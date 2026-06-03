"""LLM sweep on the recoverable OTel dataset: in-context vs RLM, plain vs structured.

Task: root-cause (name the culprit service, or 'none'). Recoverable now (the origin logs its fault),
so accuracy should be high; the headline is TOKEN COST. Cost-bounded to the windows in manifest.json.
Reports per-cell tokens + correctness, the RLM/in-context ratio, and the envelope tax. Reports spend.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from tokentax.methods.llm_incontext import InContextMethod  # noqa: E402
from tokentax.methods.ollama_client import OllamaClient  # noqa: E402
from tokentax.methods.rlm import RLMMethod  # noqa: E402
from tokentax.otel_loader import windows_from_manifest  # noqa: E402

LOGS = ROOT / "data/otel_demo/logs.jsonl"
ORIGIN = {"productCatalogFailure": "product-catalog", "cartFailure": "cart", "adFailure": "ad"}


def true_culprit(w) -> str:
    return ORIGIN.get(w.fault or "", "none") if w.label == "anomalous" else "none"


def correct(pred: str, truth: str) -> bool:
    p = str(pred).strip().lower()
    if truth == "none":
        return p in ("none", "", "unknown") or p.startswith("no")
    return truth in p or p in truth


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", default=str(ROOT / "data/otel_demo/manifest.json"))
    args = ap.parse_args()
    windows = windows_from_manifest(LOGS, args.manifest)

    client = OllamaClient()
    methods = {"in_context": InContextMethod(client), "rlm": RLMMethod(client)}
    conditions = ["plain", "structured"]
    print(f"model={client.model}  windows={len(windows)}\n")
    print(f"{'method':11s} {'cond':11s} {'window':22s} {'in_tok':>8s} {'out':>5s} {'rounds':>6s} "
          f"{'pred':16s} {'true':16s} {'ok':>3s}")
    cells: dict = {}
    spend = 0
    for w in windows:
        truth = true_culprit(w)
        for mname, method in methods.items():
            for cond in conditions:
                if mname == "in_context":
                    r = await method.apredict(w.records, cond, "root_cause")
                else:
                    r = await method.apredict(w.records, cond, "root_cause")
                ok = correct(str(r.prediction), truth)
                spend += r.input_tokens + r.output_tokens
                cells.setdefault((mname, cond), []).append(
                    {"tokens": r.total_tokens, "in": r.input_tokens, "out": r.output_tokens,
                     "rounds": r.rlm_rounds, "ok": ok})
                print(f"{mname:11s} {cond:11s} {w.key[:22]:22s} {r.input_tokens:8d} "
                      f"{r.output_tokens:5d} {r.rlm_rounds:6d} {str(r.prediction)[:16]:16s} "
                      f"{truth:16s} {'Y' if ok else '·':>3s}", flush=True)
                await asyncio.sleep(4)  # space out big calls to respect cloud rate limits

    print("\n=== per-cell summary (mean tokens, accuracy) ===")
    summ = {}
    for (m, c), rs in cells.items():
        mean_tok = sum(x["tokens"] for x in rs) / len(rs)
        acc = sum(x["ok"] for x in rs) / len(rs)
        summ[f"{m}/{c}"] = {"mean_tokens": round(mean_tok), "accuracy": round(acc, 3), "n": len(rs)}
        print(f"  {m:11s} {c:11s} mean_tokens={mean_tok:9,.0f} acc={acc:.2f} (n={len(rs)})")

    print("\n=== headline ===")
    for c in conditions:
        ic = summ.get(f"in_context/{c}", {}).get("mean_tokens", 0)
        rl = summ.get(f"rlm/{c}", {}).get("mean_tokens", 1)
        print(f"  {c:11s}: RLM uses {rl / max(1, ic):.3f}x in-context tokens "
              f"({ic:,.0f} -> {rl:,.0f})")
    ic_p = summ.get("in_context/plain", {}).get("mean_tokens", 1)
    ic_s = summ.get("in_context/structured", {}).get("mean_tokens", 1)
    print(f"  in-context envelope tax (structured/plain): {ic_s / max(1, ic_p):.2f}x")
    print(f"\n  TOTAL SPEND this sweep: {spend:,} tokens")
    (ROOT / "results/runs/otel_sweep.json").write_text(json.dumps(
        {"summary": summ, "total_tokens_spent": spend, "n_windows": len(windows)}, indent=2))
    print("  wrote results/runs/otel_sweep.json")


if __name__ == "__main__":
    asyncio.run(main())
