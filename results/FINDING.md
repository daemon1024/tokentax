> [!CAUTION]
> **PARTIALLY RETRACTED (2026-08-20, same day).** Two follow-up runs invalidated the token results below.
>
> **1. The token contrasts are inside the noise floor.** This document reported paired bootstrap CIs
> from a single run per cell. Re-running cells whose tool schema is *byte-identical* shows the models
> are not deterministic despite `temperature=0` and a fixed seed:
>
> | condition | median Δ across runs | mean \|Δ\| | identical cells |
> |---|---|---|---|
> | plain | +680 | **39,758** | 0/48 |
> | structured_no_trace | +288 | **8,347** | — |
> | structured | +13 | **12,112** | 3/47 |
>
> Every within-navigation effect below is smaller than this. The CIs measured only *within-run*
> pairing and never observed run-to-run variance. **"Structure saves tokens" is not established** —
> it flips sign depending on tool-schema gating and is inside the noise either way.
>
> **2. The `trace_id` penalty was mostly my own harness.** Tool schemas are re-sent every round and
> differed per arm — 267 / 320 / **459** tokens for plain / no_trace / structured. That is +139 tok per
> request × ~3 rounds ≈ 417, against a reported penalty of 514. Re-running with schemas matched across
> all arms (`--matched-schemas`, `runs/cloud_matrix_matched.jsonl`) cut it to **−182**.
>
> **3. The task cannot test the hypothesis at all.** "Name the culprit service" is answered by one
> aggregate (ERROR count per service, take the top). Correlating a request across services is never
> required, so `trace_id` is never on the critical path — trace tools were called in **17%** of
> structured cells, 18 calls out of 313. A null was guaranteed by construction, independent of every
> defect above.
>
> **What replaces it — see `NAVIGATION.md`.** The comparison that was missing from this document is
> RLM vs reading the whole window, and it is decisive: **1,127,422 vs 3,985 median tokens (331×),
> accuracy 2/6 vs 6/6.** That gap is orders of magnitude outside the noise floor. The compression comes
> from *navigating instead of reading* — not from trace structure.
>
> Sections 3, 4 and 5 below (plain fails by exhaustion; direction inconsistent across models; means
> mislead and the tail is the story) are unaffected and still stand.

# The corrected result: structure buys accuracy, not tokens — and `trace_id` costs tokens

**Run:** 8 frontier models (Ollama Cloud) × 3 arms × 12 OTel-Demo windows = **288 cells, 0 failures**.
Tables: `CLOUD_ANALYSIS.md` (generated). Raw: `runs/cloud_matrix.jsonl` (includes tool sequences).
Supersedes `MATRIX_RESULTS_V2.md` — see `WITHDRAWAL.md` for why that run does not hold.

This is the first run in this project with **matched aggregation power across arms**, **parallel prompt
framing**, **one variable per contrast**, and **paired bootstrap CIs**.

## What was asked

The original thesis: *OpenTelemetry trace context is free input compression — a trace-aware navigator
reaches the same conclusion for far fewer tokens.* Three arms isolate the pieces:

| arm | line content | aggregator | trace tools |
|---|---|---|---|
| `plain` | body only | `errors_by_cluster` (Drain templates) | — |
| `structured_no_trace` | + `service.name`, severity | `errors_by_service` | — |
| `structured` | + `trace_id` | `errors_by_service` | `extract_trace_ids`, `lines_for_trace` |

`plain → structured_no_trace` isolates **service identity**.
`structured_no_trace → structured` isolates **`trace_id` alone** — the contrast no published work runs.

## Result

**1. `service.name` saves tokens. `trace_id` costs them.**

| contrast | median Δ tok | 95% CI | ratio |
|---|---|---|---|
| plain → structured_no_trace | **+1,092 saved** | [+21, +2,916] · excludes 0 | 0.77× |
| structured_no_trace → structured | **−514 spent** | [−654, −374] · excludes 0 | **1.20×** |
| plain → structured | −194 | [−478, +905] · **crosses 0** | 1.07× |

Adding `trace_id` and the trace tools makes the task **20% more expensive**, significantly, with no
offsetting cost benefit. Net structure-vs-plain on tokens is a **wash** — the CI crosses zero.

**The headline claim is refuted on its own axis.** Trace context is not free input compression here; it
is a net token cost. The token saving that does exist comes from `service.name`, which is a plain
structured-logging field and has nothing to do with tracing.

**2. Structure does buy accuracy — modestly, and this is the real effect.**

| contrast | acc | paired Δ | 95% CI |
|---|---|---|---|
| plain → structured_no_trace | 0.948 → 0.979 | +0.031 | [−0.021, +0.083] crosses 0 |
| structured_no_trace → structured | 0.979 → 1.000 | +0.021 | [+0.000, +0.052] crosses 0 |
| plain → structured | 0.948 → 1.000 | **+0.052** | **[+0.010, +0.104] excludes 0** |

Neither single step is significant; the combined effect is. Structure moves accuracy 0.948 → 1.000.

**3. Plain's failure mode is exhaustion, not error.** Four of five plain misses are `unknown` returned
after **56k–201k tokens** of flailing (`qwen3.5:397b` burned 200,720 on one window). Only one plain miss
is a genuine mis-attribution. Structure's accuracy benefit is mostly *preventing runaway navigation*,
not improving reasoning.

**4. The direction is not consistent across models.** Two of eight are *more expensive* with full
structure: `mistral-large-3:675b` at **2.86×** (median 1,088 plain → 3,110 structured — it is the single
most efficient model on plain and one of the worst on structured) and `deepseek-v4-pro:0813` at 1.09×.
Any claim of a general structure discount has to survive this; it does not.

**5. Cost is a heavy-tailed distribution and means lie.** Plain: mean 29,072, median 5,328, max 286,925.
The old runs reported means only. The mean/median gap *is* the finding — structure narrows the tail
(plain p90 = 120,345 vs structured p90 = 17,008), which is a variance story, not a central-tendency one.

## Scope — what this does and does not establish

**Does not generalise to real incidents.** The dataset is recoverable by construction: `infra/otel-demo/`
patches a `logger.error` into each fault-origin service, and the injected text *names the culprit in
plain English* — `failed to retrieve product from catalog backend`, `cart store unavailable`,
`failed to retrieve ads: ad service backend unavailable`. One `errors_by_cluster()` call therefore solves
the task with no structure at all, which is why accuracy sits near ceiling in every arm.

That makes this a valid **cost control** and an invalid test of hard localisation. Read the result as:
*when the answer is present in message text and both arms can aggregate, trace context adds cost and
little else.* Whether `trace_id` earns its cost when several services error and cause must be separated
from symptom is **still open** — and needs a dataset with multi-service error cascades, which this is not.

**Other limits.** 12 windows, one fault family each, one run per cell (no temperature variance estimate);
cloud `gpu_seconds` is null so cost is tokens only; `cl100k_base` remains a token proxy for accounting.

## What this changes

The project's framing was "structure is free compression, accuracy is the non-inferiority guard." The
data says the opposite: **accuracy is where structure pays, and tokens are where it costs.** A successor
experiment should pre-register the accuracy axis as primary and treat tokens as the guard.

The one contrast worth running next is the one this dataset cannot host: multi-service error cascades
where the top-ranked erroring service is a *symptom*, not the cause. That is the only condition under
which trace context should be expected to earn its 20% premium.
