"""Per-request forensics V3: Tt and Th on three models, with fresh controls, pre-registered in
results/REQUEST_FORENSICS_V3_PREREG.md BEFORE the first main cell.

Reuses V1/V2 wholesale: the frozen 30-seed sample and its verification (`run_request_forensics.load_cases`),
error classification, the resume rule (only cells without an OBSERVATION re-run), the usage-limit guard
(`forensics_v2.GuardedOllamaClient`) and the row format. New here:

  * arms Tt and Th (`forensics_v3`); every arm, old and new, runs through `forensics_v3.run_agent_v3`
    (tests/test_forensics_v3.py: identical messages to the V1 loop for P / S / T);
  * ONE queue in the pre-registered PLAN order, drained by `--concurrency` workers (<= 3, the account's
    concurrent-request limit on Ollama Pro, so no request waits in the provider's queue);
  * a SPEND CAP: estimated cost at peak list prices; once it passes the cap no new cell starts (cells in
    flight finish and are kept), the rest stay owed and the write-up is marked PARTIAL;
  * two pre-registered secondary fields per row: `grep_trace`, `lookup_trace` (forensics_v3.used_trace_id).

FIXED (see the PREREG; changing any of it is a new --tag, never a resumed run):
  timeout 300 s, max rounds 20, token ceiling 250,000, num_ctx 32,768, temperature 0, seed 0, think=False,
  3 HTTP retries, lines_near 40 lines / 30 s, correct := F1 >= 0.8, concurrency 3, spend cap $45.

Usage:
    set -a; . ./.env; set +a
    .venv/bin/python scripts/run_request_forensics_v3.py --pilot --tag smoke --limit 1 --plan smoke
    .venv/bin/python scripts/run_request_forensics_v3.py                        # main, the PLAN below
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from tokentax import forensics as F  # noqa: E402
from tokentax import forensics_v2 as V2  # noqa: E402
from tokentax import forensics_v3 as V3  # noqa: E402
from tokentax.forensics_stats import OBSERVED  # noqa: E402

_spec = importlib.util.spec_from_file_location("rf1", ROOT / "scripts/run_request_forensics.py")
RF = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(RF)

# ------------------------------ FIXED (see REQUEST_FORENSICS_V3_PREREG.md) ------------------------------
CELL_TIMEOUT_S = RF.CELL_TIMEOUT_S        # 300
MAX_ROUNDS = RF.MAX_ROUNDS                # 20
MAX_TOTAL_TOKENS = RF.MAX_TOTAL_TOKENS    # 250,000
NUM_CTX = RF.NUM_CTX                      # 32,768
MAX_RETRIES = RF.MAX_RETRIES              # 3
MAX_CONCURRENCY = 3
SPEND_CAP_USD = 45.0
OUT_STEM = "request_forensics_v3"

A, B, C = "beam", "minimax-m3.1-flash", "deepseek-v4-pro:0813"
# Phases in priority order. Inside a phase: seed-major, the phase's arms adjacent in the order given.
PLAN = [
    (A, ("P", "S", "T", "Tt", "Th")),     # 1. model A, every arm (cheap)
    (C, ("T", "Tt", "Th")),               # 2. model C, the trace arms
    (B, ("T", "Tt", "Th")),               # 3. model B, the trace arms
    (C, ("P", "S")),                      # 4. model C, the baselines
    (B, ("P", "S")),                      # 5. model B, fresh baselines (V2 has 0/30 and 0/30)
]
SMOKE_PLAN = [(m, ("Tt", "Th")) for m in (A, C, B)]

# Peak list prices, USD per million tokens (input, output), https://ollama.com/pricing on 2026-10-25.
# beam is not on the price list; it is estimated at a deliberately high rate so the cap stays conservative.
PRICE = {A: (1.00, 4.00), B: (0.15, 0.60), C: (1.32, 3.96)}
# ---------------------------------------------------------------------------------------------------------

START = time.time()
STOP = asyncio.Event()
SPENT = {"usd": 0.0}
STOP_REASON = {"why": ""}


def log(m: str) -> None:
    print(f"[{time.time() - START:7.0f}s] {m}", flush=True)


def cost(model: str, in_tok: int, out_tok: int) -> float:
    pin, pout = PRICE.get(model, (3.00, 15.00))
    return (in_tok * pin + out_tok * pout) / 1e6


def done_keys(path: Path) -> set:
    return {(r["model"], r["arm"], r["case"]) for r in RF.read_rows(path) if r["status"] in OBSERVED}


def prior_spend(path: Path) -> float:
    return sum(cost(r["model"], r.get("in_tok", 0), r.get("out_tok", 0)) for r in RF.read_rows(path))


async def run_cell(path: Path, model: str, arm: str, case: F.Case, windows, phase: int) -> dict:
    cond = V3.ARMS_V3[arm]
    records = windows[case.window_idx].records
    client = V2.GuardedOllamaClient(model=model, timeout=CELL_TIMEOUT_S, max_retries=MAX_RETRIES)
    meter = F.Meter()
    t0 = time.perf_counter()
    status, err, outcome = "", "", None
    try:
        outcome = await asyncio.wait_for(
            V3.run_agent_v3(client, records, cond, case, meter, MAX_ROUNDS, MAX_TOTAL_TOKENS, NUM_CTX),
            timeout=CELL_TIMEOUT_S)
    except TimeoutError:
        status, err = "timeout", "timeout"
    except V2.UsageLimitReached as e:
        status, err = "transport", f"usage_limit: {e}"[:300]
        STOP_REASON["why"] = "usage limit"
        STOP.set()
    except Exception as e:  # noqa: BLE001 - record, never crash the run
        err = f"{type(e).__name__}: {e}"[:300]
        status = RF.classify_error(err)
    latency = time.perf_counter() - t0

    if outcome is not None:
        status = "answered" if outcome.indices is not None else "no_answer"
    if status in OBSERVED:
        idx = outcome.indices if (outcome and outcome.indices is not None) else []
        sc = F.score_lines(idx, case)
        if status != "answered":
            sc = {**sc, "precision": 0.0, "recall": 0.0, "f1": 0.0, "tp": 0, "n_pred": 0}
        pred_root = outcome.root if outcome else ""
    else:
        idx, sc, pred_root = [], {"precision": 0.0, "recall": 0.0, "f1": 0.0, "tp": 0,
                                  "n_pred": 0, "n_truth": len(case.truth)}, ""
    seed_trace = records[case.seed_idx].trace_id
    use = V3.used_trace_id(meter.trace, seed_trace)
    usd = cost(model, meter.in_tok, meter.out_tok)
    SPENT["usd"] += usd
    row = {
        "run": "v3", "phase": phase, "model": model, "arm": arm, "condition": cond, "case": case.key,
        "fault": case.fault, "status": status, "error": err,
        "pred_indices": idx, "pred_root": pred_root,
        "precision": round(sc["precision"], 4), "recall": round(sc["recall"], 4),
        "f1": round(sc["f1"], 4), "n_pred": sc["n_pred"], "n_truth": len(case.truth),
        "correct": bool(status == "answered" and sc["f1"] >= F.CORRECT_F1),
        "root_correct": bool(status == "answered" and F.root_correct(pred_root, case.root_service)),
        "truth_root": case.root_service, "seed_service": case.seed_service,
        "n_services": case.n_services, "seed_trace": seed_trace,
        "grep_trace": use["grep_trace"], "lookup_trace": use["lookup_trace"],
        "in_tok": meter.in_tok, "out_tok": meter.out_tok, "total_tok": meter.total,
        "est_usd": round(usd, 5),
        "censored": status == "timeout",
        "rounds": meter.rounds, "max_prompt_tok": meter.max_prompt_tok,
        "tools_used": meter.tools, "first_tool": meter.tools[0] if meter.tools else "",
        "n_not_available": meter.not_available,
        "aborted": bool(outcome and outcome.aborted),
        "abort_reason": outcome.abort_reason if outcome else "",
        "latency_s": round(latency, 1),
        "trace": meter.trace,
        "cfg": {"timeout": CELL_TIMEOUT_S, "max_rounds": MAX_ROUNDS, "num_ctx": NUM_CTX,
                "max_total_tokens": MAX_TOTAL_TOKENS, "lines_near_max": F.NEAR_MAX_LINES,
                "correct_f1": F.CORRECT_F1, "host": client.host, "max_retries": MAX_RETRIES,
                "concurrency": MAX_CONCURRENCY, "spend_cap_usd": SPEND_CAP_USD},
    }
    with path.open("a") as f:
        f.write(json.dumps(row) + "\n")
    flag = {"answered": "ok " if row["correct"] else "MISS", "no_answer": "NOANS",
            "timeout": "TMO", "transport": "XPORT", "unavailable": "UNAVL"}[status]
    log(f"  {flag:5s} p{phase} {model:22s} {arm:2s} {case.fault[:8]:8s} f1={row['f1']:.2f} "
        f"tok={row['total_tok']:<8,} r={meter.rounds:<2} grepT={int(use['grep_trace'])} "
        f"${SPENT['usd']:.2f} {err[:50]}")
    if SPENT["usd"] >= SPEND_CAP_USD and not STOP.is_set():
        STOP_REASON["why"] = f"spend cap ${SPEND_CAP_USD:.0f}"
        STOP.set()
    return row


async def worker(q: asyncio.Queue, path, windows) -> None:
    while True:
        try:
            item = q.get_nowait()
        except asyncio.QueueEmpty:
            return
        if STOP.is_set():
            q.task_done()
            continue
        phase, model, arm, case = item
        await run_cell(path, model, arm, case, windows, phase)
        q.task_done()


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pilot", action="store_true", help="the 4 disjoint pilot seeds, not the main 30")
    ap.add_argument("--tag", default="", help="output suffix (smoke / ...); config changes need one")
    ap.add_argument("--plan", default="main", choices=["main", "smoke"])
    ap.add_argument("--concurrency", type=int, default=MAX_CONCURRENCY)
    ap.add_argument("--limit", type=int, default=0, help="first N seeds only (smoke)")
    ap.add_argument("--dry-run", action="store_true", help="print the queue and exit")
    a = ap.parse_args()
    if a.concurrency > MAX_CONCURRENCY:
        print(f"concurrency is capped at {MAX_CONCURRENCY}", file=sys.stderr)
        return 2
    if a.plan == "smoke" and not a.tag:
        print("the smoke plan needs --tag", file=sys.stderr)
        return 2

    windows, cases = RF.load_cases(a.pilot)        # verifies the frozen sample
    if a.limit:
        cases = cases[:a.limit]
    path = ROOT / f"results/runs/{OUT_STEM}{('_' + a.tag) if a.tag else ''}.jsonl"
    if not os.getenv("OLLAMA_API_KEY"):
        print("OLLAMA_API_KEY not set (set -a; . ./.env; set +a)", file=sys.stderr)
        return 2
    if "ollama.com" not in os.getenv("OLLAMA_HOST", "https://ollama.com/api"):
        print("V3 runs on Ollama Cloud only", file=sys.stderr)
        return 2

    plan = PLAN if a.plan == "main" else SMOKE_PLAN
    done = done_keys(path)
    SPENT["usd"] = prior_spend(path)
    q: asyncio.Queue = asyncio.Queue()
    n_total = 0
    for phase, (model, arms) in enumerate(plan, 1):
        todo = [(arm, c) for c in cases for arm in arms if (model, arm, c.key) not in done]
        n_total += len(cases) * len(arms)
        log(f"phase {phase}: {model} x {arms}: {len(todo)} of {len(cases) * len(arms)} cells to run")
        for arm, c in todo:
            q.put_nowait((phase, model, arm, c))
    log(f"{q.qsize()} cells queued -> {path.name}; prior est. spend ${SPENT['usd']:.2f}, cap ${SPEND_CAP_USD:.0f}")
    if a.dry_run:
        return 0
    await asyncio.gather(*(worker(q, path, windows) for _ in range(a.concurrency)))
    if STOP.is_set():
        log(f"STOPPED ({STOP_REASON['why']}). Results so far are PARTIAL; owed cells stay owed.")
    obs = done_keys(path)
    owed = [(m, arm, c.key) for m, arms in plan for c in cases for arm in arms if (m, arm, c.key) not in obs]
    log(f"finished: {len(obs)} observed cells of {n_total}; {len(owed)} owed; est. spend ${SPENT['usd']:.2f}")
    return 3 if STOP.is_set() else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
