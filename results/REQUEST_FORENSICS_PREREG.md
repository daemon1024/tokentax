# Pre-registration: per-request forensics, P / S / T

**Written 2026-10-20 before the first model cell.** Model-free work done before this document: the
ambiguity gate (below), the case sample, the harness and its 33 unit tests, and the reference numbers in
"Model-free reference". The only model calls made before it are two transport/capability probes, listed
under "Models". No cell of the experiment has been run.

`WITHDRAWAL.md` withdrew the earlier pre-registration because the committed test was never executed and the
headline metric appeared in no line of Python. Every quantity below is already computed by code on disk:
`src/tokentax/forensics_stats.py` (statistics, unit-tested), `scripts/analyze_request_forensics.py` (the
decision rule), `scripts/run_request_forensics.py` (the run). Hashes at the bottom.

## Question

On the culprit-service task, `trace_id` measured as a null (+2,025 median tokens, no accuracy gain,
p = 0.00083) because that task is answered by counting errors per service and never needs a cross-service
join. `trace_id` is a **join key**, so it can only pay on a task that *is* a join. This run tests that task:

> Given ONE error log line, return the indices of every other log line in the window that belongs to the
> same request, and name the service where the failure originated.

## Dataset and why it is allowed

`data/otel_demo/logs.jsonl` + `manifest_multifault.json`: 12 windows of 75 s, 64,356 records, ~1.0M
cl100k tokens each. Only the 9 anomalous windows yield seeds. **Gitignored, one machine, one capture,
not reproducible.**

**Gate (model-free, run before this document; `results/runs/gate/*.json`).** Criterion from
`scripts/check_request_ambiguity.py`: median concurrent requests >= 5 AND median services per erroring
trace >= 2, with >= 30 usable edge errors, at W = 2 s.

| input | edge | usable | median concurrent @2s | median services | verdict |
|---|---|---|---|---|---|
| whole capture | frontend | 0 | — | — | INDETERMINATE |
| whole capture | frontend-proxy | 0 | — | — | INDETERMINATE |
| whole capture | all services | 689 | 154.0 | 3.0 | PROCEED |
| 12 manifest windows | frontend | 0 | — | — | INDETERMINATE |
| 12 manifest windows | frontend-proxy | 0 | — | — | INDETERMINATE |
| 12 manifest windows | all services | 259 | 156.0 | 3.0 | **PROCEED** |
| sc10 (negative control) | all / product-catalog | 760 | 38.0 | 1.0 | STOP |

Two things the PROCEED does not say, stated now so they cannot be discovered later:

1. **The edge emits no ERROR logs.** `frontend` has no log records at all and `frontend-proxy` (55% of the
   capture's records, envoy access lines) has zero ERROR records. The seeds are therefore ERROR lines at *inner*
   services (`product-catalog`, `cart`, `ad`) that carry the hand-patched `logger.error`, not edge/symptom
   lines. The task brief allowed the "all services" fallback; this is that fallback.
2. **The verdict moves with W.** At W = 0.05 s the median is 4.0 concurrent requests (< 5, STOP); at
   0.25 s it is 22.0. The requests themselves are short (median span 216 ms first-to-last line, measured
   model-free), so the genuinely ambiguous window is a few hundred ms, where 22 requests interleave. The
   PROCEED at W = 2 s overstates the ambiguity a competent searcher faces.

## Sample (frozen in `results/runs/request_forensics_cases.json`)

*Eligible seed:* an ERROR record with a non-empty `trace_id`, whose trace has >= 2 other lines in >= 2
services; one seed per trace, the **last** error line of the trace (so the first error line is the
originating one). Eligible: product-catalog 225, ad 16, cart 9 (250). `otelcol-contrib` errors are
untraced and fall out.

*Draw:* `random.Random(20261020)`, stratified by fault window. **Main n = 30: 11 productCatalogFailure,
10 adFailure, 9 cartFailure** (all 9 cart seeds exist; the strata are NOT proportional to the population,
which is 90% product-catalog). **Pilot: 2 + 2 seeds, disjoint from main, never analysed.**

Main seeds: truth = 3-30 other lines (median 7), 2-10 services (median 3). `root_service` equals the seed's
own service in 30/30, so the root-service metric is uninformative on this dataset (see Limitations).

## Arms

| arm | `LogREPL` condition | each line carries | seed line shown as |
|---|---|---|---|
| P | `plain` | `[i]` + `LogRecord.body()` | body |
| S | `structured_no_trace` | + `svc=` + `sev=` | `svc= sev=` + body |
| T | `structured` | + `trace=<8 hex>` | `svc= sev= trace=<32 hex>` + body |

The seed is also given its timestamp (ISO-8601 UTC, ms) in every arm. **No arm sees per-line timestamps**;
`lines_near` is the only time handle. This is the repo's existing line format, left unchanged.

**Tools: one schema, byte-identical in all arms** (`forensics_tool_schemas()` takes no condition argument):
`overview, grep, peek, errors_by_cluster, errors_by_service, extract_trace_ids, lines_for_trace` (the
existing matched set) plus the new `lines_near(timestamp, seconds)`. A tool whose backing field is absent
replies `not available ...`; the count of such replies is recorded per cell. `lines_near` returns at most
40 lines (the closest to the centre, shown in index order, with a count of the rest), `seconds` in
[0, 30]. `lines_for_trace` and the `trace_id` scope of the digests accept the 8-char prefix the lines
display (T arm only; unique prefixes only), because the lines show 8 chars and the tool otherwise needs 32.

**One system prompt for all arms** (`forensics.SYSTEM`), and an overview that carries data only: the
existing harness told the T arm "use extract_trace_ids / lines_for_trace" and the P arm "no service field",
which is prompt-level steering. Neither is present. The service roster is in the prompt of every arm.

**Scrubbing.** Every arm goes through `LogRecord.body()`. Measured on the 64,356 window records: 0 hex
tokens >= 16 chars in any `body()`, 0 own trace/span ids, 0 `otel*` residuals. Residual correlation keys
**remain in the text of every arm by nature**: envoy `x-request-id` UUIDs, `sessionId=` in URLs, `userId=`
in cart and checkout lines. They are application content, not instrumentation identity, and can give P a
legitimate grep join. They are not removed; their effect is a limitation, not a bug.

## Models

`gpt-oss:120b`, `nemotron-3-ultra`, `gemma4:31b` (Ollama Cloud). The preferred list could not be run:
probed 2026-10-20 with one tiny request each, `qwen3.5:397b` returned **410 Gone**, and `glm-5.3`,
`deepseek-v4.1-flash`, `kimi-k3`, `minimax-m3` returned **402 Payment Required**. The three chosen answered
the probe and each emitted a well-formed tool call on a pilot seed in a single-round capability probe
(no cell run). `nemotron-3-ultra` is kept although `nezha_matrix_v2.jsonl` shows 83/84 timeouts at 240 s
on a different task, because the probe above answered in 5 s; the longer timeout below is partly for it.
If a model's smoke run (below) ends >= 9 of 12 cells in timeout / transport / unavailable, it is dropped
and replaced by the next of `nemotron-3-super`, `minimax-m3.1-flash`; that is the only use of smoke results.

HTTP 429 and 5xx are **transport failures, retried later, never results**; 402/403/404/410 are
**unavailable**, not run, reported. If the cloud is exhausted, the fallback is local Ollama
(`qwen3.5:9b`, `gpt-oss:20b`, `qwen3:14b`); local results are reported as a separate stratum and never
pooled with cloud.

## Fixed configuration

```
sample_seed 20261020   main 30 seeds x 3 arms x 3 models = 270 cells   concurrency 3
cell timeout 300 s   max rounds 20   token ceiling 250,000   num_ctx 32,768
OllamaClient: temperature 0, seed 0, think=False, 3 HTTP retries
lines_near: max 40 lines, seconds in [0,30]     correct := line-set F1 >= 0.8
```

Changing any of these is a new output file, not a resumed run. `num_ctx` may not be enforced by the cloud
backend; the largest single-round prompt is recorded per cell and compared to it afterwards. The token
ceiling truncates the cost of any arm that reads a lot (P most plausibly): a ceiling hit is a failure whose
cost is the observed tokens, so P's cost is a lower bound wherever it hits.

## Metrics

- **Line-set F1** over the *other* lines of the request. The seed is removed from both truth and
  prediction. Ground truth = every record in the window with the seed's `trace_id`.
- **Correct** := F1 >= 0.8. Chosen before any data: it tolerates one or two missed lines on a typical
  7-line request, but a trace of 3 other lines allows one miss only if nothing extra is returned. Reported
  also at F1 >= 0.5 and F1 = 1 as sensitivity; those do not enter any decision.
- **Tokens** = sum over every round of `prompt_eval_count + eval_count` as counted by the provider
  (a real tokenizer, not the cl100k proxy; but each model tokenizes differently, so tokens are compared
  only within a model).
- **Tokens per correct (TPC)** = sum of observed tokens over *all* observed cells of the arm / number
  correct. Failures keep their observed tokens in the numerator and add nothing to the denominator.
- **Primary statistic:** the geometric mean over models of the within-model ratio TPC(T)/TPC(S), over
  complete (model, seed) triples. Ratios are formed within a model first because tokenizers differ.
- **Secondary:** root-service exact match; median tokens on answered cells; per-model breakdown;
  by-stratum table (descriptive only).

## Failures are data

A cell ends as `answered`, `no_answer` (token ceiling, round cap, or no parseable JSON), `timeout`
(wall clock; tokens are the rounds that completed, a lower bound, flagged `censored`), `transport` or
`unavailable`. The first three are observations: they score F1 = 0 and keep their tokens; a timeout is
**never** `total_tok = 0`. `transport`/`unavailable` are not observations, are retried by re-invoking the
runner, and are counted. Analysis uses *complete triples* (all three arms observed for a (model, seed)),
so the arms always see identical cells. The first observation of a cell is never replaced.
Paired **token** deltas use pairs where both arms *answered* (a censored token count is not comparable);
paired **F1** deltas and TPC use all observed cells. Failure counts are in the accounting table of the
write-up; means state which cells they cover.

## Decision rule (T vs S isolates `trace_id`, holding service + severity constant)

The **falsification condition fires** if ANY of:

1. geometric-mean TPC ratio T/S **> 0.80** (T is not at least 20% cheaper per correct answer), or
2. the 95% cluster-bootstrap CI (5,000 resamples of the 30 seeds, all models and arms kept together,
   seed 20261020) has upper bound **>= 1.0**, or
3. the **noise replicate** does not agree (below): for `gpt-oss:120b`, the replicate T/S ratio is > 1.0 or
   differs from the main-run ratio by >= 0.20, or no replicate exists, or
4. **non-inferiority fails**: mean case-level F1(T) - F1(S) < **-0.05**.

If none fires, trace_id pays on this task, for these models, on this data. The 20% margin is a practical
significance floor; the replicate is the run-to-run noise check on the *headline ratio itself*, not an
imported figure (the OTel Demo noise floor in `FINDING.md` was measured on a different task).

**Reported separately, not part of the falsification:** whether T *raises* F1 over S (case-level mean
dF1 > 0 and exact sign test p < 0.05 on the 30 case-level values, each averaged over models); S vs P
(`service.name`); T vs P.

**Tests.** Per model: exact two-sided sign test on paired dF1 and on paired dTok (ties dropped), n <= 30.
Pooled: sign tests on *case-level* values (averaged over the models that have the pair; token values are
mean ln-ratios), because the three models share the 30 seeds and 90 pairs are not independent. Means and
medians are both reported.

**Noise replicate.** After the main run, `gpt-oss:120b` x 30 seeds x 3 arms is run again with the identical
configuration into `request_forensics_rep2.jsonl`. Only that model is replicated (the fastest and the only
one whose cell cost is cheap).

## Smoke

4 pilot seeds x 3 arms x 3 models = 36 cells into `request_forensics_smoke.jsonl`, same configuration,
disjoint seeds, excluded from analysis. Purpose: harness validation. A harness *bug* it exposes is fixed and
recorded as a dated amendment below before the main run; the sample and configuration are not touched.

## Model-free reference (measured before any model call)

| W (s) | lines in window, median | time-window-only F1 mean | cases with F1 >= 0.8 |
|---|---|---|---|
| 0.05 | 9 | 0.260 | 0/30 |
| 0.1 | 17 | 0.265 | 0/30 |
| 0.25 | 49 | 0.223 | 0/30 |
| 0.5 | 88 | 0.193 | 0/30 |
| 1.0 | 144 | 0.126 | 0/30 |

Returning *everything* within +/-W of the seed never reaches F1 >= 0.8 on any of the 30 seeds, so a time
window alone cannot solve the task and a model must filter by content. The exact lines of the request cost
a median of **600** cl100k tokens (max 997); reading the +/-0.05 s window costs 1,443 and +/-0.25 s costs
9,012; the whole window is ~1.0M. The mechanical lower bound for `lines_for_trace` is therefore real, which
is exactly why a model-free bound cannot be the result.

## Known limitations, stated before seeing results

- **The seeds are the hand-patched `logger.error` lines.** The labels are constructed. This run uses no
  fault-label accuracy, but the seed text ("failed to retrieve product from catalog backend ...") is
  distinctive, which makes *locating* the seed easier in every arm than it would be in the wild.
- **Root service is trivial here**: root == seed's service in 30/30. A predictor that copies the seed's
  service scores 30/30 in S and T; in P the service is not shown. Report it, conclude nothing from it.
- **n = 30 seeds, 3 models, one run per cell** (one replicate of one model). Strata are small (9-11); no
  per-stratum claim will be made. Cart requests (24 lines, 10 services) are a different regime from
  product-catalog (7 lines, 3 services).
- **Ground truth is the trace_id partition.** Lines with no `trace_id` (5% of records) can never be in
  truth, and the truth is "same trace", which may differ from "same user action" for session-spanning flows.
- **Plain-text correlation keys remain** (see Scrubbing) and may let P do better than a keyless log would.
- **No per-line timestamps in any arm**; envoy access lines are long (attributes folded in by the loader)
  and dominate token cost, so absolute tokens are not a general log-analysis figure.
- **One capture, one machine, no backup.** Models are served by a third party and may change underneath.
- A null here does not show `trace_id` is useless; it shows it did not pay *on this workload*, where the
  entire stack is 11 services, requests are short, and the seed is easy to find.

## Provenance (sha256 at time of writing)

```
b1550f0268146d5b175b6485f1548ccb7793275943eee5d10c12c277bbf2ca5f  data/otel_demo/logs.jsonl
0083cb49790395ebfa35d6ba2e7def39b8559b510265d23a2277c05dccd6e1ba  data/otel_demo/manifest_multifault.json
787c732af9e043165b4b981d7d2409d7a919c44b9b25acb932816e20d488c665  results/runs/request_forensics_cases.json
4485fb8e07a219a510067d21c941d9f396ae4729c586092a68489b2636b97454  src/tokentax/forensics.py
b9ce3993f73c78759c6a17f9f37594491d5fc60f94a8179a3f8447c977bc11b1  src/tokentax/forensics_stats.py
e91a06ab63cb00aff1dbd68e0833692707916a00a049ba8fd544c29704fd4cd2  scripts/run_request_forensics.py
d6c2c36153f20825ee5bc06d315678cd688e971be4caca02d10d715a8c0cfbb1  scripts/analyze_request_forensics.py
912fe83259988f7c4acb75d5633fa6b53bc5983e9223585d26b4e23da3474a2c  scripts/check_request_ambiguity.py
a0f07cbf14c40226648777e17491638090fdafa520a95aa0d4c5bd2feb02f922  scripts/check_request_ambiguity_windows.py
```

## Amendments

(none yet; any change after the first model cell is dated and listed here with the new hash)
