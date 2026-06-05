"""Build results/RLM_COMPARISON.md from results/runs/rlm_compare.jsonl."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
J = ROOT / "results/runs/rlm_compare.jsonl"
DOC = ROOT / "results/RLM_COMPARISON.md"
MODELS = ["qwen3:8b", "qwen3.5:9b", "gpt-oss:20b", "gemma4:e4b"]


def main() -> None:
    rows = {}
    for line in J.read_text().splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        rows[(r["model"], r["method"], r["condition"])] = r

    def cell(m, meth, c):
        r = rows.get((m, meth, c))
        if not r:
            return "—"
        ok = "✓" if r["correct"] else ("ERR" if r["pred"] == "ERROR" else "✗")
        s = f"{r['total_tok']:,} {ok}"
        if meth == "recursive":
            s += f" (sub={r['subcalls']},maxRoot={r['max_root_prompt']:,})"
        return s

    out = ["# tool-RLM vs recursive-RLM — cross-model, structured vs unstructured", "",
           "One productCatalogFailure window (capped ~200 records / ~40k tokens), root-cause task, "
           "local Ollama. Cell = total tokens + correct(✓)/wrong(✗)/error(ERR); recursive also shows "
           "sub-call count and max single root-prompt (the offloaded-context signature). truth=product-catalog.",
           ""]
    # main table: model rows, columns = method x condition
    out += ["| model | tool plain | tool struct | recursive plain | recursive struct |",
            "|---|---|---|---|---|"]
    for m in MODELS:
        out.append(f"| {m} | {cell(m,'tool','plain')} | {cell(m,'tool','structured')} | "
                   f"{cell(m,'recursive','plain')} | {cell(m,'recursive','structured')} |")
    # maxRootPrompt focus (recursive only)
    out += ["", "## Recursive RLM — root context stays tiny (max single root-prompt, tokens)", "",
            "| model | plain maxRoot | struct maxRoot | plain sub-calls | struct sub-calls |",
            "|---|---|---|---|---|"]
    for m in MODELS:
        rp = rows.get((m, "recursive", "plain"))
        rs = rows.get((m, "recursive", "structured"))
        if rp and rs:
            out.append(f"| {m} | {rp['max_root_prompt']:,} | {rs['max_root_prompt']:,} | "
                       f"{rp['subcalls']} | {rs['subcalls']} |")
        else:
            out.append(f"| {m} | (incomplete) | | | |")
    # accuracy + token summary
    out += ["", "## Summary", ""]
    for meth in ("tool", "recursive"):
        for c in ("plain", "structured"):
            cs = [rows[(m, meth, c)] for m in MODELS if (m, meth, c) in rows]
            if not cs:
                continue
            acc = sum(x["correct"] for x in cs) / len(cs)
            mt = sum(x["total_tok"] for x in cs) // len(cs)
            out.append(f"- **{meth} / {c}**: acc {acc:.2f}, mean {mt:,} tok (n={len(cs)})")
    out += ["", "## Findings", "",
            "1. **All 16 cells correct** (recoverable task) — accuracy doesn't separate methods/models "
            "here; the signal is TOKENS and the root-context ceiling.",
            "2. **Recursive RLM is cheaper than our tool-RLM on average** (plain 2,962 vs 14,665; "
            "structured 1,923 vs 5,427). The gap is biggest where tool-RLM flails: qwen3.5:9b plain "
            "tool=40,706 vs recursive=2,825 (~14x). tool-RLM *accumulates* grep results in a growing "
            "root transcript re-sent each round; the recursive root stays disciplined and small.",
            "3. **The root-context ceiling is tiny and ~constant across models** (maxRoot 631–1,045 "
            "tokens) regardless of window size — the offloaded-context signature, now shown for all 4 "
            "model families, not just qwen3:8b.",
            "4. **Structure helps both methods** (tool 14.7k→5.4k; recursive 3.0k→1.9k).",
            "5. **Honest nuance: recursion was rarely *invoked*** — 7/8 recursive cells did 0 sub-LM "
            "calls (only qwen3:8b-plain made 1). For this sparse, grep-localizable signal the root "
            "solved it by examining (overview+grep) without dispatching sub-LMs. So this run mainly "
            "demonstrates the *offloaded-context discipline* (tiny root), not the sub-LM recursion "
            "itself — which only pays off when the relevant region is too big to examine directly.",
            "", "_Caveat: single window (~40k tok, 200 records, productCatalog fault), local Ollama, "
            "one run per cell — directional, not error-barred._"]
    DOC.write_text("\n".join(out) + "\n")
    print(f"wrote {DOC} ({len(rows)} cells)")


if __name__ == "__main__":
    main()
