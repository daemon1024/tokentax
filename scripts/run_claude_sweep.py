"""In-context sweep on Claude Sonnet (subscription, via claude -p): plain vs structured (otel vs raw).

Reads the OTel fault window, chunks it under Sonnet's context, asks for the culprit service per chunk,
aggregates. Reports tokens (incl. constant ~30k harness overhead — cancels in the plain-vs-structured
ratio per the stakeholder), accuracy, and the envelope tax. Key question: does Sonnet find the fault
in the verbose STRUCTURED window that qwen3:8b missed?
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from tokentax.methods.claude_cli import claude_call  # noqa: E402
from tokentax.methods.llm_incontext import _chunk_records, _parse_json  # noqa: E402
from tokentax.otel_loader import windows_from_manifest  # noqa: E402

LOGS = ROOT / "data/otel_demo/logs.jsonl"
ORIGIN = {"productCatalogFailure": "product-catalog", "cartFailure": "cart", "adFailure": "ad"}
SYSTEM = ("You are an SRE. The text below is one chunk of logs from a fixed time window of a "
          "microservice system. AT MOST one service is failing. Name the single culprit service "
          "(emitting the failure) exactly as in the logs, or 'none' if nothing is failing here. "
          'Respond with ONLY JSON: {"culprit_service": "<name or none>"}.')


def true_culprit(w) -> str:
    return ORIGIN.get(w.fault or "", "none") if w.label == "anomalous" else "none"


def correct(pred: str, truth: str) -> bool:
    # normalize away naming-format differences (e.g. 'productcatalogservice' vs 'product-catalog')
    norm = lambda s: re.sub(r"[^a-z0-9]", "", str(s).lower())  # noqa: E731
    p, t = norm(pred), norm(truth)
    if truth == "none":
        return p in ("none", "", "unknown") or p.startswith("no")
    return t in p or (p in t and len(p) > 3)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", default=str(ROOT / "data/otel_demo/manifest_sweep1.json"))
    ap.add_argument("--model", default="sonnet")
    ap.add_argument("--chunk-tokens", type=int, default=140_000)
    args = ap.parse_args()
    windows = windows_from_manifest(LOGS, args.manifest)

    print(f"model={args.model} (via claude -p subscription)  windows={len(windows)}\n")
    print(f"{'cond':11s} {'window':22s} {'chunks':>6s} {'in_tok':>9s} {'out':>5s} "
          f"{'cost$':>6s} {'pred':16s} {'true':16s} {'ok':>3s}")
    results = {}
    for w in windows:
        truth = true_culprit(w)
        for cond in ("plain", "structured"):
            chunks = _chunk_records(w.records, cond, args.chunk_tokens)
            in_tok = out_tok = 0
            cost = 0.0
            votes = []
            for ch in chunks:
                r = claude_call(f"{SYSTEM}\n\n--- LOGS ---\n{ch}", model=args.model)
                in_tok += r.input_tokens
                out_tok += r.output_tokens
                cost += r.cost_usd
                v = str(_parse_json(r.content).get("culprit_service", "")).strip().lower()
                if v and v not in ("none", "unknown"):
                    votes.append(v)
            pred = max(set(votes), key=votes.count) if votes else "none"
            ok = correct(pred, truth)
            results[(w.key, cond)] = {"in": in_tok, "out": out_tok, "cost": cost,
                                      "chunks": len(chunks), "pred": pred, "ok": ok}
            print(f"{cond:11s} {w.key[:22]:22s} {len(chunks):6d} {in_tok:9,d} {out_tok:5d} "
                  f"{cost:6.2f} {pred[:16]:16s} {truth:16s} {'Y' if ok else '·':>3s}", flush=True)

    print("\n=== headline (in-context, Sonnet) ===")
    for w in windows:
        p = results.get((w.key, "plain"))
        s = results.get((w.key, "structured"))
        if p and s:
            tax = (s["in"] + s["out"]) / max(1, p["in"] + p["out"])
            print(f"  {w.key[:28]:28s} envelope tax (structured/plain tokens) = {tax:.2f}x "
                  f"| plain ok={p['ok']} structured ok={s['ok']}")
    total = sum(v["in"] + v["out"] for v in results.values())
    cost = sum(v["cost"] for v in results.values())
    print(f"\n  TOTAL: {total:,} tokens, ${cost:.2f} (incl. constant ~30k/call harness overhead)")
    (ROOT / "results/runs/claude_sweep.json").write_text(json.dumps(
        {f"{k[0]}|{k[1]}": v for k, v in results.items()}, indent=2))
    print("  wrote results/runs/claude_sweep.json")


if __name__ == "__main__":
    main()
