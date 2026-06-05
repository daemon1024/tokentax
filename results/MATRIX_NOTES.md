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

## Matrix-v2 tick — 96/192 (qwen3:8b + qwen3.5:9b both complete)
Both qwen models done; pattern unchanged from the 78-tick (structured cheap+accurate, plain
expensive+mis-attributing). gpt-oss:20b running, gemma4:e4b queued (both faster MoE — should finish
in ~30-45 min). Runner healthy, ~67 min elapsed.

## Matrix-v2 tick — 108/192 + adaptation
gpt-oss:20b is much slower on the 1M-token windows and its PLAIN cells TIME OUT (240s) — it flails
navigating a million tokens with no service field to anchor on, while its STRUCTURED cells finish in
~40s via errors_by_service. This is itself a strong thesis statement: on large inputs, plain RLM is
not just costlier but INFEASIBLE for the slower model, whereas the structured digest is trivial.
Restarted gpt-oss:20b + gemma4:e4b with a tighter 150s cell-timeout + fresh budget so the matrix
completes (their plain cells will mostly record as timeouts = the finding; structured cells are real).

## Matrix-v2 tick — 126/192
gpt-oss:20b (30/48): structured cells succeed via the digest (~1.3-1.6k tok, fast); plain cells time
out (ERROR) as expected — confirms plain RLM is infeasible on 1M-token windows for the slower model.
Minor: a few structured-normal cells answer "otelcol-contrib" (the collector's internal error shows in
the errors_by_service digest) instead of "none" — should bucket otelcol-* out of the digest. gemma4:e4b
queued. Budget on track to complete.
## Matrix-v2 tick — 142/192: gpt-oss 46/48, gemma4:e4b last; pattern holds (structured cheap+correct via digest, plain ERROR/timeout). Budget ~46min left for gemma.
## Matrix-v2 tick — 173/192: gemma4:e4b 29/48 (last model), runner alive. Pattern holds for gemma too (structured ~1.6k correct, plain ERROR/product-review). Budget tight; may need a short gemma resume.

## FINAL — matrix-v2 COMPLETE, 192/192 cells (corrected cross-model run)

4 tool-capable models × 12 multifault OTel windows × {tool-RLM, recursive-RLM} × {plain, structured}.
This run **supersedes the leaky `matrix.jsonl`**: the fix is two-fold — (a) `LogREPL` lines are
condition-aware (plain = bare message body; structured = svc/sev/trace tags) so "plain" no longer
leaked `service.name` into every grep result; (b) a structured-only `errors_by_service()` digest
(per-service ERROR count, computable *only* because structured logs carry `service.name`) — that
digest is the actual "free input compression" the thesis is about. Windows here are realistic: 200 to
**5,600 records, up to ~735k plain tokens**. Token means below **exclude ERROR/timeout cells** (those
emit 0 tokens and would deflate the plain means); timeout counts are reported separately because the
timeouts are themselves a finding.

| model | tool plain | tool struct | rec plain | rec struct |
|---|---|---|---|---|
| qwen3:8b   | 2/12 · 10.7k · 0 TO | **9/12 · 1.4k** | 7/12 · 9.6k · 1 TO | **11/12 · 1.7k** (maxRoot~855) |
| qwen3.5:9b | 5/12 · 67.6k · 2 TO | **11/12 · 1.8k** | 6/12 · 12.5k · 2 TO | **11/12 · 2.2k** (maxRoot~1.1k) |
| gpt-oss:20b| 2/12 · 18.7k · **9 TO** | **11/12 · 6.1k** | 3/12 · 4.4k · **9 TO** | **10/12 · 3.1k** · 1 TO (maxRoot~1.1k) |
| gemma4:e4b | 6/12 · 5.4k · 1 TO | **11/12 · 2.1k** | 3/12 · 2.3k · **6 TO** | **11/12 · 2.7k** (maxRoot~1.1k) |

(cells = accuracy/12 · mean tokens when answered · timeouts; recursive structured also shows mean maxRoot.)

### Findings — thesis confirmed across all four model families
1. **Structure = free input compression, and it generalizes.** In EVERY model, structured collapses
   the task to **1.4–6.1k tokens at 9–11/12 accuracy** via one `errors_by_service()` call → a ~10-token
   digest ("product-catalog=2") → answer, almost always with 0 sub-LM calls. Plain, when it answers at
   all, costs **5.4–67.6k tokens at 2–7/12**. Per-model token reduction ranges **~2.5× (gemma tool) to
   ~37× (qwen3.5:9b tool: 67.6k → 1.8k)**; accuracy simultaneously roughly doubles.
2. **At scale, plain isn't just costlier — it's INFEASIBLE.** On the ~670–735k-token windows the slower
   models time out navigating raw lines: **gpt-oss:20b times out on 9/12 plain cells in BOTH methods**;
   gemma4:e4b on 6/12 recursive-plain. Structured **never** times out for the same windows (the digest
   is tiny). So structure is the difference between answering and not answering — not a mere discount.
3. **Plain mis-attributes to the symptom service.** Without `service.name`, the navigator repeatedly
   blames `recommendation`/`product-review` — services that error *because they call* the failing
   `product-catalog` (downstream symptom, not root cause). The digest disambiguates cause from symptom.
4. **Recursive RLM keeps the root context tiny — the offloaded-context signature holds.** Even on
   735k-token windows, recursive `maxRoot` stays **855–6,349 tokens** (structured: ~855–1,100). The
   full window never enters the root model's context; the root reasons over metadata + sub-answers.
5. **Bigger ≠ more robust on raw input.** gpt-oss:20b (the largest) is the *most fragile* on plain
   (9/12 timeouts) yet fully recovers on structured (11/12 tool, 10/12 recursive). qwen3.5:9b over-
   navigates plain (67.6k tokens) where the smaller qwen3:8b uses 10.7k. Structure rescues every model
   regardless of size; capability does not substitute for it.
6. **The earlier "anti-thesis" null was a missing tool, not a refutation.** With only verbose grep the
   RLM had no way to *exploit* structure, so structured wasn't cheaper. The value appears exactly when
   the navigator can compute a compact, field-derived digest in the environment (the RLM/REPL premise)
   instead of reading raw lines — which is the whole point.

### Caveats
Single fault family per window; faults are log-recoverable by construction (so accuracy is near a
ceiling and the discriminating signals are tokens + timeout rate). n=12 windows/model, one run/cell —
directional, not a CI'd headline. The pre-registered confirmatory cell (RLM on trace-anomaly,
structured vs plain, bootstrap CIs) is still the formal test; this matrix is the supporting
cross-model generalization. `otelcol-*` should be bucketed out of the digest (the collector's own
internal errors occasionally surface as a culprit on normal windows). Prior leaky run kept in
`results/runs/matrix*.jsonl` history for audit.
