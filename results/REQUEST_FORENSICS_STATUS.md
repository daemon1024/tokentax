# Per-request forensics: status, paused by the operator

**There is no result in this document.** The pre-registered run (`REQUEST_FORENSICS_PREREG.md`, 270 cells)
was stopped after **22 cells** to conserve Ollama cloud quota. The operator's message said 20; the file on
disk holds 22 rows, and it has been left exactly as found. `results/REQUEST_FORENSICS.md` was not written,
because there is nothing to analyse yet: no paired table, no tokens-per-correct, no verdict on the
falsification condition. A successor run with newer models will be pre-registered separately, by a different
owner of the cloud calls; this run is not to be resumed.

The pre-registration was not edited. No model call was made after the stop order.

## What exists

| artifact | state |
|---|---|
| `results/REQUEST_FORENSICS_PREREG.md` | written before the first model cell, unchanged |
| `results/runs/gate/*.json` | model-free gate outputs, complete |
| `results/runs/request_forensics_cases.json` | frozen sample (30 main + 4 pilot seeds), sha256 `787c732a...c665` |
| `results/runs/request_forensics_smoke.jsonl` | 36 harness-smoke cells on the 4 pilot seeds; excluded from any analysis |
| `results/runs/request_forensics.jsonl` | **22 of 270** main cells, sha256 `474ce7d9...ef4fa`, NOT analysed |
| `results/runs/request_forensics_rep2.jsonl` | does not exist (the noise replicate was never run) |

## The 22 cells that completed (status only)

3 of the 30 main seeds were touched. Cells were launched seed-major with arms adjacent, so what finished is
mostly whole triples: 7 of the 8 (seed, model) pairs started are complete triples, so the set is small and
not a random subset of the 90 triples. Statuses below are cell accounting, not outcomes to be summed into a
claim.

| seed | stratum | model | P | S | T |
|---|---|---|---|---|---|
| `adFailure@1780512217532789000#1669` | adFailure | gpt-oss:120b | answered | no_answer | answered |
| `adFailure@1780512217532789000#1669` | adFailure | nemotron-3-ultra | no_answer | not run | not run |
| `adFailure@1780512217532789000#1669` | adFailure | gemma4:31b | not run | not run | not run |
| `cartFailure@1780512112521021000#3107` | cartFailure | gemma4:31b | answered | answered | answered |
| `cartFailure@1780512112521021000#3107` | cartFailure | gpt-oss:120b | answered | answered | answered |
| `cartFailure@1780512112521021000#3107` | cartFailure | nemotron-3-ultra | no_answer | no_answer | answered |
| `productCatalogFailure@1780511857491378000#1599` | productCatalogFailure | gemma4:31b | answered | answered | answered |
| `productCatalogFailure@1780511857491378000#1599` | productCatalogFailure | gpt-oss:120b | timeout | timeout | answered |
| `productCatalogFailure@1780511857491378000#1599` | productCatalogFailure | nemotron-3-ultra | no_answer | timeout | answered |

Totals by status: 14 answered, 5 no_answer, 3 timeout; 0 transport, 0 unavailable. `answered` here means a
parseable final answer, not a correct one.

## Why the run is not at 270

The runner process was gone when I next checked, with exit code 144. I had launched it as a background
shell command with a 600 s tool timeout, which is the likely cause, and that was my mistake; it happened
before the stop order arrived. Cells in flight at that moment were never written, so they are neither
observations nor failures and are simply owed. The stop order then made the question moot.

## Gate results (model-free, complete)

Criterion (`scripts/check_request_ambiguity.py`): median concurrent requests >= 5 AND median services per
erroring trace >= 2, with >= 30 usable edge errors, at W = 2 s.

| input | edge | usable | median concurrent @2s | median services | verdict |
|---|---|---|---|---|---|
| otel_demo, whole capture | frontend | 0 | — | — | INDETERMINATE |
| otel_demo, whole capture | frontend-proxy | 0 | — | — | INDETERMINATE |
| otel_demo, whole capture | all services | 689 | 154.0 | 3.0 | PROCEED |
| otel_demo, 12 multifault windows | frontend | 0 | — | — | INDETERMINATE |
| otel_demo, 12 multifault windows | frontend-proxy | 0 | — | — | INDETERMINATE |
| otel_demo, 12 multifault windows | all services | 259 | 156.0 | 3.0 | **PROCEED** |
| rcalab sc10 (negative control) | all / product-catalog | 760 | 38.0 | 1.0 | STOP |

Caveats that belong to the verdict: the edge services emit no ERROR logs, so seeds are inner-service errors
at the hand-patched fault origins; at W = 0.05 s the windowed median is 4.0 concurrent (STOP) and at 0.25 s
it is 22.0; requests are short (median span 216 ms). Nezha was not cloned: otel_demo passed the gate, so the
brief's condition for the 3.2 GB clone was not met.

Model-free reference, measured before any model call and recorded in the pre-registration: returning every
line within +/-W of the seed reaches F1 >= 0.8 on 0 of 30 seeds at every W tried (0.05 to 1.0 s), and the
exact lines of a request cost a median of 600 cl100k tokens.

## Harness notes for the successor

None of these is a result; they are properties of the harness a successor should decide on in advance.

- **Config was never changed.** Hashes of the harness files at run time matched the pre-registration.
- **`num_ctx` is not a binding constraint on the cloud backend.** The per-cell `max_prompt_tok` recorded in
  the smoke file exceeds the declared 32,768 for two of the three models.
- **The 250,000-token ceiling is reached by cells that read a lot,** which the pre-registration anticipated;
  those cells are `no_answer` failures that keep their observed tokens. Whether a successor wants a different
  ceiling is a pre-registration decision, not something to adjust inside this run.
- **Three cells hit the 300 s wall clock after few completed rounds.** These are recorded as `timeout` with
  their lower-bound tokens, as pre-registered. A successor should state in advance how it distinguishes a
  provider stall from a slow model, since the two are indistinguishable in this log.
- **Analysis-code detail the pre-registration did not spell out:** `forensics_stats.geo_ratio` drops a model
  from the geometric mean when either arm has zero correct answers (the ratio is undefined). That direction is
  conservative against T, but it should be stated explicitly in a successor's pre-registration, and the
  `FALS_replicate` check fires mechanically whenever the main-run ratio for the replicated model is undefined.

## Harness files (all new, nothing existing modified)

- `src/tokentax/forensics.py`: `ForensicsREPL` (adds `lines_near`, data-only overview, trace-prefix
  resolution), the single matched `forensics_tool_schemas()`, case eligibility and stratified sampling,
  scoring, the agent loop with a `Meter` that survives timeouts.
- `src/tokentax/forensics_stats.py`: dedupe, complete triples, tokens-per-correct, exact sign test,
  within-model geometric ratio, cluster bootstrap.
- `scripts/run_request_forensics.py`: runner (`--cases-only`, `--pilot --tag smoke`, resumable).
- `scripts/analyze_request_forensics.py`: the pre-registered paired analysis and decision rule.
- `scripts/check_request_ambiguity_windows.py`: runs the existing gate, unchanged, on manifest windows.
- `tests/test_forensics.py`, `tests/test_forensics_stats.py`: 33 offline tests.

`make test`: 68 passed. `make lint`: all checks passed.
