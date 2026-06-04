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
