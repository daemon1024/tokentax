"""Corrected cross-model matrix: tool-RLM vs recursive-RLM x plain/structured x 4 models x 12 windows.

Re-runs the cross-model evaluation with the FIXED code (condition-aware LogREPL: plain is truly plain;
structured exposes svc/sev/trace + the errors_by_service digest). Supersedes the leaky matrix.jsonl.
Time-budgeted, resumable, per-cell timeout, self-committing, robust. Writes matrix_v2.jsonl +
regenerates MATRIX_RESULTS_V2.md after each model.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import subprocess
import sys
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from tokentax.methods.ollama_client import OllamaClient  # noqa: E402
from tokentax.methods.rlm import RLMMethod  # noqa: E402
from tokentax.methods.rlm_recursive import RecursiveRLM  # noqa: E402
from tokentax.otel_loader import windows_from_manifest  # noqa: E402

LOGS = ROOT / "data/otel_demo/logs.jsonl"
MF = ROOT / "data/otel_demo/manifest_multifault.json"
OUT = ROOT / "results/runs/matrix_v2.jsonl"
DOC = ROOT / "results/MATRIX_RESULTS_V2.md"
OLLAMA = "/Applications/Ollama.app/Contents/Resources/ollama"
ORIGIN = {"productCatalogFailure": "product-catalog", "cartFailure": "cart", "adFailure": "ad"}
START = time.time()


def log(m): print(f"[{time.time()-START:7.0f}s] {m}", flush=True)


def truth_of(w) -> str:
    return ORIGIN.get(w.fault or "", "none") if w.label == "anomalous" else "none"


def correct(pred: str, truth: str) -> bool:
    n = re.sub(r"[^a-z0-9]", "", str(pred).lower())
    if truth == "none":
        return n in ("none", "", "unknown") or n.startswith("no")
    t = re.sub(r"[^a-z0-9]", "", truth)
    return t in n or (truth == "product-catalog" and "catalog" in n)


def done() -> set:
    if not OUT.exists():
        return set()
    return {(r["model"], r["method"], r["condition"], r["window"])
            for r in (json.loads(x) for x in OUT.read_text().splitlines() if x.strip())}


def append(row):
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "a") as f:
        f.write(json.dumps(row) + "\n")


def ensure(model):
    try:
        return subprocess.run([OLLAMA, "run", model, "ok"], capture_output=True, text=True,
                              timeout=200).returncode == 0
    except subprocess.TimeoutExpired:
        return False


def commit(msg):
    co = "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
    subprocess.run(["git", "-C", str(ROOT), "add", "-f", "results/runs/matrix_v2.jsonl"], capture_output=True)
    subprocess.run(["git", "-C", str(ROOT), "add", "results/MATRIX_RESULTS_V2.md"], capture_output=True)
    subprocess.run(["git", "-C", str(ROOT), "commit", "-q", "-m", msg, "-m", co], capture_output=True)


def regen(models):
    rows = [json.loads(x) for x in OUT.read_text().splitlines() if x.strip()] if OUT.exists() else []
    agg = defaultdict(lambda: {"n": 0, "ok": 0, "tok": 0, "sub": 0, "ab": 0})
    for r in rows:
        a = agg[(r["model"], r["method"], r["condition"])]
        a["n"] += 1
        a["ok"] += int(r["correct"])
        a["tok"] += r["total_tok"]
        a["sub"] += r.get("subcalls", 0)
        a["ab"] += int(r.get("aborted", False))
    out = ["# Corrected cross-model matrix (tool-RLM vs recursive-RLM)", "",
           f"{len(rows)}/192 cells. 4 tool-capable models x 12 multifault OTel windows x 2 methods x "
           "2 conditions. Fixed code: plain truly plain; structured has svc/sev/trace tags + the "
           "errors_by_service digest. Cell = accuracy, mean tokens, mean sub-calls, abort%.", "",
           "| model | method | cond | n | acc | mean_tok | mean_sub | abort% |",
           "|---|---|---|---|---|---|---|---|"]
    for (m, meth, c), a in sorted(agg.items()):
        n = a["n"]
        out.append(f"| {m} | {meth} | {c} | {n} | {a['ok']/n:.2f} | {a['tok']//n:,} | "
                   f"{a['sub']/n:.1f} | {100*a['ab']//n}% |")
    DOC.write_text("\n".join(out) + "\n")


async def cell(meth, records, condition, timeout):
    t0 = time.time()
    try:
        r = await asyncio.wait_for(meth.apredict(records, condition, "root_cause"), timeout)
        if hasattr(r, "root_in"):  # recursive
            return dict(pred=r.prediction, total_tok=r.total_tokens, subcalls=r.n_subcalls,
                        max_root=r.max_root_prompt, rounds=r.rounds, aborted=r.aborted,
                        latency_s=round(time.time()-t0, 1), error="")
        return dict(pred=str(r.prediction), total_tok=r.total_tokens, subcalls=0, max_root=0,
                    rounds=r.rlm_rounds, aborted=r.aborted, latency_s=round(time.time()-t0, 1), error="")
    except Exception as e:  # noqa: BLE001
        return dict(pred="ERROR", total_tok=0, subcalls=0, max_root=0, rounds=0, aborted=True,
                    latency_s=round(time.time()-t0, 1),
                    error="timeout" if isinstance(e, TimeoutError) else str(e)[:120])


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--budget-sec", type=int, default=9000)
    ap.add_argument("--cell-timeout", type=float, default=240)
    ap.add_argument("--models", nargs="+",
                    default=["qwen3:8b", "qwen3.5:9b", "gpt-oss:20b", "gemma4:e4b"])
    args = ap.parse_args()
    windows = sorted(windows_from_manifest(LOGS, MF), key=lambda w: w.key)
    dn = done()
    log(f"{len(args.models)} models x {len(windows)} windows x 2 methods x 2 cond | {len(dn)} done")
    for model in args.models:
        if time.time()-START > args.budget_sec:
            break
        todo = [(w, mth, c) for w in windows for mth in ("tool", "recursive")
                for c in ("plain", "structured") if (model, mth, c, w.key) not in dn]
        if not todo:
            log(f"{model}: done")
            continue
        log(f"=== {model}: {len(todo)} cells ===")
        if not ensure(model):
            log(f"{model}: load failed, skip")
            continue
        client = OllamaClient(host="http://localhost:11434", model=model, max_retries=2)
        methods = {"tool": RLMMethod(client, max_rounds=14, num_ctx=16384),
                   "recursive": RecursiveRLM(client, max_rounds=12, sub_num_ctx=16384, root_num_ctx=8192)}
        for w, mth, c in todo:
            if time.time()-START > args.budget_sec:
                log("budget out")
                break
            res = await cell(methods[mth], w.records, c, args.cell_timeout)
            tr = truth_of(w)
            append({"model": model, "method": mth, "condition": c, "window": w.key,
                    "truth": tr, "correct": correct(res["pred"], tr), **res})
            log(f"  {mth:9s} {c:10s} {w.fault or 'normal':22s} -> {str(res['pred'])[:14]:14s} "
                f"ok={correct(res['pred'], tr)} tok={res['total_tok']:>6} sub={res['subcalls']}")
        subprocess.run([OLLAMA, "stop", model], capture_output=True)
        regen(args.models)
        commit(f"matrix-v2: {model} cells (corrected cross-model run)")
        log(f"=== {model} committed ===")
    regen(args.models)
    commit("matrix-v2: checkpoint")
    log("RUN COMPLETE")


if __name__ == "__main__":
    asyncio.run(main())
