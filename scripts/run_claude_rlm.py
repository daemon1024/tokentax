"""RLM on Claude Sonnet via the subscription: Claude navigates a log FILE with its native tools.

The most natural RLM — Claude Code is a log-navigating agent. We write the window to a file and ask
it to find the culprit by grepping/reading SELECTIVELY (not reading the whole file). Token usage then
reflects only what it pulled in (navigation cost) + the constant ~30k harness overhead — to compare
against in-context, which read the whole 460-679k-token window.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from tokentax.methods.claude_cli import claude_call  # noqa: E402
from tokentax.methods.llm_incontext import _parse_json  # noqa: E402
from tokentax.nezha import format_window  # noqa: E402
from tokentax.otel_loader import windows_from_manifest  # noqa: E402

LOGS = ROOT / "data/otel_demo/logs.jsonl"
ORIGIN = {"productCatalogFailure": "product-catalog", "cartFailure": "cart", "adFailure": "ad"}

PROMPT = """There is a microservice log file at {path} ({nlines} lines, too large to read fully).
AT MOST one service is failing. Find the single culprit service (the one emitting the failure).
Navigate EFFICIENTLY: use Grep to find error/exception lines first, then Read only the few relevant
lines. Do NOT read the whole file. When done, respond with ONLY JSON {{"culprit_service": "<name>"}}."""


def correct(pred: str, truth: str) -> bool:
    norm = lambda s: re.sub(r"[^a-z0-9]", "", str(s).lower())  # noqa: E731
    p, t = norm(pred), norm(truth)
    return t in p or (p in t and len(p) > 3)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", default=str(ROOT / "data/otel_demo/manifest_sweep1.json"))
    ap.add_argument("--model", default="sonnet")
    args = ap.parse_args()
    windows = windows_from_manifest(LOGS, args.manifest)

    print(f"model={args.model} RLM (claude navigates a log file via Grep/Read)\n")
    print(f"{'cond':11s} {'window':22s} {'in_tok':>9s} {'out':>5s} {'cost$':>6s} {'pred':18s} {'ok':>3s}")
    results = {}
    for w in windows:
        truth = ORIGIN.get(w.fault or "", "none")
        for cond in ("plain", "structured"):
            text = format_window(w.records, cond)
            with tempfile.NamedTemporaryFile("w", suffix=f"_{cond}.log", delete=False) as f:
                f.write(text)
                path = f.name
            prompt = PROMPT.format(path=path, nlines=len(w.records))
            r = claude_call(prompt, model=args.model, allowed_tools="Grep,Read")
            pred = str(_parse_json(r.content).get("culprit_service", "")).strip()
            ok = correct(pred, truth)
            results[(w.key, cond)] = {"in": r.input_tokens, "out": r.output_tokens,
                                      "cost": r.cost_usd, "pred": pred, "ok": ok}
            print(f"{cond:11s} {w.key[:22]:22s} {r.input_tokens:9,d} {r.output_tokens:5d} "
                  f"{r.cost_usd:6.2f} {pred[:18]:18s} {'Y' if ok else '·':>3s}", flush=True)
            Path(path).unlink(missing_ok=True)

    (ROOT / "results/runs/claude_rlm.json").write_text(json.dumps(
        {f"{k[0]}|{k[1]}": v for k, v in results.items()}, indent=2))
    print("\nwrote results/runs/claude_rlm.json")
    print("(compare in_tok here vs in-context's 460-679k full read)")


if __name__ == "__main__":
    main()
