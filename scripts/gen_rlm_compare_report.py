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
    out += ["", "## Findings (corrected — true-plain navigation)", "",
            "Methodology fix vs the earlier run: `LogREPL` used to prepend `svc=`/severity to EVERY "
            "grep line regardless of condition, so the RLM's 'plain' secretly contained the service "
            "name. Now plain lines are the bare message body; structured lines expose svc=/sev=/trace= "
            "tags + the trace tools. This makes plain genuinely require inferring the culprit.",
            "",
            "1. **Structure's real benefit is correct ATTRIBUTION, not token savings.** On true-plain, "
            "tool-RLM is only **2/4 correct** — qwen3.5:9b and gemma4:e4b answer `recommendation`, a "
            "service that errors *because it calls* the failing product-catalog (symptom, not cause). "
            "The explicit `svc=` field (structured) fixes attribution → **4/4**. The earlier 'structure "
            "= cheaper navigation' was largely the leak.",
            "2. **Token effect is now method-dependent, not a clean win.** tool-RLM: structure cheaper "
            "(plain 14.5k → struct 5.7k) because true-plain makes it flail (no svc to grep → many "
            "rounds; gpt-oss 30.8k, qwen3.5 16.6k). recursive: structure slightly *costlier* (plain "
            "8.9k → struct 9.6k) because svc=/sev= tags make grep lines longer (maxRoot 700–1,090 plain "
            "vs 2,600–3,450 structured).",
            "3. **Recursive RLM is more ROBUST on plain** — 4/4 vs tool-RLM's 2/4. Its prompt directs "
            "it to infer the culprit from content, and it reads carefully (sometimes a sub-LM call), "
            "so it resists the recommendation symptom-distractor that fools tool-RLM on plain.",
            "4. **Recursion still rarely *invoked*** — most recursive cells used 0–1 sub-LM calls; the "
            "sparse signal is grep-localizable. The mechanism's value (offloaded context, tiny root, "
            "inputs beyond the context window) is real but this task doesn't force it. qwen3:8b "
            "recursive is the cost outlier (~19k — over-navigates).",
            "", "_Caveat: single window (~40k tok, 200 records, productCatalog fault), local Ollama, "
            "one run per cell — directional, not error-barred. Earlier leaky-plain run kept at "
            "results/runs/rlm_compare_leaky.jsonl for comparison._"]
    DOC.write_text("\n".join(out) + "\n")
    print(f"wrote {DOC} ({len(rows)} cells)")


if __name__ == "__main__":
    main()
