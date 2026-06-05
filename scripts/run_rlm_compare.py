"""tool-RLM (grep navigator) vs recursive-RLM, plain vs structured, across tool-capable models.

One productCatalogFailure window (capped) so the recursive sub-LM calls stay tractable. Grouped by
model, resumable (skips done cells), per-cell timeout, robust. Writes results/runs/rlm_compare.jsonl;
run scripts/gen_rlm_compare_report.py after to build results/RLM_COMPARISON.md.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from tokentax.methods.ollama_client import OllamaClient  # noqa: E402
from tokentax.methods.rlm import RLMMethod  # noqa: E402
from tokentax.methods.rlm_recursive import RecursiveRLM  # noqa: E402
from tokentax.otel_loader import windows_from_manifest  # noqa: E402

LOGS = ROOT / "data/otel_demo/logs.jsonl"
MANI = ROOT / "data/otel_demo/manifest_sweep1.json"
OUT = ROOT / "results/runs/rlm_compare.jsonl"
OLLAMA = "/Applications/Ollama.app/Contents/Resources/ollama"
TRUTH = "product-catalog"
START = time.time()


def log(m): print(f"[{time.time()-START:6.0f}s] {m}", flush=True)


def correct(pred: str) -> bool:
    return "catalog" in re.sub(r"[^a-z0-9]", "", str(pred).lower())


def done() -> set:
    if not OUT.exists():
        return set()
    return {(json.loads(x)["model"], json.loads(x)["method"], json.loads(x)["condition"])
            for x in OUT.read_text().splitlines() if x.strip()}


def append(row):
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "a") as f:
        f.write(json.dumps(row) + "\n")


def ensure(model: str) -> bool:
    try:
        r = subprocess.run([OLLAMA, "run", model, "ok"], capture_output=True, text=True, timeout=200)
        return r.returncode == 0
    except subprocess.TimeoutExpired:
        return False


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-records", type=int, default=200)
    ap.add_argument("--budget-sec", type=int, default=5400)
    ap.add_argument("--cell-timeout", type=float, default=300)
    ap.add_argument("--models", nargs="+",
                    default=["qwen3:8b", "qwen3.5:9b", "gpt-oss:20b", "gemma4:e4b"])
    args = ap.parse_args()
    recs = windows_from_manifest(LOGS, MANI)[0].records[: args.max_records]
    dn = done()
    log(f"window {len(recs)} records | {len(args.models)} models x 2 methods x 2 conditions | {len(dn)} done")

    for model in args.models:
        if time.time() - START > args.budget_sec:
            break
        if all((model, mth, c) in dn for mth in ("tool", "recursive") for c in ("plain", "structured")):
            log(f"{model}: done, skip")
            continue
        log(f"=== {model} ===")
        if not ensure(model):
            log(f"{model}: load failed, skip")
            continue
        client = OllamaClient(host="http://localhost:11434", model=model, max_retries=2)
        tool = RLMMethod(client, max_rounds=14, num_ctx=16384)
        rec = RecursiveRLM(client, max_rounds=12, sub_num_ctx=16384, root_num_ctx=8192)
        for cond in ("plain", "structured"):
            for mname, meth in (("tool", tool), ("recursive", rec)):
                if (model, mname, cond) in dn or time.time() - START > args.budget_sec:
                    continue
                t0 = time.time()
                try:
                    r = await asyncio.wait_for(meth.apredict(recs, cond, "root_cause"), args.cell_timeout)
                    if mname == "recursive":
                        row = {"pred": r.prediction, "total_tok": r.total_tokens,
                               "root_tok": r.root_in + r.root_out, "sub_tok": r.sub_in + r.sub_out,
                               "subcalls": r.n_subcalls, "max_root_prompt": r.max_root_prompt,
                               "rounds": r.rounds, "aborted": r.aborted}
                    else:
                        row = {"pred": str(r.prediction), "total_tok": r.total_tokens,
                               "root_tok": r.total_tokens, "sub_tok": 0, "subcalls": 0,
                               "max_root_prompt": 0, "rounds": r.rlm_rounds, "aborted": r.aborted}
                    row.update(correct=correct(row["pred"]), latency_s=round(time.time() - t0, 1), error="")
                except Exception as e:  # noqa: BLE001 - unattended: never die on a cell
                    row = {"pred": "ERROR", "total_tok": 0, "root_tok": 0, "sub_tok": 0, "subcalls": 0,
                           "max_root_prompt": 0, "rounds": 0, "aborted": True, "correct": False,
                           "latency_s": round(time.time() - t0, 1),
                           "error": ("timeout" if isinstance(e, TimeoutError) else str(e)[:120])}
                append({"model": model, "method": mname, "condition": cond, **row})
                log(f"  {mname:9s} {cond:10s} -> {str(row['pred'])[:16]:16s} ok={row['correct']} "
                    f"tok={row['total_tok']:>6} subcalls={row['subcalls']} maxRoot={row['max_root_prompt']}")
        subprocess.run([OLLAMA, "stop", model], capture_output=True)
    log("COMPARE COMPLETE")


if __name__ == "__main__":
    asyncio.run(main())
