"""Compare three methods on one window: in-context (read-all) vs grep-navigator vs recursive RLM.

Shows what the paper's recursion actually adds. Recursive RLM reports root vs sub token split and the
MAX single root-prompt — the root never holds the whole window even though sub-LMs read all of it.
Local Ollama; window capped to keep it tractable.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import tiktoken  # noqa: E402

from tokentax.methods.llm_incontext import InContextMethod  # noqa: E402
from tokentax.methods.ollama_client import OllamaClient  # noqa: E402
from tokentax.methods.rlm import RLMMethod  # noqa: E402
from tokentax.methods.rlm_recursive import RecursiveRLM  # noqa: E402
from tokentax.nezha import format_window  # noqa: E402
from tokentax.otel_loader import windows_from_manifest  # noqa: E402

LOGS = ROOT / "data/otel_demo/logs.jsonl"
ENC = tiktoken.get_encoding("cl100k_base")
TRUTH = "product-catalog"


def ok(pred: str) -> bool:
    import re
    n = lambda s: re.sub(r"[^a-z0-9]", "", str(s).lower())  # noqa: E731
    return TRUTH.replace("-", "") in n(pred)


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", default=str(ROOT / "data/otel_demo/manifest_sweep1.json"))
    ap.add_argument("--max-records", type=int, default=500)
    ap.add_argument("--model", default="qwen3:8b")
    ap.add_argument("--chunk-lines", type=int, default=100)
    args = ap.parse_args()

    w = windows_from_manifest(LOGS, args.manifest)[0]
    recs = w.records[: args.max_records]
    pc_err = sum(1 for r in recs if r.is_error and r.pod == "product-catalog")
    wtok = len(ENC.encode(format_window(recs, "plain"), disallowed_special=()))
    print(f"model={args.model} window={w.key} records={len(recs)} (~{wtok:,} plain tok) "
          f"product-catalog errors in slice={pc_err}\n")

    client = OllamaClient(host="http://localhost:11434", model=args.model, max_retries=2)
    inc = InContextMethod(client, max_input_tokens=28000, num_ctx=32768)
    nav = RLMMethod(client, max_rounds=14, num_ctx=16384)
    rec = RecursiveRLM(client, max_rounds=12, sub_num_ctx=16384, root_num_ctx=8192)

    print(f"{'method':16s} {'cond':11s} {'pred':16s} {'ok':>3s} {'total_tok':>10s} {'detail':44s}")
    # recursive RLM FIRST (the new mechanism), then grep-navigate, then in-context (slowest)
    for cond in ("plain", "structured"):
        r = await rec.apredict(recs, cond, "root_cause")
        detail = (f"root={r.root_in+r.root_out:,} sub={r.sub_in+r.sub_out:,} "
                  f"subcalls={r.n_subcalls} maxRootPrompt={r.max_root_prompt:,}")
        print(f"{'rlm_recursive':16s} {cond:11s} {str(r.prediction)[:16]:16s} {'Y' if ok(r.prediction) else '·':>3s} "
              f"{r.total_tokens:10,d} {detail:44s}", flush=True)
    for cond in ("plain", "structured"):
        r = await nav.apredict(recs, cond, "root_cause")
        print(f"{'rlm_navigate':16s} {cond:11s} {str(r.prediction)[:16]:16s} {'Y' if ok(r.prediction) else '·':>3s} "
              f"{r.total_tokens:10,d} {f'grep; {r.rlm_rounds} rounds':44s}", flush=True)
    for cond in ("plain", "structured"):
        r = await inc.apredict(recs, cond, "root_cause")
        print(f"{'in_context':16s} {cond:11s} {str(r.prediction)[:16]:16s} {'Y' if ok(r.prediction) else '·':>3s} "
              f"{r.total_tokens:10,d} {'reads whole window (chunked)':44s}", flush=True)

    print("\nkey: rlm_recursive's max_root_prompt stays small even though sub-LMs read the window —")
    print("that is the paper's mechanism (offloaded context + recursion). grep-navigate is cheapest")
    print("for a sparse signal; recursion's value is capability on inputs beyond the context window.")


if __name__ == "__main__":
    asyncio.run(main())
