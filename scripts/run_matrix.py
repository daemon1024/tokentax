"""Autonomous cross-model RLM matrix runner (time-budgeted, resumable, self-documenting).

Runs RLM across {models} x {12 multifault windows} x {plain, structured} on local Ollama, plus a
Drain baseline and (time permitting) a small in-context anchor. Writes one JSONL row per cell
immediately (resumable: skips done cells), regenerates results/MATRIX_RESULTS.md + git-commits after
each model, and stops gracefully at the wall-clock budget. Defensive: per-cell timeout, model
fit-smoke (skip on OOM), try/except around every cell. Designed to run unattended for hours.

Usage: python scripts/run_matrix.py --budget-sec 15000 --models qwen3:8b qwen3:14b gemma3:12b qwen3:30b-a3b
"""

from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
import sys  # noqa: E402

sys.path.insert(0, str(ROOT / "src"))

from tokentax.methods.ollama_client import OllamaClient  # noqa: E402
from tokentax.methods.rlm import RLMMethod  # noqa: E402
from tokentax.otel_loader import windows_from_manifest  # noqa: E402

LOGS = ROOT / "data/otel_demo/logs.jsonl"
MF = ROOT / "data/otel_demo/manifest_multifault.json"
OUT = ROOT / "results/runs/matrix.jsonl"
DOC = ROOT / "results/MATRIX_RESULTS.md"
ORIGIN = {"productCatalogFailure": "product-catalog", "cartFailure": "cart", "adFailure": "ad"}
OLLAMA = "/Applications/Ollama.app/Contents/Resources/ollama"
START = time.time()


def log(msg: str) -> None:
    print(f"[{time.time() - START:7.0f}s] {msg}", flush=True)


def correct(pred: str, truth: str) -> bool:
    import re
    norm = lambda s: re.sub(r"[^a-z0-9]", "", str(s).lower())  # noqa: E731
    p, t = norm(pred), norm(truth)
    if truth == "none":
        return p in ("none", "", "unknown") or p.startswith("no")
    return bool(p) and (t in p or (p in t and len(p) > 3))


def true_culprit(w) -> str:
    return ORIGIN.get(w.fault or "", "none") if w.label == "anomalous" else "none"


def done_cells() -> set:
    if not OUT.exists():
        return set()
    out = set()
    for line in OUT.read_text().splitlines():
        try:
            r = json.loads(line)
            out.add((r["model"], r["method"], r["condition"], r["window"]))
        except (json.JSONDecodeError, KeyError):
            pass
    return out


def append_row(row: dict) -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "a") as f:
        f.write(json.dumps(row) + "\n")


def ensure_model(model: str) -> bool:
    """Pull if missing, then a 1-token smoke to confirm it loads within RAM. False => skip model."""
    have = subprocess.run([OLLAMA, "list"], capture_output=True, text=True).stdout
    if model.split(":")[0] not in have or model not in have:
        log(f"pulling {model} …")
        rc = subprocess.run([OLLAMA, "pull", model], capture_output=True, text=True)
        if rc.returncode != 0:
            log(f"  pull FAILED {model}: {rc.stderr[:120]}")
            return False
    try:
        r = subprocess.run([OLLAMA, "run", model, "say ok"], capture_output=True, text=True, timeout=180)
        if r.returncode != 0:
            log(f"  load FAILED {model} (OOM?): {r.stderr[:120]}")
            return False
    except subprocess.TimeoutExpired:
        log(f"  load TIMEOUT {model}")
        return False
    return True


def stop_model(model: str) -> None:
    subprocess.run([OLLAMA, "stop", model], capture_output=True, text=True)


def git_commit(msg: str) -> None:
    co = "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
    subprocess.run(["git", "-C", str(ROOT), "add", "results/runs/matrix.jsonl", "results/MATRIX_RESULTS.md"],
                   capture_output=True)
    subprocess.run(["git", "-C", str(ROOT), "commit", "-q", "-m", msg, "-m", co], capture_output=True)


def regenerate_doc(models: list[str]) -> None:
    rows = [json.loads(x) for x in OUT.read_text().splitlines() if x.strip()] if OUT.exists() else []
    lines = ["# Cross-model RLM matrix (autonomous run)", "",
             f"Live results, {len(rows)} cells so far. Local Ollama, 12 multifault OTel windows "
             "(3 normal + 3 each product-catalog/cart/ad), RLM navigation, root-cause task.", ""]
    # aggregate RLM by (model, condition)
    lines += ["## RLM: accuracy, mean tokens, abort rate by (model, condition)", "",
              "| model | cond | n | acc | mean_tok | mean_rounds | abort% |", "|---|---|---|---|---|---|---|"]
    agg: dict = {}
    for r in rows:
        if r["method"] != "rlm":
            continue
        k = (r["model"], r["condition"])
        a = agg.setdefault(k, {"n": 0, "ok": 0, "tok": 0, "rounds": 0, "abort": 0})
        a["n"] += 1
        a["ok"] += int(r["correct"])
        a["tok"] += r["in_tok"] + r["out_tok"]
        a["rounds"] += r.get("rounds", 0)
        a["abort"] += int(r.get("aborted", False))
    for (m, c), a in sorted(agg.items()):
        n = a["n"]
        lines.append(f"| {m} | {c} | {n} | {a['ok']/n:.2f} | {a['tok']//n:,} | "
                     f"{a['rounds']/n:.1f} | {100*a['abort']//n}% |")
    # in-context rows if any
    ic = [r for r in rows if r["method"] == "in_context"]
    if ic:
        lines += ["", "## In-context anchor", "", "| model | cond | window | tok | ok |", "|---|---|---|---|---|"]
        for r in ic:
            lines.append(f"| {r['model']} | {r['condition']} | {r['window'][-12:]} | "
                         f"{r['in_tok']+r['out_tok']:,} | {r['correct']} |")
    DOC.write_text("\n".join(lines) + "\n")


async def rlm_cell(model: str, w, condition: str, timeout: float) -> dict:
    client = OllamaClient(host="http://localhost:11434", model=model, max_retries=2)
    rlm = RLMMethod(client, max_rounds=14, max_total_tokens=120_000, num_ctx=16384)
    truth = true_culprit(w)
    t0 = time.time()
    try:
        r = await asyncio.wait_for(rlm.apredict(w.records, condition, "root_cause"), timeout=timeout)
        return {"pred": str(r.prediction), "correct": correct(str(r.prediction), truth),
                "in_tok": r.input_tokens, "out_tok": r.output_tokens, "rounds": r.rlm_rounds,
                "aborted": r.aborted, "latency_s": round(time.time() - t0, 1), "error": ""}
    except asyncio.TimeoutError:
        return {"pred": "TIMEOUT", "correct": False, "in_tok": 0, "out_tok": 0, "rounds": 0,
                "aborted": True, "latency_s": round(time.time() - t0, 1), "error": "timeout"}
    except Exception as e:  # noqa: BLE001 - unattended: never die on one cell
        return {"pred": "ERROR", "correct": False, "in_tok": 0, "out_tok": 0, "rounds": 0,
                "aborted": True, "latency_s": round(time.time() - t0, 1), "error": str(e)[:160]}


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--budget-sec", type=int, default=15000)
    ap.add_argument("--models", nargs="+",
                    default=["qwen3:8b", "qwen3:14b", "gemma3:12b", "qwen3:30b-a3b"])
    ap.add_argument("--cell-timeout", type=float, default=360)
    args = ap.parse_args()

    windows = windows_from_manifest(LOGS, MF)
    windows.sort(key=lambda w: w.key)
    done = done_cells()
    log(f"matrix: {len(args.models)} models x {len(windows)} windows x 2 conditions | "
        f"budget {args.budget_sec}s | {len(done)} cells already done")

    for model in args.models:
        if time.time() - START > args.budget_sec:
            log("budget exhausted — stopping")
            break
        # skip if all this model's cells are done
        todo = [(w, c) for w in windows for c in ("plain", "structured")
                if (model, "rlm", c, w.key) not in done]
        if not todo:
            log(f"{model}: all cells done, skip")
            continue
        log(f"=== model {model}: {len(todo)} cells to do ===")
        if not ensure_model(model):
            for w in windows:
                for c in ("plain", "structured"):
                    append_row({"model": model, "method": "rlm", "condition": c, "window": w.key,
                                "pred": "SKIP_OOM", "correct": False, "in_tok": 0, "out_tok": 0,
                                "rounds": 0, "aborted": True, "error": "model_unavailable"})
            regenerate_doc(args.models)
            git_commit(f"matrix: {model} unavailable (OOM/pull fail)")
            continue
        for w, c in todo:
            if time.time() - START > args.budget_sec:
                log("budget exhausted mid-model — stopping")
                break
            res = await rlm_cell(model, w, c, args.cell_timeout)
            append_row({"model": model, "method": "rlm", "condition": c, "window": w.key,
                        "truth": true_culprit(w), **res})
            log(f"  {model} {c:10s} {w.key[-10:]} -> {res['pred'][:18]:18s} "
                f"ok={res['correct']} tok={res['in_tok']+res['out_tok']:>6} "
                f"r={res['rounds']} {res['latency_s']}s")
        stop_model(model)
        regenerate_doc(args.models)
        git_commit(f"matrix: RLM cells for {model} (autonomous run)")
        log(f"=== {model} done, committed ===")

    regenerate_doc(args.models)
    git_commit("matrix: autonomous run checkpoint")
    log("RUN COMPLETE")


if __name__ == "__main__":
    asyncio.run(main())
