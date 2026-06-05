# Cross-model RLM matrix — running narrative (human notes)

Data tables are auto-regenerated in `MATRIX_RESULTS.md`; this file holds interpretation
that the runner won't overwrite. RLM root-cause task on 12 multifault OTel windows.

## Tick 1 — ~41/120 cells
- **qwen3:8b** (baseline): 18/24 correct, 1 abort. Structured cells ~3 rounds / ~3-5k tokens;
  plain cells sometimes flail (one hit the 14-round ceiling at ~96k tokens).
- **qwen3.5:9b**: 12/17 so far with **8 aborts — all on PLAIN windows**, where it burns
  **12-14 rounds and 72-124k tokens** trying to navigate without structure, then hits the
  round/token ceiling. Its structured cells are clean (correct, fewer rounds, cheaper).
- Early signal (consistent with the thesis): **structure makes RLM navigation tractable;
  plain navigation degrades badly even on a 9B** (high rounds, high tokens, frequent aborts).
  Aborts on *normal* plain windows still score "correct" (truth=none) — a scoring artifact to
  note, not real success.
- gpt-oss:20b downloading; gemma4:e4b / deepseek-v2:16b queued (their tool-calling support TBD).

## Tick 2 — ~93/120 cells (4 of 5 models)
- **gpt-oss:20b: 23/24 correct, 2 aborts** — best navigator; clean tool use, low rounds.
- **gemma4:e4b: 20/21 correct, 1 abort** — SURPRISE/correction: gemma4 *does* support the Ollama
  tools API and does RLM well (gemma3 did not — so this is a gemma4 improvement, not a family trait).
- **qwen3:8b: 18/24** (1 abort) — solid small baseline.
- **qwen3.5:9b: 17/24, 10 aborts** — WEAKEST. It over-navigates plain windows (12-14 rounds,
  70-124k tokens) and hits the ceiling; structured cells are fine. More capable ≠ better RLM here —
  the 9B's verbosity hurts it on plain.
- Emerging cross-model picture: tool-calling RLM works on qwen3/qwen3.5/gpt-oss/gemma4; navigation
  QUALITY differs (gpt-oss:20b ≈ gemma4:e4b > qwen3:8b > qwen3.5:9b). deepseek-v2:16b pending.

## FINAL — 120/120 cells, 5 models (RLM root-cause, 12 multifault OTel windows, ~76 min run)

| model | plain acc | struct acc | plain mean_tok | struct mean_tok | struct/plain | plain abort% |
|---|---|---|---|---|---|---|
| gpt-oss:20b | 0.92 | 1.00 | 41,671 | 12,066 | 0.29x | 16% |
| gemma4:e4b | 0.92 | 1.00 | 9,515 | 5,907 | 0.62x | 8% |
| qwen3:8b | 0.50 | 1.00 | 17,558 | 3,861 | 0.22x | 8% |
| qwen3.5:9b | 0.50 | 0.92 | 83,312 | 22,605 | 0.27x | 75% |
| deepseek-v2:16b | — | — | — | — | — | 100% (no tools) |

### Findings
1. **Structure helps every tool-capable model, on BOTH axes.** Structured RLM costs 0.22–0.62x the
   tokens of plain (1.6–4.5x cheaper) AND raises accuracy (0.50–0.92 plain -> 0.92–1.00 structured;
   structured is perfect for 3 of 4). It also collapses the abort rate (plain 8–75% -> structured 0–8%).
   This generalizes the single-window Sonnet/qwen8b result across 4 model families/sizes.
2. **Plain navigation is where models diverge.** Without structure, gpt-oss:20b and gemma4:e4b stay
   accurate (0.92) by navigating content; qwen3:8b and qwen3.5:9b collapse to 0.50. So a better model
   is more robust to the *absence* of structure — but all still benefit from it.
3. **More capable != better/cheaper RLM.** qwen3.5:9b is the worst cell: 0.50 plain acc, **83k tokens,
   11 rounds, 75% abort** — it over-reasons and flails on plain windows, far worse than the smaller
   qwen3:8b (17k). Verbosity hurts navigation.
4. **gemma4:e4b is the efficiency winner** (9.5k plain / 5.9k structured, high acc) — and a correction
   to expectations: gemma4 *supports* the Ollama tools API and does RLM well (gemma3 did not).
   gpt-oss:20b is the most *robust* navigator (best plain accuracy).
5. **deepseek-v2:16b cannot do tool-calling RLM** — 24/24 ERROR (Ollama tools API unsupported for this
   model). Negative result: not every local model can serve as an RLM backend.

### Caveat
Accuracy is near-saturated by design (recoverable faults), so the discriminating signals are tokens,
rounds, and abort rate. n=12 windows/model; single fault family per window.

## Matrix-v2 tick — 78/192 (qwen3:8b done + qwen3.5:9b partial)
Corrected cross-model run (true-plain + errors_by_service digest). Pattern stable:
- structured: ~1.5–1.9k tok, acc 0.80–0.89 (digest localizes the fault cheaply).
- plain: 9–35k tok, acc 0.25–0.53 (mis-attributes to symptom services product-review/recommendation).
- tool/plain mean inflated by qwen3.5:9b flailing (one normal window = 87,984 tok — over-navigates
  with no service field to anchor on).
- recursive > tool on accuracy in BOTH conditions (0.89 vs 0.80 structured; 0.53 vs 0.25 plain).
- Minor: a recursive-structured miss on a normal window -> "otelcol-contrib" (the collector's own
  internal error appears in the digest; should bucket otelcol-* out). gpt-oss:20b + gemma4:e4b pending.
