# Withdrawal of the pre-registered claim

**Date:** 2026-08-20 · **Applies to:** `BENCHMARK_PLAN_v3.md` §7 (pre-registered decision rule) and every
LLM result in `results/`.

## What was pre-registered

`BENCHMARK_PLAN_v3.md:124-127` committed, before running, to:

- a token effect size — structured-RLM ≤ X% of in-context-plain `cost_per_correct`;
- F1 non-inferiority within −δ via bootstrap CI;
- a primary confirmatory cell: **RLM on trace-anomaly, structured vs plain**.

## What is being withdrawn, and why

**The pre-registered test was never run.** The confirmatory cell was trace-anomaly; every LLM script in
`scripts/` passes the literal string `'root_cause'`. `cost_per_correct` — the headline metric — appears in
no line of Python in this repository. No LLM result here carries a confidence interval. Zero of the five
Definition-of-Done items were met.

**What was run instead does not support the thesis.** The 192-cell matrix (`results/runs/matrix_v2.jsonl`)
compares a plain arm against a structured arm that has an extra tool, `errors_by_service()`
(`src/tokentax/methods/repl.py:97`) — a ranked per-service ERROR-count digest gated on `trace_aware`. It
never reads `trace_id`, so it does not test trace-aware navigation.

Three independent defects, each sufficient on its own:

1. **The digest reproduces the labelling function.** `infra/otel-demo/` patches a hand-authored
   `logger.error` into the fault-origin service; `scripts/run_matrix_v2.py:34` maps the fault flag to that
   same service. The culprit is consequently the *only* erroring service in 9 of 9 anomalous windows, and
   `argmax()` over the digest scores **11/12 with no model in the loop** — matching the best structured
   cells. Across 96 structured cells the LLM never beat the digest and lost to it three times.

2. **Outcome-dependent stopping.** `d39a652` cut the per-cell timeout 240s → ~150s *mid-run*, for exactly
   the two models whose *plain* cells were failing. gemma4's slowest successful cell is 147.6s. Those
   timeouts were then published as the finding "plain isn't just costlier — it's INFEASIBLE."

3. **Censored cost.** 30 of 31 timeouts are plain cells, booked at `total_tok=0`. `MATRIX_NOTES.md`
   averages answered cells only; `MATRIX_RESULTS_V2.md` averages all 12. The two disagree in *sign* for 3
   of 8 model-method pairs.

**The honest measurement points the other way.** `results/runs/rlm_compare_matched_tools.jsonl` (formerly
misfiled as `rlm_compare_leaky_v2.jsonl` — it is *not* leaky) is the immediately preceding run: same code,
windows and models, **tools matched, no digest**. Against `rlm_compare.jsonl`, which differs only by adding
the digest to the structured arm:

| run | tool/plain | tool/struct | rec/plain | rec/struct |
|---|---|---|---|---|
| matched tools, no digest | 14,495 · 2/4 | 5,720 · 4/4 | **8,910 · 4/4** | **9,646 · 4/4** |
| digest added to structured only | 14,495 · 2/4 | 2,755 · 4/4 | **8,910 · 4/4** | **1,986 · 4/4** |

The plain columns are bit-identical; only the structured cells move. With tools matched, structured was
**more expensive** than plain at identical accuracy. `RLM_COMPARISON.md` finding #4 claims the earlier null
"was a missing tool, not a refutation" — that inverts what the data show. The null was the honest result.

## Other claims affected

- **`gpu_seconds` is not measured.** Computed correctly at `ollama_client.py:40` and hardcoded to `0.0` at
  `rlm.py:115` and `llm_incontext.py:125` — on every local run where Ollama returned real durations.
- **"Recursive RLM" mostly did not recurse.** 89 of 96 recursive cells made zero sub-calls (70 of 77 among
  non-error cells). `rlm_recursive.py:154` also silently yields an *empty* chunk when the model omits `end`.
- **The `Method.predict → Result` contract** that `CLAUDE.md` called non-negotiable is dead code — nothing
  subclasses it; four methods return three result types.

## What survives, and is worth keeping

1. **The envelope tax.** OTLP-JSON costs 1.47–2.19× plain tokens to read the same content. Replicated
   across Train Ticket, qwen and Sonnet. Unaffected by any defect above. (Note the 2026 format literature —
   TOON/JTON — has since attributed most of this to whitespace.)
2. **The compression handle.** Fault signal occupies 0.02–0.34% of a ~1.07M-token window.
3. **The recoverability finding — the most valuable result in this repository.** In Nezha, the injected
   service emits *any* ERROR in 12 of 38 windows and is named in the failure text in 2 of 38; anomalous and
   normal traces both average 0.06 errors/trace. Real micro-fault datasets largely do not encode their
   labels in logs. This killed the project's own primary task, which is why it is trustworthy.
4. **The negative engineering results:** `deepseek-v2:16b` cannot drive the Ollama tools API; format alone
   does not rescue an 8B on a 70k-token window.

## Status

The pre-registration is **withdrawn, not amended**. Any successor experiment must be pre-registered afresh,
with matched tool capability across arms as a stated precondition. Superseded documents are retained with
correction banners rather than deleted, so the record of what was actually run stays auditable.
