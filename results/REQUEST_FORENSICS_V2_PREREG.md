# Pre-registration: per-request forensics V2, P / S / T / TI

**Status: FINAL, 2026-10-20, before the first main cell.** The design sections were written before any V2
model call. The *Models*, *Cost estimate* and *Provenance* sections were then filled in from the tool-call
probe, one free local validation and two cloud smoke cells, none of which is analysed. Any later change is
a dated amendment with a new output file.

## Relation to V1

`results/REQUEST_FORENSICS_PREREG.md` (V1) is **not modified**. V1 was paused after 22 cells
(`results/runs/request_forensics.jsonl`, untouched) because its models are old. V2 is a **new run**: new
models, one new arm, new output files. V1 and V2 cells are **never pooled**. V1's 22 cells and its 36 smoke
cells inform the cost estimate below and nothing else.

## Question

Same as V1: given ONE error log line, return the indices of every other line of the same request and the
service where the failure originated. `trace_id` is a join key, so this is the task where it can pay.

V2 adds one question: **does the join key pay as an index, without being printed on every line?**

## Dataset, gate, sample: unchanged from V1

`data/otel_demo` (`logs.jsonl` + `manifest_multifault.json`), model-free gate PROCEED at W = 2 s over all
services (259 usable, median 156 concurrent requests, median 3 services per erroring trace;
`results/runs/gate/`), with V1's two stated caveats: the edge emits no ERROR logs (seeds are inner-service
lines carrying the hand-patched `logger.error`), and at W = 0.05 s the median is 4 concurrent requests.

**The same frozen sample:** 30 main seeds (11 productCatalogFailure, 10 adFailure, 9 cartFailure) and 4
disjoint pilot seeds, `results/runs/request_forensics_cases.json`. The runner refuses to start if the sample
it rebuilds differs from that file (`run_request_forensics.load_cases`).

## Arms

| arm | condition | each line the model reads | seed line | trace tools |
|---|---|---|---|---|
| P | `plain` | `[i]` + body | body | reply "not available" |
| S | `structured_no_trace` | `[i] svc= sev=` + body | `svc= sev=` + body | reply "not available" |
| T | `structured` | `[i] svc= sev= trace=<8 hex>` + body | `svc= sev= trace=<32 hex>` + body | live |
| **TI** | `structured_trace_index` | `[i] svc= sev=` + body (**byte-identical to S**) | `svc= sev= trace=<32 hex>` + body (as T) | live |

**Rationale for TI, stated before any TI cell.** In T every line any tool returns carries `trace=<8 hex>`.
Measured in situ on this dataset that prefix costs **6.4 cl100k tokens per line** (6.7 per traced line),
structured minus no_trace (`talk/NUMBERS.md`, Stage 3 caveat 1), and every returned line is re-sent on
every later round. TI keeps the trace INDEX (the seed hands over its id; `lines_for_trace`,
`extract_trace_ids` and the `trace_id=` scope of both digests work exactly as in T) and drops the per-line
TAX. In TI `grep` cannot find a trace id in the lines, because no line contains one.

**What does not differ between arms:** the tool schema (`forensics.forensics_tool_schemas()`, one function,
no condition argument, byte-identical), the system prompt (`forensics.SYSTEM`), the data-only overview
(TI's overview is T's), the seed timestamp, the agent loop. P / S / T cells run through V1's
`forensics.run_agent` itself; TI runs through `forensics_v2.run_agent_v2`, the same loop with the REPL and
seed renderer injected. `tests/test_forensics_v2.py` asserts the two loops send identical messages for
P / S / T and that TI's lines are byte-identical to S's.

## Models

Candidates, newest first, from the live catalogue (`GET /api/tags`, 2026-10-20, 23 models): muse-spark-open,
beam, minimax-m3.1-flash, deepseek-v4.1-flash:1017, mistral-large-4, clef:27b, glm-5.3, kimi-k3. **No model
named "laya" or anything similar is in the catalogue.** Each candidate got ONE tiny request in the
harness's own call shape (`scripts/probe_tool_calls.py`: `GuardedOllamaClient`, `think=False`,
`num_ctx` 32,768, one `get_weather` tool, a prompt that requires calling it). PASS = a well-formed tool call
naming the tool with `city` = Paris. Raw rows: `results/runs/model_probe.jsonl`.

| model | probe | reason (provider's body) |
|---|---|---|
| muse-spark-open | FAIL | HTTP 402 "this model is not included in your free usage" |
| **beam** | **PASS** | `get_weather({"city": "Paris"})`, 153 tokens |
| **minimax-m3.1-flash** | **PASS** | `get_weather({"city": "Paris"})`, 487 tokens |
| deepseek-v4.1-flash:1017 | FAIL | HTTP 402, same body |
| mistral-large-4 | FAIL | HTTP 403 "currently being rolled out and is not yet [available]" |
| clef:27b | FAIL | HTTP 400 "is a decision model and only supports /v1/sy[...]" (not the chat endpoint) |
| glm-5.3 | FAIL | HTTP 402, same body |
| kimi-k3 | FAIL | HTTP 402, same body |

**The account is on the free tier** (the 402 body says so), which bounds the quota.

**Run order, model-major: 1. `beam`, 2. `minimax-m3.1-flash`.** All 120 cells of beam before minimax, so a
quota cut-off leaves complete paired comparisons for whichever model finished. beam goes first because its
smoke cell cost 3,393 tokens against minimax's 120,692 for the same correct answer (see Cost estimate),
so a fixed quota completes more quadruples. The replicate (below) is therefore run on beam.

## Fixed configuration (V1 verbatim, except concurrency)

```
sample_seed 20261020   main 30 seeds x 4 arms x M models        concurrency 2 (V1: 3)
cell timeout 300 s   max rounds 20   token ceiling 250,000   num_ctx 32,768
OllamaClient: temperature 0, seed 0, think=False, 3 HTTP retries
lines_near: max 40 lines, seconds in [0,30]     correct := line-set F1 >= 0.8
order: model-major; inside a model seed-major, arms adjacent in the order P, S, T, TI
```

Changing any of these is a new output file, never a resumed run. Re-invoking the same command resumes:
only cells without an observation re-run.

## Metrics and failures: V1's definitions

Line-set F1 over the OTHER lines of the request (seed removed from both sides); correct := F1 >= 0.8
(sensitivity at 0.5 and 1.0, no decision). Tokens = provider-counted `prompt_eval_count + eval_count` summed
over every round, compared only within a model. **Tokens per correct (TPC)** = sum of observed tokens over
all observed cells of an arm / number correct. A cell is `answered`, `no_answer` (ceiling, round cap, no
parseable JSON), `timeout` (tokens = completed rounds, a lower bound, flagged censored), `transport` or
`unavailable`. The first three are observations (F1 = 0 for failures, tokens kept, never zero). The last two
are not observations; they are counted and re-run. **Analysis unit: complete quadruples**, (model, seed)
with all four arms observed. Paired token deltas use pairs where both arms answered; paired F1 and TPC use
all observed cells. Medians AND means are reported; failure counts are reported separately per arm.

**Usage limit.** An HTTP 429 whose body says "usage limit" stops the whole run at once
(`forensics_v2.GuardedOllamaClient`; no retry loop). Observed cells stay; the rest stay owed; the write-up
is marked PARTIAL and states which models and seeds the numbers cover.

## Hypotheses and decision rules (computed by `scripts/analyze_request_forensics_v2.py`)

**H1 (V1's primary, re-tested): T pays over S.** Falsification fires if ANY of
1. geometric-mean (over models) TPC ratio T/S **> 0.80**;
2. 95% cluster-bootstrap CI (5,000 resamples of seeds, every model and arm of a seed kept together,
   seed 20261020) has upper bound **>= 1.0**;
3. mean case-level F1(T) - F1(S) **< -0.05** (non-inferiority);
4. replicate: TPC(T, replicate) / TPC(S, main) for model 1 **> 0.80**. If no replicate is run, H1 is
   reported "not replicated" and is not called confirmed.

**H2: TI pays over S** (the index alone, no per-line prefix). The same four conditions with TI in place of T.

**H3: TI is cheaper than T** (the per-line prefix is a real cost at task level). Claimed only if ALL of:
geometric-mean TPC ratio TI/T < 1.0; exact sign test on case-level mean ln(tok_TI / tok_T) over answered
pairs p < 0.05; mean case-level F1(TI) - F1(T) >= -0.05; and |ln ratio| exceeds the replicate noise, the
larger of |ln TPC(rep)/TPC(main)| for T and for TI on model 1. Otherwise H3 is "not shown". If T is cheaper
than TI by the same test, that is reported as the opposite finding (the printed id helps navigation).

**Reported, not decision-bearing:** S vs P (`service.name`), T vs P, TI vs P; per-model tables;
root-service exact match (uninformative here: root == seed service in 30/30, see V1); F1 >= 0.5 and F1 = 1
sensitivity; tool-use counts; not-available tool replies per cell.

**Tests.** Exact two-sided sign tests (ties dropped) on case-level values (each seed averaged over the
models that have the pair), and per model. The models share the seeds, so model-by-seed pairs are not
treated as independent.

## Noise replicate

After the main run of model 1: model 1 x 30 seeds x arms **T and TI** only, identical configuration, into
`results/runs/request_forensics_v2_rep2.jsonl`. P and S are not replicated: they are the expensive arms (V1
mean ~160-175k tokens per cell) and H1/H2's replicate condition only needs the cheap arm's run-to-run
spread against the main-run S.

## Validation before the first main cell

1. Offline tests (`tests/test_forensics_v2.py`, `tests/test_analyze_forensics_v2.py`).
2. **Local, free:** one pilot seed x 4 arms on a local model into `request_forensics_v2_local.jsonl`.
3. **Cloud smoke:** ONE cell per chosen model (arm TI, pilot seed 1, the new code path) into
   `request_forensics_v2_smoke.jsonl`. Smoke and local cells are disjoint from the main seeds and are
   never analysed. A harness bug they expose is fixed and recorded as a dated amendment before the main run.

## Validation done, and the cost estimate

**Local (free), `request_forensics_v2_local.jsonl`, qwen3.5:9b, pilot seed 1 x 4 arms.** All four arms ran
end to end with no harness error. P and S hit the 300 s wall clock (107,511 and 148,980 tokens, censored);
T and TI answered with F1 = 1.0 in 2 rounds (3,219 and 3,179 tokens). TI's first call was
`lines_for_trace` on the seed's id, and its result lines carried no `trace=` text. No harness bug was found,
so no amendment was needed.

**Cloud smoke, `request_forensics_v2_smoke.jsonl`, ONE cell per model, arm TI, pilot seed 1.**

| model | status | F1 | tokens | rounds | first tool |
|---|---|---|---|---|---|
| beam | answered | 1.00 | 3,393 | 3 | `lines_for_trace` (round 1 was an empty reply, nudged by V1's loop) |
| minimax-m3.1-flash | answered | 1.00 | 120,692 | 8 | `grep`; it found the request with `lines_for_trace` in round 1, then spent 7 rounds re-verifying (a 27 KB `peek`, `lines_near`, wide greps) |

Cloud tokens spent before the main run: probe 640 + smoke 124,085 = **124,725**.

**Estimate for the main run (provider tokens; not a measurement of the run).** Basis: V1's observed per-cell
means over all 58 V1 cells on three older models (P 173,711 over 20 cells; S 159,051 over 19; T 4,170 over
19; 17 of 39 P/S cells ended at the token ceiling), scaled by the smoke above.

| item | per seed | 30 seeds |
|---|---|---|
| beam: P 174k + S 159k (V1 means) + T 4k + TI 3.4k | ~340k | **~10.2M** (upper ~16M if P and S always hit the 250k ceiling) |
| minimax-m3.1-flash: P, S near the ceiling, T and TI at its smoke cost (~120k) | ~490-760k | **~15-23M** |
| replicate, beam T + TI | ~7.6k | ~0.23M |
| **total** | | **~25-39M** |

On a free-tier account this almost certainly exceeds the remaining quota. The run is therefore expected to
end on a usage-limit 429 (clean stop, PARTIAL write-up), and the order above decides what is complete when
it does. Nothing about the design changes because of that; the analysis is restricted to complete
quadruples, as written above.

## Known limitations, stated before seeing results

All of V1's (constructed seeds, trivial root service, n = 30, plain-text correlation keys in every arm, no
per-line timestamps, one capture), plus:
- **One run per cell** except the T/TI replicate of model 1.
- **TI vs T is a small effect by construction.** V1's T cells cost ~3-6k tokens; the prefix touches only
  the lines tools return. The run-to-run noise on a ~4k-token cell is of the same order (median absolute
  rerun delta 528 tokens on the OTel Demo control, `talk/NUMBERS.md` claim 7). H3 is powered to see a
  large prefix tax or nothing.
- **P and S are expected to hit the 250,000-token ceiling often** (V1: 17 of 39 P/S cells ended
  `no_answer`). Their TPC is then a lower bound on what an unbounded search would cost.
- The models are served by a third party and may change underneath; the catalogue date is recorded.

## Provenance (sha256 before the first main cell)

```
b1550f0268146d5b175b6485f1548ccb7793275943eee5d10c12c277bbf2ca5f  data/otel_demo/logs.jsonl
0083cb49790395ebfa35d6ba2e7def39b8559b510265d23a2277c05dccd6e1ba  data/otel_demo/manifest_multifault.json
787c732af9e043165b4b981d7d2409d7a919c44b9b25acb932816e20d488c665  results/runs/request_forensics_cases.json
4485fb8e07a219a510067d21c941d9f396ae4729c586092a68489b2636b97454  src/tokentax/forensics.py          (= V1)
b9ce3993f73c78759c6a17f9f37594491d5fc60f94a8179a3f8447c977bc11b1  src/tokentax/forensics_stats.py    (= V1)
e91a06ab63cb00aff1dbd68e0833692707916a00a049ba8fd544c29704fd4cd2  scripts/run_request_forensics.py   (= V1)
c7aca750713181c833840575984a16350220b32c5e916ed2ba114fd9dbd9bda6  src/tokentax/methods/ollama_client.py
af95fe4bc4dde38060ec86efd4ae67af1d9d93b6ab000991404f1c4cbdf4ea08  src/tokentax/forensics_v2.py
649da63431ba63c7bb307c6533ab672a073280dcbeb18de8a8cb6e61696122e9  scripts/run_request_forensics_v2.py
ff15d653d9f8798722c202fca4c40f061db551881814b12872f146c62970721a  scripts/analyze_request_forensics_v2.py
ee29582a57b106bc709e00c23ed56b66e6a14a833ce9fe29446cfe973fba1cd7  results/runs/model_probe.jsonl
357959ef202b2be72900fd50c92e71298a4fe912a60dc05c2d00d162498e4c09  results/runs/request_forensics_v2_local.jsonl
1e90392a98718a3cce9d241c4960611eef7a6ad85ce31540bf7bd336eea8162f  results/runs/request_forensics_v2_smoke.jsonl
474ce7d93233c13ddcff0431aa1872c1f45f8d4bb52d17d17a0c9cf3dc9ef4fa  results/runs/request_forensics.jsonl  (V1, untouched)
26f92ad09512889e7a0b6c3709fc87a113c53bfefc22fef85060e9b717bbc155  results/REQUEST_FORENSICS_PREREG.md  (V1, untouched)
```

Main-run command (re-invoking it resumes; only cells without an observation re-run):

```bash
set -a; . ./.env; set +a
.venv/bin/python scripts/run_request_forensics_v2.py --models beam,minimax-m3.1-flash   # -> request_forensics_v2.jsonl
.venv/bin/python scripts/run_request_forensics_v2.py --tag rep2 --models beam --arms T,TI   # replicate, after
.venv/bin/python scripts/analyze_request_forensics_v2.py
```

## Amendments

- **2026-10-20 12:18Z, procedural only; no design, parameter, sample or analysis change.** beam's 120
  main cells were complete (all observed). minimax-m3.1-flash's first two seeds cost ~1.63M tokens (P and S
  at the ceiling, T up to 275k), which puts its 30 seeds at ~24M, likely past the free-tier quota. The beam
  replicate (scheduled "after the main run of model 1", ~0.25M tokens) was therefore run BEFORE the rest of
  minimax, so that it is not lost to a quota cut-off. The main-run process was stopped at a seed boundary
  (8 minimax rows written), the replicate was run (`--tag rep2 --models beam --arms T,TI`, 60 cells), and
  the main run was resumed with the identical command. Cells in flight when the process was stopped wrote
  no row, so they are not observations; they stay owed and run on resume. Total concurrency never
  exceeded 2.
