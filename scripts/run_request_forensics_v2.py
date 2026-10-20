"""Per-request forensics V2: P / S / T / TI on data/otel_demo, pre-registered in
results/REQUEST_FORENSICS_V2_PREREG.md BEFORE the first main cell.

Reuses V1 wholesale: the frozen 30-seed sample and its verification (`run_request_forensics.load_cases`,
which refuses to run if the sample drifted from results/runs/request_forensics_cases.json), the error
classification, the resume rule (only cells without an OBSERVATION re-run) and the row format. New here:

  * arm TI (`forensics_v2`), run in the same cell loop as the V1 arms;
  * `GuardedOllamaClient`: an HTTP 429 whose body says "usage limit" stops the WHOLE run at once
    (no retry loop); cells already observed stay, the rest stay owed, the write-up is marked PARTIAL;
  * MODEL-major order: every arm and seed of model 1 before model 2, so a quota cut-off leaves complete
    paired comparisons for the models that finished; inside a model, seed-major with the four arms
    adjacent;
  * concurrency <= 2.

FIXED (see the PREREG; changing any of it is a new --tag, never a resumed run):
  V1 config verbatim: timeout 300 s, max rounds 20, token ceiling 250,000, num_ctx 32,768,
  temperature 0, seed 0, think=False, 3 HTTP retries, lines_near 40 lines / 30 s, correct := F1 >= 0.8.

Usage:
    .venv/bin/python scripts/run_request_forensics_v2.py --pilot --tag local --models qwen3.5:9b   # local
    .venv/bin/python scripts/run_request_forensics_v2.py --pilot --tag smoke --limit 1 --models M  # smoke
    .venv/bin/python scripts/run_request_forensics_v2.py --models M1,M2                            # main
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
from tokentax import forensics_v2 as V  # noqa: E402
from tokentax.forensics_stats import OBSERVED  # noqa: E402

_spec = importlib.util.spec_from_file_location("rf1", ROOT / "scripts/run_request_forensics.py")
RF = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(RF)

# ------------------------------ FIXED (see REQUEST_FORENSICS_V2_PREREG.md) ------------------------------
CELL_TIMEOUT_S = RF.CELL_TIMEOUT_S        # 300
MAX_ROUNDS = RF.MAX_ROUNDS                # 20
MAX_TOTAL_TOKENS = RF.MAX_TOTAL_TOKENS    # 250,000
NUM_CTX = RF.NUM_CTX                      # 32,768
MAX_RETRIES = RF.MAX_RETRIES              # 3
MAX_CONCURRENCY = 2
OUT_STEM = "request_forensics_v2"
# ---------------------------------------------------------------------------------------------------------

START = time.time()
STOP = asyncio.Event()


def log(m: str) -> None:
    print(f"[{time.time() - START:7.0f}s] {m}", flush=True)


def done_keys(path: Path) -> set:
    return {(r["model"], r["arm"], r["case"]) for r in RF.read_rows(path) if r["status"] in OBSERVED}


async def run_cell(sem, path: Path, model: str, arm: str, case: F.Case, windows) -> dict | None:
    async with sem:
        if STOP.is_set():
            return None
        cond = V.ARMS_V2[arm]
        records = windows[case.window_idx].records
        client = V.GuardedOllamaClient(model=model, timeout=CELL_TIMEOUT_S, max_retries=MAX_RETRIES)
        meter = F.Meter()
        t0 = time.perf_counter()
        status, err, outcome = "", "", None
        try:
            outcome = await asyncio.wait_for(
                V.run_cell_agent(client, records, cond, case, meter, MAX_ROUNDS, MAX_TOTAL_TOKENS, NUM_CTX),
                timeout=CELL_TIMEOUT_S)
        except TimeoutError:
            status, err = "timeout", "timeout"
        except V.UsageLimitReached as e:
            status, err = "transport", f"usage_limit: {e}"[:300]
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
        row = {
            "run": "v2", "model": model, "arm": arm, "condition": cond, "case": case.key, "fault": case.fault,
            "status": status, "error": err,
            "pred_indices": idx, "pred_root": pred_root,
            "precision": round(sc["precision"], 4), "recall": round(sc["recall"], 4),
            "f1": round(sc["f1"], 4), "n_pred": sc["n_pred"], "n_truth": len(case.truth),
            "correct": bool(status == "answered" and sc["f1"] >= F.CORRECT_F1),
            "root_correct": bool(status == "answered" and F.root_correct(pred_root, case.root_service)),
            "truth_root": case.root_service, "seed_service": case.seed_service,
            "n_services": case.n_services,
            "in_tok": meter.in_tok, "out_tok": meter.out_tok, "total_tok": meter.total,
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
                    "correct_f1": F.CORRECT_F1, "host": client.host, "max_retries": MAX_RETRIES},
        }
        with path.open("a") as f:
            f.write(json.dumps(row) + "\n")
        flag = {"answered": "ok " if row["correct"] else "MISS", "no_answer": "NOANS",
                "timeout": "TMO", "transport": "XPORT", "unavailable": "UNAVL"}[status]
        log(f"  {flag:5s} {model:24s} {arm:2s} {case.fault[:8]:8s} f1={row['f1']:.2f} "
            f"tok={row['total_tok']:<8,} r={meter.rounds:<2} first={row['first_tool'] or '-':<14s} {err[:60]}")
        return row


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pilot", action="store_true", help="the 4 disjoint pilot seeds, not the main 30")
    ap.add_argument("--tag", default="", help="output suffix (local / smoke / rep2); config changes need one")
    ap.add_argument("--models", required=True, help="comma-separated, in priority order")
    ap.add_argument("--arms", default=",".join(V.ARM_ORDER))
    ap.add_argument("--concurrency", type=int, default=MAX_CONCURRENCY)
    ap.add_argument("--limit", type=int, default=0, help="first N seeds only (smoke)")
    a = ap.parse_args()
    if a.concurrency > MAX_CONCURRENCY:
        print(f"concurrency is capped at {MAX_CONCURRENCY}", file=sys.stderr)
        return 2
    arms = tuple(x.strip() for x in a.arms.split(",") if x.strip())
    if any(x not in V.ARMS_V2 for x in arms):
        print(f"unknown arm in {arms}", file=sys.stderr)
        return 2

    windows, cases = RF.load_cases(a.pilot)        # verifies the frozen sample
    if a.limit:
        cases = cases[:a.limit]
    path = ROOT / f"results/runs/{OUT_STEM}{('_' + a.tag) if a.tag else ''}.jsonl"
    local = "localhost" in os.getenv("OLLAMA_HOST", "") or "127.0.0.1" in os.getenv("OLLAMA_HOST", "")
    if local and os.getenv("OLLAMA_API_KEY"):
        print("local host requested but OLLAMA_API_KEY is set; unset it for a local run", file=sys.stderr)
        return 2
    if not local and not os.getenv("OLLAMA_API_KEY"):
        print("OLLAMA_API_KEY not set (set -a; . ./.env; set +a)", file=sys.stderr)
        return 2
    if not a.tag and not local and "ollama.com" not in os.getenv("OLLAMA_HOST", "https://ollama.com/api"):
        print("main run must target Ollama Cloud", file=sys.stderr)
        return 2

    models = [m.strip() for m in a.models.split(",") if m.strip()]
    done = done_keys(path)
    sem = asyncio.Semaphore(a.concurrency)
    for m in models:                                    # MODEL-major
        todo = [(arm, c) for c in cases for arm in arms if (m, arm, c.key) not in done]
        log(f"{m}: {len(cases)} seeds x {len(arms)} arms; {len(todo)} cells to run -> {path.name}")
        await asyncio.gather(*(run_cell(sem, path, m, arm, c, windows) for arm, c in todo))
        if STOP.is_set():
            log("USAGE LIMIT reached: run stopped. Results so far are PARTIAL; owed cells stay owed.")
            break
    owed = [(m, arm, c.key) for m in models for c in cases for arm in arms
            if (m, arm, c.key) not in done_keys(path)]
    log(f"finished: {len(done_keys(path))} observed cells; {len(owed)} cells owed")
    return 3 if STOP.is_set() else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
