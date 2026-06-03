"""Cost-bounded live smoke of the in-context method on real Nezha fault windows.

Runs root-cause localization on the N smallest log-visible windows, plain vs structured, to get
the first real LLM token numbers + the envelope tax on real data with a real model. Deliberately
small (a few cloud calls) — NOT the full matrix.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

import tiktoken

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from tokentax.methods.llm_incontext import InContextMethod  # noqa: E402
from tokentax.methods.ollama_client import OllamaClient  # noqa: E402
from tokentax.nezha import build_root_cause_examples, format_window  # noqa: E402

RAW = ROOT / "data/raw/Nezha/rca_data"
ENC = tiktoken.get_encoding("cl100k_base")


def _match(pred: str, culprit_service: str) -> bool:
    p = pred.strip().lower()
    c = culprit_service.strip().lower()
    return c in p or p in c or c.split("-")[1:] and "-".join(c.split("-")[1:]) in p


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=2, help="number of smallest log-visible windows")
    args = ap.parse_args()

    examples = [e for e in build_root_cause_examples(RAW) if e.log_visible]
    # one per window, smallest first by plain token size
    by_window = {}
    for e in examples:
        by_window.setdefault(e.window_key, e)
    ranked = sorted(by_window.values(), key=lambda e: len(ENC.encode(
        format_window(e.records, "plain"), disallowed_special=())))
    picks = ranked[: args.n]

    client = OllamaClient()
    method = InContextMethod(client)
    print(f"model={client.model} cloud={client.is_cloud}")
    print(f"{'window':16s} {'culprit':26s} {'cond':18s} {'in_tok':>8s} {'out':>5s} "
          f"{'lat_ms':>7s} {'pred':26s} {'ok':>3s}")
    rows = []
    for e in picks:
        for cond in ("plain", "structured"):
            r = await method.apredict(e.records, cond, "root_cause")
            ok = _match(str(r.prediction), e.culprit_service)
            rows.append((e.window_key, cond, r.input_tokens, r.output_tokens, ok))
            print(f"{e.window_key:16s} {e.culprit_service:26s} {cond:18s} {r.input_tokens:8d} "
                  f"{r.output_tokens:5d} {r.latency_ms:7.0f} {str(r.prediction)[:26]:26s} "
                  f"{'Y' if ok else '·':>3s}")

    # envelope tax: structured input tokens / plain input tokens
    plain = [t for _, c, t, _, _ in rows if c == "plain"]
    struct = [t for _, c, t, _, _ in rows if c == "structured"]
    if plain and struct:
        tax = sum(struct) / max(1, sum(plain))
        print(f"\nenvelope tax (structured/plain input tokens): {tax:.2f}x")
    acc = sum(1 for *_, ok in rows if ok) / len(rows)
    print(f"root-cause correct: {sum(1 for *_, ok in rows if ok)}/{len(rows)} ({acc:.0%})")
    print("NOTE: tiny sample, cost-bounded smoke — not a benchmark result.")


if __name__ == "__main__":
    asyncio.run(main())
