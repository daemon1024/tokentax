"""Head-to-head on ONE real fault window: in-context vs RLM, plain vs structured.

The thesis test in miniature (root-cause). Cost-bounded to 1 window (4 cells). Prints tokens,
rounds, prediction, correctness — and the RLM-vs-in-context token ratio per condition.
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
from tokentax.methods.rlm import RLMMethod  # noqa: E402
from tokentax.nezha import build_root_cause_examples, format_window  # noqa: E402

RAW = ROOT / "data/raw/Nezha/rca_data"
ENC = tiktoken.get_encoding("cl100k_base")


def _match(pred: str, culprit: str) -> bool:
    p, c = pred.strip().lower(), culprit.strip().lower()
    return bool(p) and (c in p or p in c)


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rank", type=int, default=0, help="which window by size rank (0=smallest)")
    args = ap.parse_args()

    by_window = {}
    for e in build_root_cause_examples(RAW):
        if e.log_visible:
            by_window.setdefault(e.window_key, e)
    ranked = sorted(by_window.values(),
                    key=lambda e: len(ENC.encode(format_window(e.records, "plain"), disallowed_special=())))
    e = ranked[args.rank]

    client = OllamaClient()
    incontext = InContextMethod(client)
    rlm = RLMMethod(client)
    print(f"model={client.model}  window={e.window_key}  TRUE culprit={e.culprit_service}  "
          f"records={len(e.records)}\n")
    print(f"{'method':12s} {'condition':12s} {'in_tok':>8s} {'out':>5s} {'rounds':>6s} "
          f"{'pred':24s} {'ok':>3s}")
    cells = {}
    for cond in ("plain", "structured"):
        ic = await incontext.apredict(e.records, cond, "root_cause")
        cells[("in_context", cond)] = ic
        print(f"{'in_context':12s} {cond:12s} {ic.input_tokens:8d} {ic.output_tokens:5d} "
              f"{ic.rlm_rounds:6d} {str(ic.prediction)[:24]:24s} "
              f"{'Y' if _match(str(ic.prediction), e.culprit_service) else '·':>3s}")
    for cond in ("plain", "structured"):
        rr = await rlm.apredict(e.records, cond, "root_cause")
        cells[("rlm", cond)] = rr
        tag = f"{rr.rlm_rounds}{'*abort' if rr.aborted else ''}"
        print(f"{'rlm':12s} {cond:12s} {rr.input_tokens:8d} {rr.output_tokens:5d} "
              f"{tag:>6s} {str(rr.prediction)[:24]:24s} "
              f"{'Y' if _match(str(rr.prediction), e.culprit_service) else '·':>3s}")

    print("\n--- token cost (input+output) ---")
    for cond in ("plain", "structured"):
        ic = cells[("in_context", cond)].total_tokens
        rl = cells[("rlm", cond)].total_tokens
        print(f"  {cond:12s} in_context={ic:>8,}  rlm={rl:>8,}  "
              f"rlm/in_context={rl/max(1,ic):.2f}x")
    print("NOTE: single window, cost-bounded smoke — directional, not a benchmark result.")


if __name__ == "__main__":
    asyncio.run(main())
