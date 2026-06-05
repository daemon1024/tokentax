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
    out += ["", "## Findings — thesis confirmed once the RLM can EXPLOIT structure", "",
            "Two fixes vs the first run: (a) `LogREPL` lines are now condition-aware (plain = bare "
            "body; structured = svc/sev/trace tags) so 'plain' is genuinely plain; (b) a structured-"
            "only `errors_by_service()` tool returns a tiny per-service ERROR-count digest — computable "
            "ONLY because structured logs carry `service.name`. That digest is the actual 'free input "
            "compression' the thesis is about; grepping verbose lines was not exploiting structure.",
            "",
            "1. **Structure = free input compression for the navigator — confirmed.** Structured cells "
            "call errors_by_service() once → ~10-token digest ('product-catalog=2') → answer, 0 sub-"
            "calls. Means: **structured ~2–2.8k vs plain ~8.9–14.5k** — ~5–7x cheaper. Plain can't "
            "aggregate by service (no field) → must read + infer.",
            "2. **recursive + structured is the cheapest AND correct cell (mean 1,986 tok, 4/4)** — what "
            "the thesis predicts. recursive-struct (1,986) < tool-struct (2,755); both ≪ their plain.",
            "3. **Plain is genuinely hard.** tool-RLM plain = **2/4** — qwen3.5:9b & gemma4:e4b answer "
            "`recommendation`, the service that errors because it *calls* the failing product-catalog "
            "(symptom, not cause); no service field to disambiguate. recursive plain is more robust "
            "(4/4) but expensive (must read+infer; 8.9k mean).",
            "4. **The earlier 'anti-thesis' result was a missing tool, not a refutation.** With only "
            "verbose grep, the RLM had no way to use structure, so structured wasn't cheaper. The "
            "structure's value shows up exactly when the navigator can compute a compact, field-derived "
            "digest in the environment (the RLM/REPL idea) instead of reading raw lines.",
            "5. qwen3:8b recursive-plain is the cost outlier (~19.5k — over-navigates); structured "
            "fixes it (1.7k). Most recursive cells used 0 sub-LM calls (signal is digest-localizable).",
            "", "_Caveat: single window (~40k tok, 200 records, productCatalog fault, only product-"
            "catalog errors present), local Ollama, one run/cell — directional. Prior runs kept at "
            "results/runs/rlm_compare_leaky*.jsonl._"]
    DOC.write_text("\n".join(out) + "\n")
    print(f"wrote {DOC} ({len(rows)} cells)")


if __name__ == "__main__":
    main()
