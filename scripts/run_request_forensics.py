"""Per-request forensics: P / S / T, matched tools, on data/otel_demo (multifault manifest).

PRE-REGISTERED in results/REQUEST_FORENSICS_PREREG.md BEFORE the first model cell. Everything in the
"FIXED" block is part of that document; changing any of it means a NEW output file (`--tag`), not a
resumed run.

Usage:
    .venv/bin/python scripts/run_request_forensics.py --cases-only          # build + freeze the sample
    .venv/bin/python scripts/run_request_forensics.py --pilot --tag smoke    # harness smoke, disjoint seeds
    .venv/bin/python scripts/run_request_forensics.py                        # the pre-registered run
    # re-invoking the same command resumes: only cells without an OBSERVATION (transport/unavailable) re-run
    .venv/bin/python scripts/run_request_forensics.py --tag rep2 --models gpt-oss:120b   # noise replicate

Cloud key from the environment only:  set -a; . ./.env; set +a
A local fallback is selected by OLLAMA_HOST=http://localhost:11434 with OLLAMA_API_KEY unset.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from tokentax import forensics as F  # noqa: E402
from tokentax.forensics_stats import OBSERVED  # noqa: E402
from tokentax.methods.ollama_client import OllamaClient  # noqa: E402
from tokentax.otel_loader import windows_from_manifest  # noqa: E402

LOGS = ROOT / "data/otel_demo/logs.jsonl"
MANIFEST = ROOT / "data/otel_demo/manifest_multifault.json"
CASES_FILE = ROOT / "results/runs/request_forensics_cases.json"
OUT = ROOT / "results/runs/request_forensics.jsonl"

# ------------------------------ FIXED (see REQUEST_FORENSICS_PREREG.md) ------------------------------
SAMPLE_SEED = 20261020
MAIN_N = {"productCatalogFailure": 11, "adFailure": 10, "cartFailure": 9}   # 30 seeds
PILOT_N = {"productCatalogFailure": 2, "adFailure": 2}                       # 4 seeds, disjoint from MAIN
CELL_TIMEOUT_S = 300.0
MAX_ROUNDS = 20
MAX_TOTAL_TOKENS = 250_000
NUM_CTX = 32_768
CONCURRENCY = 3
MAX_RETRIES = 3          # per HTTP request, inside OllamaClient
MODELS = ["gpt-oss:120b", "nemotron-3-ultra", "gemma4:31b"]
# -----------------------------------------------------------------------------------------------------

START = time.time()


def log(m: str) -> None:
    print(f"[{time.time() - START:7.0f}s] {m}", flush=True)


def classify_error(err: str) -> str:
    """Status for a cell that raised. Neither class is a result about the model."""
    if re.search(r"Client error '(402|403|404|410)", err):
        return "unavailable"
    return "transport"


def load_cases(pilot: bool):
    """Windows + the frozen sample. The sample is also written to CASES_FILE and verified on re-load."""
    windows = windows_from_manifest(LOGS, MANIFEST)
    eligible = F.eligible_cases(windows)
    main, pilot_cases = F.sample_cases(eligible, MAIN_N, PILOT_N, SAMPLE_SEED)
    frozen = {
        "sample_seed": SAMPLE_SEED, "main_n": MAIN_N, "pilot_n": PILOT_N,
        "eligible_by_fault": {f: sum(1 for c in eligible if c.fault == f)
                              for f in sorted({c.fault for c in eligible})},
        "main": [_case_json(c) for c in main], "pilot": [_case_json(c) for c in pilot_cases],
    }
    if CASES_FILE.exists():
        old = json.loads(CASES_FILE.read_text())
        if old != frozen:
            raise SystemExit(f"sample drifted from {CASES_FILE}; refusing to run a different sample "
                             "under the same name")
    else:
        CASES_FILE.parent.mkdir(parents=True, exist_ok=True)
        CASES_FILE.write_text(json.dumps(frozen, indent=1))
        log(f"froze sample -> {CASES_FILE}")
    return windows, (pilot_cases if pilot else main)


def _case_json(c: F.Case) -> dict:
    return {"key": c.key, "fault": c.fault, "window_idx": c.window_idx, "seed_idx": c.seed_idx,
            "trace_id": c.trace_id, "seed_service": c.seed_service, "root_service": c.root_service,
            "n_services": c.n_services, "n_truth": len(c.truth), "truth": list(c.truth)}


def read_rows(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(x) for x in path.read_text().splitlines() if x.strip()]


def done_keys(path: Path) -> set:
    """Cells that need no more work: any OBSERVATION. A transport row is still owed."""
    return {(r["model"], r["arm"], r["case"]) for r in read_rows(path) if r["status"] in OBSERVED}


async def run_cell(sem, path: Path, model: str, arm: str, case: F.Case, windows) -> dict:
    async with sem:
        cond = F.ARMS[arm]
        records = windows[case.window_idx].records
        client = OllamaClient(model=model, timeout=CELL_TIMEOUT_S, max_retries=MAX_RETRIES)
        meter = F.Meter()
        t0 = time.perf_counter()
        status, err, outcome = "", "", None
        try:
            outcome = await asyncio.wait_for(
                F.run_agent(client, records, cond, case, meter, MAX_ROUNDS, MAX_TOTAL_TOKENS, NUM_CTX),
                timeout=CELL_TIMEOUT_S)
        except TimeoutError:
            status, err = "timeout", "timeout"
        except Exception as e:  # noqa: BLE001 - record, never crash the run
            err = f"{type(e).__name__}: {e}"[:300]
            status = classify_error(err)
        latency = time.perf_counter() - t0

        if outcome is not None:
            status = "answered" if outcome.indices is not None else "no_answer"
        if status in OBSERVED:
            idx = outcome.indices if (outcome and outcome.indices is not None) else []
            sc = F.score_lines(idx, case)
            if status != "answered":   # a failure is scored as no answer, never as a partial credit
                sc = {**sc, "precision": 0.0, "recall": 0.0, "f1": 0.0, "tp": 0, "n_pred": 0}
            pred_root = outcome.root if outcome else ""
        else:
            idx, sc, pred_root = [], {"precision": 0.0, "recall": 0.0, "f1": 0.0, "tp": 0,
                                      "n_pred": 0, "n_truth": len(case.truth)}, ""
        row = {
            "model": model, "arm": arm, "condition": cond, "case": case.key, "fault": case.fault,
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
                    "correct_f1": F.CORRECT_F1, "host": client.host},
        }
        with path.open("a") as f:
            f.write(json.dumps(row) + "\n")
        flag = {"answered": "ok " if row["correct"] else "MISS", "no_answer": "NOANS",
                "timeout": "TMO", "transport": "XPORT", "unavailable": "UNAVL"}[status]
        log(f"  {flag:5s} {model:18s} {arm} {case.fault[:8]:8s} f1={row['f1']:.2f} "
            f"tok={row['total_tok']:<8,} r={meter.rounds:<2} first={row['first_tool'] or '-':<14s} "
            f"{err[:70]}")
        return row


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cases-only", action="store_true")
    ap.add_argument("--pilot", action="store_true", help="the 4 disjoint pilot seeds, not the main 30")
    ap.add_argument("--tag", default="", help="output suffix; a config change needs a new tag")
    ap.add_argument("--models", default="")
    ap.add_argument("--concurrency", type=int, default=CONCURRENCY)
    ap.add_argument("--limit", type=int, default=0, help="debug: first N seeds only")
    a = ap.parse_args()
    if a.concurrency > 3:
        print("concurrency is capped at 3 by the brief", file=sys.stderr)
        return 2

    windows, cases = load_cases(a.pilot)
    if a.cases_only:
        log(f"{len(cases)} {'pilot' if a.pilot else 'main'} seeds")
        return 0
    if a.limit:
        cases = cases[:a.limit]

    path = ROOT / f"results/runs/request_forensics{('_' + a.tag) if a.tag else ''}.jsonl"
    local = "localhost" in os.getenv("OLLAMA_HOST", "") or "127.0.0.1" in os.getenv("OLLAMA_HOST", "")
    if not local and not os.getenv("OLLAMA_API_KEY"):
        print("OLLAMA_API_KEY not set (set -a; . ./.env; set +a)", file=sys.stderr)
        return 2

    models = [m.strip() for m in a.models.split(",") if m.strip()] or MODELS
    done = done_keys(path)
    # seed-major, arms adjacent: if the account hits a usage limit mid-run, what finished is whole triples
    todo = [(m, arm, c) for c in cases for m in models for arm in F.ARMS
            if (m, arm, c.key) not in done]
    log(f"{len(cases)} seeds x {len(F.ARMS)} arms x {len(models)} models = "
        f"{len(cases) * len(F.ARMS) * len(models)} cells; {len(done)} done, {len(todo)} to run -> {path.name}")
    sem = asyncio.Semaphore(a.concurrency)
    await asyncio.gather(*(run_cell(sem, path, m, arm, c, windows) for m, arm, c in todo))
    left = [r for r in read_rows(path) if r["status"] not in OBSERVED]
    n_obs = len(done_keys(path))
    log(f"finished: {n_obs} observed cells; {len({(r['model'], r['arm'], r['case']) for r in left} - done_keys(path))}"
        " cells still owed (transport/unavailable)")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
