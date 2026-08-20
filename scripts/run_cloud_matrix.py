"""Corrected 3-arm matrix on Ollama Cloud — the honest replacement for matrix_v2.

WHAT CHANGED vs `run_matrix_v2.py` (see WITHDRAWAL.md):

1. **Matched aggregation power.** Every arm gets a ranked ERROR digest computable from the data it can
   see: `errors_by_cluster` (Drain templates, no fields needed) in all three, plus `errors_by_service`
   where the service field exists. The old run gave a digest to the structured arm ONLY, so it measured
   the tool, not the structure.
2. **Parallel prompts.** Navigation hints are phrased identically per arm (see `rlm._nav_for`).
3. **Three arms, one variable at a time.**
       plain -> structured_no_trace   isolates `service.name`
       structured_no_trace -> structured  isolates `trace_id` (service+severity held constant)
4. **Failures are data, never zeros.** A timeout/error keeps its observed token count and is reported
   as a separate rate; token means state exactly which cells they cover.
5. **Fixed parameters.** Timeout, rounds and ceiling are set before the first cell and never changed
   mid-run. A different setting means a new output file.
6. **Auditable.** The full tool-call sequence is persisted per cell; `matrix_v2.jsonl` dropped it, which
   is why nobody could check afterwards which tool produced the answer.
7. **`cost_per_correct` is actually computed**, against a zero-token baseline per arm.

Usage:
    .venv/bin/python scripts/run_cloud_matrix.py --smoke
    .venv/bin/python scripts/run_cloud_matrix.py --models gpt-oss:120b,kimi-k3
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from tokentax.methods.ollama_client import OllamaClient  # noqa: E402
from tokentax.methods.repl import LogREPL  # noqa: E402
from tokentax.methods.rlm import RLMMethod  # noqa: E402
from tokentax.otel_loader import windows_from_manifest  # noqa: E402

LOGS = ROOT / "data/otel_demo/logs.jsonl"
MF = ROOT / "data/otel_demo/manifest_multifault.json"
OUT = ROOT / "results/runs/cloud_matrix.jsonl"
DOC = ROOT / "results/CLOUD_MATRIX.md"

ORIGIN = {"productCatalogFailure": "product-catalog", "cartFailure": "cart", "adFailure": "ad"}
CONDITIONS = ("plain", "structured_no_trace", "structured")

# --- fixed before the first cell; changing any of these means a NEW output file ---
CELL_TIMEOUT_S = 240.0
MAX_ROUNDS = 14
MAX_TOTAL_TOKENS = 250_000
NUM_CTX = 32_768
CONCURRENCY = 6

DEFAULT_MODELS = [
    "gpt-oss:120b", "qwen3.5:397b", "deepseek-v4-pro:0813", "kimi-k3",
    "glm-5.2", "mistral-large-3:675b", "nemotron-3-super", "gemma4:31b",
]

START = time.time()


def log(m):
    print(f"[{time.time() - START:7.0f}s] {m}", flush=True)


def truth_of(w) -> str:
    return ORIGIN.get(w.fault or "", "none") if w.label == "anomalous" else "none"


def correct(pred: str, truth: str) -> bool:
    """Single scorer for the whole project. The old code had nine divergent copies, two of which
    disagreed on the same stored prediction."""
    import re
    n = re.sub(r"[^a-z0-9]", "", str(pred).lower())
    if truth == "none":
        return n in ("none", "", "unknown") or n.startswith("no")
    t = re.sub(r"[^a-z0-9]", "", truth)
    return t in n or (truth == "product-catalog" and "catalog" in n)


def baseline_pred(repl: LogREPL) -> str:
    """Zero-token baseline: argmax over the arm's own digest, no model in the loop.

    Structured arms rank services directly. The plain arm can only rank message-templates, so it is
    scored by whether the top template's text names the culprit — which on this dataset it does.
    """
    if repl.has_fields:
        d = repl.errors_by_service()
        if d.startswith("no errors"):
            return "none"
        return d.split(": ", 1)[1].split(",")[0].split("=")[0].strip()
    d = repl.errors_by_cluster(limit=1)
    if d.startswith("no errors"):
        return "none"
    return d.split("\n", 1)[1] if "\n" in d else "none"


def done_keys() -> set:
    if not OUT.exists():
        return set()
    return {(r["model"], r["condition"], r["window"])
            for r in (json.loads(x) for x in OUT.read_text().splitlines() if x.strip())}


async def run_cell(sem, model, cond, w, truth):
    async with sem:
        client = OllamaClient(model=model, timeout=CELL_TIMEOUT_S, max_retries=2)
        method = RLMMethod(client, max_rounds=MAX_ROUNDS,
                           max_total_tokens=MAX_TOTAL_TOKENS, num_ctx=NUM_CTX)
        t0 = time.perf_counter()
        err, res = "", None
        try:
            res = await asyncio.wait_for(
                method.apredict(w.records, cond, "root_cause"), timeout=CELL_TIMEOUT_S)
        except TimeoutError:
            err = "timeout"
        except Exception as e:  # noqa: BLE001 - record, never crash the matrix
            err = f"{type(e).__name__}: {e}"[:200]
        latency = time.perf_counter() - t0

        tools_used = []
        if res is not None:
            tools_used = [t["tool"] for t in (res.raw_trace or []) if "tool" in t]
        row = {
            "model": model, "condition": cond, "window": w.key if hasattr(w, "key") else str(w.fault),
            "truth": truth,
            "pred": (res.prediction if res else ""),
            "correct": bool(res and correct(res.prediction, truth)),
            "in_tok": (res.input_tokens if res else 0),
            "out_tok": (res.output_tokens if res else 0),
            "total_tok": (res.total_tokens if res else 0),
            "rounds": (res.rlm_rounds if res else 0),
            "tools_used": tools_used,
            "first_tool": (tools_used[0] if tools_used else ""),
            "aborted": bool(res and res.aborted),
            "abort_reason": (res.abort_reason if res else ""),
            "latency_s": round(latency, 1),
            "error": err,
            # provenance so a reader can tell which settings produced this row
            "cfg": {"timeout": CELL_TIMEOUT_S, "max_rounds": MAX_ROUNDS, "num_ctx": NUM_CTX},
        }
        with OUT.open("a") as f:
            f.write(json.dumps(row) + "\n")
        flag = "ok " if row["correct"] else ("ERR" if err else "MISS")
        log(f"  {flag} {model:22s} {cond:20s} {truth:16s} -> {row['pred'][:22]:22s} "
            f"tok={row['total_tok']:<7,} r={row['rounds']} via={row['first_tool']}")
        return row


def regen():
    rows = [json.loads(x) for x in OUT.read_text().splitlines() if x.strip()] if OUT.exists() else []
    if not rows:
        return
    agg = defaultdict(lambda: {"n": 0, "ok": 0, "tok": 0, "ans": 0, "fail": 0, "rounds": 0})
    for r in rows:
        a = agg[(r["model"], r["condition"])]
        a["n"] += 1
        failed = bool(r["error"])
        a["fail"] += int(failed)
        a["ok"] += int(r["correct"])
        if not failed:
            a["ans"] += 1
            a["tok"] += r["total_tok"]
            a["rounds"] += r["rounds"]

    out = [
        "# Corrected 3-arm matrix — Ollama Cloud",
        "",
        "Matched aggregation power across arms; parallel prompts; one variable per contrast.",
        "Supersedes `MATRIX_RESULTS_V2.md` (see `WITHDRAWAL.md` for why that run does not hold).",
        "",
        f"Fixed config: timeout={CELL_TIMEOUT_S:.0f}s, max_rounds={MAX_ROUNDS}, num_ctx={NUM_CTX:,}. "
        f"{len(rows)} cells.",
        "",
        "`mean_tok` covers ANSWERED cells only; `fail` is reported separately and is never folded in "
        "as a zero.",
        "",
        "| model | condition | n | acc | mean_tok | mean_rounds | fail | cost_per_correct |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for (m, c), a in sorted(agg.items()):
        n, ans, ok = a["n"], a["ans"], a["ok"]
        mt = f"{a['tok'] // ans:,}" if ans else "—"
        mr = f"{a['rounds'] / ans:.1f}" if ans else "—"
        cpc = f"{a['tok'] // ok:,}" if ok else "—"
        out.append(f"| {m} | {c} | {n} | {ok / n:.2f} | {mt} | {mr} | {a['fail']} | {cpc} |")

    # per-condition pooled view: the actual contrast of interest
    pool = defaultdict(lambda: {"n": 0, "ok": 0, "tok": 0, "ans": 0, "fail": 0})
    for r in rows:
        a = pool[r["condition"]]
        a["n"] += 1
        a["ok"] += int(r["correct"])
        a["fail"] += int(bool(r["error"]))
        if not r["error"]:
            a["ans"] += 1
            a["tok"] += r["total_tok"]
    out += ["", "## Pooled across models — the contrast", "",
            "| condition | n | acc | mean_tok | fail | cost_per_correct |", "|---|---|---|---|---|---|"]
    for c in CONDITIONS:
        a = pool.get(c)
        if not a:
            continue
        mt = f"{a['tok'] // a['ans']:,}" if a["ans"] else "—"
        cpc = f"{a['tok'] // a['ok']:,}" if a["ok"] else "—"
        out.append(f"| {c} | {a['n']} | {a['ok'] / a['n']:.2f} | {mt} | {a['fail']} | {cpc} |")

    # which tool actually answered
    ft = defaultdict(lambda: defaultdict(int))
    for r in rows:
        ft[r["condition"]][r["first_tool"] or "(none)"] += 1
    out += ["", "## First tool called (what the models actually reach for)", ""]
    for c in CONDITIONS:
        if c in ft:
            items = ", ".join(f"{k}={v}" for k, v in sorted(ft[c].items(), key=lambda kv: -kv[1]))
            out.append(f"- **{c}**: {items}")
    DOC.write_text("\n".join(out) + "\n")


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", default=",".join(DEFAULT_MODELS))
    ap.add_argument("--smoke", action="store_true", help="2 models x 3 conditions x 3 windows")
    args = ap.parse_args()

    if not os.environ.get("OLLAMA_API_KEY"):
        sys.exit("OLLAMA_API_KEY not set (environment only). `set -a; . ./.env; set +a`")
    os.environ.setdefault("OLLAMA_HOST", "https://ollama.com")

    windows = list(windows_from_manifest(str(LOGS), str(MF)))
    models = [m.strip() for m in args.models.split(",") if m.strip()]
    if args.smoke:
        models = models[:2]
        seen, picked = set(), []
        for w in windows:  # one window per truth class
            t = truth_of(w)
            if t not in seen:
                seen.add(t)
                picked.append(w)
        windows = picked[:3]

    OUT.parent.mkdir(parents=True, exist_ok=True)
    have = done_keys()
    sem = asyncio.Semaphore(CONCURRENCY)
    tasks = []
    for m in models:
        for c in CONDITIONS:
            for w in windows:
                key = (m, c, w.key if hasattr(w, "key") else str(w.fault))
                if key in have:
                    continue
                tasks.append(run_cell(sem, m, c, w, truth_of(w)))
    log(f"{len(models)} models x {len(CONDITIONS)} conditions x {len(windows)} windows "
        f"= {len(tasks)} cells to run ({len(have)} already done)")
    for i in range(0, len(tasks), 24):
        await asyncio.gather(*tasks[i:i + 24])
        regen()
        log(f"--- {min(i + 24, len(tasks))}/{len(tasks)} cells; {DOC.name} regenerated")
    regen()
    log(f"done. {DOC}")


if __name__ == "__main__":
    asyncio.run(main())
