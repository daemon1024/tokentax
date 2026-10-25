# Pre-registration: per-request forensics V3, the printed id vs the lookup vs telling the model

**Status: FINAL, 2026-10-25, before the first main cell.** Written after the tool-call probe and a 6-cell
smoke on one pilot seed (neither is analysed). Any later change is a dated amendment with a new output file.

## Relation to V1 and V2

V1 (`REQUEST_FORENSICS_PREREG.md`) and V2 (`REQUEST_FORENSICS_V2_PREREG.md`, result `REQUEST_FORENSICS_V2.md`)
are **not modified** and their cells are **never pooled** with V3's. V2 found that the arm T (trace_id
printed on every line AND a live lookup) beats S (service.name only): beam 30/30 vs 6/30,
minimax-m3.1-flash 28/30 vs 0/30. T changed two things at once relative to S: the id on the line, and the
tools that look it up. V3 separates them, and adds a third model.

## Questions

1. **Printed id (S → Tt).** Does printing `trace=<id>` on every line pay when the lookup tools are off?
   `grep` can still find the id in the text, so a model that greps it gets the request's lines.
2. **Lookup (Tt → T).** Holding the printed id fixed, does the live lookup pay on top?
3. **Tell it (T → Th).** Does one sentence saying what the field is for change how the model works? Primary
   outcome: rounds (turns). V2 observed minimax-m3.1-flash find the request with `lines_for_trace` and
   then spend many rounds re-verifying.
4. **Replication on a third model (S → T, P → S)** on `deepseek-v4-pro:0813`.

## Dataset, sample: unchanged from V1/V2

`data/otel_demo` (sha256 below), the frozen 30 main seeds (11 productCatalogFailure, 10 adFailure, 9
cartFailure) and 4 disjoint pilot seeds in `results/runs/request_forensics_cases.json`; the runner refuses
to start if the sample it rebuilds differs (`run_request_forensics.load_cases`).

## Arms (`src/tokentax/forensics_v3.py`)

| arm | condition | each line the model reads | seed line | trace tools | system prompt |
|---|---|---|---|---|---|
| P | `plain` | `[i]` + body | body | "not available" | SYSTEM |
| S | `structured_no_trace` | `[i] svc= sev=` + body | `svc= sev=` + body | "not available" | SYSTEM |
| T | `structured` | `[i] svc= sev= trace=<8 hex>` + body | `svc= sev= trace=<32 hex>` + body | live | SYSTEM |
| **Tt** | `structured_trace_text` | **byte-identical to T** | as T | "not available" (as S); overview as S | SYSTEM |
| **Th** | `structured_hint` | as T | as T | live | SYSTEM + HINT |

HINT, inserted once right after the service roster: *"Every log line carries trace=<id>, the id of the
request it belongs to. lines_for_trace(id) returns every line of one request."*

**Tt vs T differ in exactly:** the four trace tools reply "not available" (`lines_for_trace`,
`extract_trace_ids`, and the `trace_id=` scope of `errors_by_cluster` / `errors_by_service`), and the
overview omits the "distinct trace_ids: N" line (it is S's overview). **Tt vs S differ in exactly:** the
printed `trace=` text on every line and on the seed. **Th vs T differ in exactly:** HINT.

**What does not differ between arms:** the tool schema (`forensics.forensics_tool_schemas()`,
byte-identical), the agent loop (`forensics_v3.run_agent_v3`, which `tests/test_forensics_v3.py` checks
sends exactly V1's messages for P / S / T), the user message wording, scoring.

## Models (probe rows in `results/runs/model_probe.jsonl`)

| | model | why |
|---|---|---|
| A | `beam` | V2's model 1 (fresh controls in this run) |
| B | `minimax-m3.1-flash` | V2's model 2, the flash model (fresh controls in this run) |
| C | `deepseek-v4-pro:0813` | a current flagship, unlocked by the account's move to Ollama Pro on 2026-10-25; probe PASS (pinned dated tag; the untagged name also passed) |

Other models probed on 2026-10-25 on the free tier: PASS nemotron-3-ultra, gpt-oss:120b, nemotron-3-super,
gemma4:31b; HTTP 402 (paid) glm-5.3-flash, deepseek-v4.1-flash, kimi-k2.6, minimax-m3, glm-5.2,
kimi-k2.7-code, mistral-large-3:675b. Model C was chosen by the operator from the paid set before any C
cell ran.

## Fixed configuration

```
timeout 300 s   max rounds 20   token ceiling 250,000   num_ctx 32,768
OllamaClient: temperature 0, seed 0, think=False, 3 HTTP retries       host https://ollama.com (Pro)
lines_near: max 40 lines, seconds in [0,30]                            correct := line-set F1 >= 0.8
concurrency 3 (the Pro account's concurrent-request limit, so no request waits in the provider's queue)
spend cap $45 estimated at peak list prices (beam, unlisted, at a deliberately high $1.00/$4.00 per M)
```

**Order (one queue, drained by 3 workers in this order; inside a phase seed-major, arms adjacent):**

1. beam × P, S, T, Tt, Th
2. deepseek-v4-pro:0813 × T, Tt, Th
3. minimax-m3.1-flash × T, Tt, Th
4. deepseek-v4-pro:0813 × P, S
5. minimax-m3.1-flash × P, S

Cheap, decision-bearing cells first, so a cut-off (spend cap or a usage-limit 429) leaves complete paired
sets for the contrasts that matter most. Changing any of the above is a new output file, never a resumed
run. Re-invoking the same command resumes: only cells without an observation re-run.

## Metrics (`scripts/analyze_request_forensics_v3.py`, written before the first main cell)

Per model × arm, over observed cells (`answered`, `no_answer`, `timeout`; a timeout keeps the tokens of its
completed rounds, flagged censored, never zero): right answers (F1 ≥ 0.8), failures by status, tokens
(provider `prompt_eval_count + eval_count`, median and mean), **tokens per right answer (TPC)** = all
observed tokens ÷ right answers, rounds (median, mean), **grep_trace** = runs whose `grep` pattern carried
a ≥ 8-hex substring of the seed's trace id, **lookup_trace** = runs that pointed a trace tool at it (in Tt
those calls reply "not available" and still count). `transport` / `unavailable` are not observations; they
are counted and re-run.

## Contrasts and decision rules (per model; models are never pooled)

For a contrast a → b (b has one more thing), over seeds where both arms are observed:

- **Printed id S → Tt, lookup Tt → T, printed id + lookup S → T, service.name P → S.** b is
  **supported** if ALL of: TPC(b)/TPC(a) ≤ 0.80; mean paired F1(b) − F1(a) ≥ −0.05; and either the exact
  two-sided sign test on per-seed correctness (b − a) or on ln(tokens b / tokens a) over pairs where both
  answered has p < 0.05 in b's favour. **Opposite** if TPC ratio ≥ 1.25 and a sign test favours a at
  p < 0.05. Otherwise **not shown**. If a has no right answer, b is supported only if the correctness sign
  test favours b at p < 0.05 and F1 is non-inferior.
- **Tell it T → Th.** **Supported** if the exact sign test on per-seed rounds (Th − T, all observed pairs)
  favours Th at p < 0.05 and mean paired F1 is non-inferior (≥ −0.05). **Opposite** if it favours T at
  p < 0.05. Secondary, reported: TPC ratio, tokens sign test, right answers.

Reported, not decision-bearing: every arm table; grep_trace / lookup_trace counts; fresh V3 controls
against V2's cells for beam and minimax-m3.1-flash (P, S, T) as a drift check; estimated spend.

Three models × five contrasts are many tests; no multiplicity correction is applied, exact p is reported,
and a claim in the talk names the model it holds for.

## Smoke (pilot seed 1, `request_forensics_v3_smoke.jsonl`, never analysed)

| model | arm | status | F1 | tokens | rounds | grep id | lookup id |
|---|---|---|---|---|---|---|---|
| beam | Tt | answered | 0.80 | 10,384 | 3 | no | yes ("not available") |
| beam | Th | answered | 1.00 | 2,500 | 2 | no | yes |
| deepseek-v4-pro:0813 | Tt | answered | 1.00 | 83,884 | 9 | yes | yes ("not available") |
| deepseek-v4-pro:0813 | Th | answered | 1.00 | 3,021 | 2 | no | yes |
| minimax-m3.1-flash | Tt | answered | 1.00 | 30,735 | 6 | yes | yes ("not available") |
| minimax-m3.1-flash | Th | answered | 1.00 | 5,749 | 3 | yes | yes |

No harness error; Tt's lookups replied "not available" as designed. Estimated spend $0.14.

**Estimate for the main run (not a measurement):** beam ~1.5M tokens; deepseek T/Tt/Th ~3M, P/S up to
~15M if it hits the ceiling like minimax; minimax T/Tt/Th ~5–10M, P/S ~15M. Roughly $15–35 at peak prices,
under the $45 cap.

## Known limitations, stated before seeing results

All of V1's and V2's (constructed seeds — the hand-patched `logger.error` lines; trivial root service;
n = 30; one capture; plain-text correlation keys in every arm), plus: one run per cell; models served by a
third party; V2 ran on the free tier, where the account's concurrency limit was 1 and V2's 2 workers
could queue at the provider (queue time counted against the 300 s timeout) — V3 runs at the account limit
with no provider queue, which is why the controls are re-run inside V3 rather than borrowed from V2.

## Provenance (sha256 before the first main cell)

```
b1550f0268146d5b175b6485f1548ccb7793275943eee5d10c12c277bbf2ca5f  data/otel_demo/logs.jsonl
0083cb49790395ebfa35d6ba2e7def39b8559b510265d23a2277c05dccd6e1ba  data/otel_demo/manifest_multifault.json
787c732af9e043165b4b981d7d2409d7a919c44b9b25acb932816e20d488c665  results/runs/request_forensics_cases.json
4485fb8e07a219a510067d21c941d9f396ae4729c586092a68489b2636b97454  src/tokentax/forensics.py          (= V1)
b9ce3993f73c78759c6a17f9f37594491d5fc60f94a8179a3f8447c977bc11b1  src/tokentax/forensics_stats.py    (= V1)
af95fe4bc4dde38060ec86efd4ae67af1d9d93b6ab000991404f1c4cbdf4ea08  src/tokentax/forensics_v2.py       (= V2)
8b68ba6507fb4192dfffa54ef15467b80e079ba1eee4c42b13f56646e5db6008  src/tokentax/forensics_v3.py
e91a06ab63cb00aff1dbd68e0833692707916a00a049ba8fd544c29704fd4cd2  scripts/run_request_forensics.py   (= V1)
c145a38a0fe0f6103d9054baf6b382dc9826cb6c868081df6e9fdce56afb72be  scripts/run_request_forensics_v3.py
5d1cc4798f9e666da04e2f8416e13714fb936324756ee0b9eee136f092e1af9e  scripts/analyze_request_forensics_v3.py
0767bc2032208a34d6af19c28d6e4dda187bf9af62b9ac69620dbfcee0f13777  tests/test_forensics_v3.py
c7aca750713181c833840575984a16350220b32c5e916ed2ba114fd9dbd9bda6  src/tokentax/methods/ollama_client.py
82aa211b9aba428c96e0fdacd193b959fb90dd6672e2d586278bf0e84548f257  src/tokentax/methods/repl.py
7061af1f89956f0a46306baf6faca7d6430194a2d10602a7ba412b056a497c86  results/runs/request_forensics_v3_smoke.jsonl
422b3f02b2fd15b5997c5edaf3c063aea12ddef3385b0b4cd054fc206cb6a1ff  results/runs/request_forensics_v2.jsonl  (V2, untouched)
```

Main-run command (re-invoking it resumes; only cells without an observation re-run):

```bash
set -a; . ./.env; set +a
.venv/bin/python scripts/run_request_forensics_v3.py        # -> results/runs/request_forensics_v3.jsonl
.venv/bin/python scripts/analyze_request_forensics_v3.py    # -> request_forensics_v3_analysis.{json,md}
```

## Amendments

(none)
