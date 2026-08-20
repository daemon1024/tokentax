"""In-context (read-the-whole-window) baseline — the thing RLM is supposed to beat.

The 288-cell matrix in `run_cloud_matrix.py` holds the METHOD fixed at RLM and varies only the
CONDITION (plain / structured_no_trace / structured). So it answers "does structure make navigation
cheaper?" (answer: no) but never answers "is navigation cheaper than reading?" — which is the
original thesis and the one comparison with a large expected effect.

These windows are ~1.09M plain / ~1.63M structured tokens (cl100k proxy), so in-context must chunk;
`InContextMethod` splits at 110k and majority-votes across chunks. Its input token count is therefore
bounded below by the window size no matter how well it does — which is why the cost side of this
comparison is near-deterministic and the interesting unknown is ACCURACY.

Bounded on purpose: 4 windows (one per truth class) x 2 models x plain. Reading 12 windows on 8
models would be ~100M input tokens for a ratio that is already visible at n=8. The cap is stated
here and in the output rather than left implicit.

    .venv/bin/python scripts/run_incontext_baseline.py
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

from tokentax.methods.anthropic_client import AnthropicClient  # noqa: E402
from tokentax.methods.llm_incontext import InContextMethod  # noqa: E402
from tokentax.methods.ollama_client import OllamaClient  # noqa: E402
from tokentax.otel_loader import windows_from_manifest  # noqa: E402

LOGS = ROOT / "data/otel_demo/logs.jsonl"
MF = ROOT / "data/otel_demo/manifest_multifault.json"
OUT = ROOT / "results/runs/incontext_baseline.jsonl"

ORIGIN = {"productCatalogFailure": "product-catalog", "cartFailure": "cart", "adFailure": "ad"}

# fixed before the first cell
CELL_TIMEOUT_S = 900.0
MAX_INPUT_TOKENS = 110_000
NUM_CTX = 131_072
CONCURRENCY = 3
DEFAULT_MODELS = ["gpt-oss:120b", "qwen3.5:397b"]

START = time.time()


def log(m):
    print(f"[{time.time() - START:7.0f}s] {m}", flush=True)


def truth_of(w) -> str:
    return ORIGIN.get(w.fault or "", "none") if w.label == "anomalous" else "none"


def correct(pred: str, truth: str) -> bool:
    n = re.sub(r"[^a-z0-9]", "", str(pred).lower())
    if truth == "none":
        return n in ("none", "", "unknown") or n.startswith("no")
    t = re.sub(r"[^a-z0-9]", "", truth)
    return t in n or (truth == "product-catalog" and "catalog" in n)


def make_client(model: str, timeout: float):
    if model.startswith("claude-"):
        return AnthropicClient(model=model, timeout=timeout, max_retries=2)
    return OllamaClient(model=model, timeout=timeout, max_retries=2)


def done_keys() -> set:
    if not OUT.exists():
        return set()
    return {(r["model"], r["condition"], r["window"])
            for r in (json.loads(x) for x in OUT.read_text().splitlines() if x.strip())}


async def run_cell(sem, model, cond, w, truth):
    async with sem:
        client = make_client(model, CELL_TIMEOUT_S)
        method = InContextMethod(client, max_input_tokens=MAX_INPUT_TOKENS, num_ctx=NUM_CTX)
        t0 = time.perf_counter()
        err, res = "", None
        try:
            res = await asyncio.wait_for(
                method.apredict(w.records, cond, "root_cause"), timeout=CELL_TIMEOUT_S)
        except TimeoutError:
            err = "timeout"
        except Exception as e:  # noqa: BLE001
            err = f"{type(e).__name__}: {e}"[:200]
        row = {
            "model": model, "condition": cond, "window": w.key, "truth": truth,
            "method": "in_context",
            "pred": (str(res.prediction) if res else ""),
            "correct": bool(res and correct(str(res.prediction), truth)),
            "in_tok": (res.input_tokens if res else 0),
            "out_tok": (res.output_tokens if res else 0),
            "total_tok": (res.total_tokens if res else 0),
            "chunks": (res.rlm_rounds if res else 0),
            "records": len(w.records),
            "latency_s": round(time.perf_counter() - t0, 1),
            "error": err,
            "cfg": {"max_input_tokens": MAX_INPUT_TOKENS, "num_ctx": NUM_CTX,
                    "timeout": CELL_TIMEOUT_S},
        }
        with OUT.open("a") as f:
            f.write(json.dumps(row) + "\n")
        flag = "ok " if row["correct"] else ("ERR" if err else "MISS")
        log(f"  {flag} {model:16s} {cond:10s} {truth:16s} -> {row['pred'][:20]:20s} "
            f"tok={row['total_tok']:<10,} chunks={row['chunks']} {row['latency_s']}s {err}")
        return row


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", default=",".join(DEFAULT_MODELS))
    ap.add_argument("--conditions", default="plain")
    ap.add_argument("--windows", type=int, default=4, help="one per truth class")
    args = ap.parse_args()

    models = [m.strip() for m in args.models.split(",") if m.strip()]
    conds = [c.strip() for c in args.conditions.split(",") if c.strip()]
    if any(not m.startswith("claude-") for m in models) and not os.environ.get("OLLAMA_API_KEY"):
        sys.exit("OLLAMA_API_KEY not set (environment only).")
    os.environ.setdefault("OLLAMA_HOST", "https://ollama.com")

    all_w = list(windows_from_manifest(str(LOGS), str(MF)))
    seen, windows = set(), []
    for w in all_w:  # one window per truth class
        t = truth_of(w)
        if t not in seen:
            seen.add(t)
            windows.append(w)
    windows = windows[:args.windows]

    OUT.parent.mkdir(parents=True, exist_ok=True)
    have = done_keys()
    sem = asyncio.Semaphore(CONCURRENCY)
    tasks = [run_cell(sem, m, c, w, truth_of(w))
             for m in models for c in conds for w in windows
             if (m, c, w.key) not in have]
    log(f"BOUNDED RUN: {len(models)} models x {len(conds)} conditions x {len(windows)} windows "
        f"= {len(tasks)} cells ({len(have)} already done). Windows not covered: "
        f"{len(all_w) - len(windows)} of {len(all_w)}.")
    await asyncio.gather(*tasks)
    log("done")


if __name__ == "__main__":
    asyncio.run(main())
