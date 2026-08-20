> [!CAUTION]
> **CORRECTION (2026-08-20): the headline of this document does not hold.**
>
> The structured arm's advantage below is produced by `errors_by_service()` (`src/tokentax/methods/repl.py:97`),
> a ranked per-service ERROR-count digest exposed **only** to the structured arm. It never reads `trace_id`,
> so it does not test trace-aware navigation.
>
> Running `argmax()` over that digest with **no model in the loop** scores **11/12** on these same windows —
> equal to the best structured cells reported here. In all 9 anomalous windows the culprit service is the
> *only* service emitting errors, because `infra/otel-demo/` patches a `logger.error` into the fault-origin
> service and `scripts/run_matrix_v2.py:34` maps the fault flag to that same service. The digest therefore
> re-expresses the labelling function rather than exploiting log structure.
>
> Two further defects affect the plain arm specifically:
> * **Outcome-dependent stopping.** `d39a652` reduced the per-cell timeout 240s → ~150s mid-run for the two
>   models whose *plain* cells were failing. gemma4's slowest successful cell is 147.6s. The resulting
>   timeouts were then reported as the finding "plain is INFEASIBLE".
> * **Censored cost.** 30 of 31 timeouts are plain cells, recorded at `total_tok=0`. Token means over plain
>   are therefore censored, not measured — and `MATRIX_NOTES.md` (answered cells only) and
>   `MATRIX_RESULTS_V2.md` (all 12) disagree in *sign* for 3 of 8 model-method pairs.
>
> The numbers below are left unedited as a record of what was run. **Do not cite them.**
> See `WITHDRAWAL.md`.

# Corrected cross-model matrix (tool-RLM vs recursive-RLM)

192/192 cells. 4 tool-capable models x 12 multifault OTel windows x 2 methods x 2 conditions. Fixed code: plain truly plain; structured has svc/sev/trace tags + the errors_by_service digest. Cell = accuracy, mean tokens, mean sub-calls, abort%.

| model | method | cond | n | acc | mean_tok | mean_sub | abort% |
|---|---|---|---|---|---|---|---|
| gemma4:e4b | recursive | plain | 12 | 0.25 | 1,125 | 0.0 | 50% |
| gemma4:e4b | recursive | structured | 12 | 0.92 | 2,651 | 0.0 | 0% |
| gemma4:e4b | tool | plain | 12 | 0.50 | 4,916 | 0.0 | 8% |
| gemma4:e4b | tool | structured | 12 | 0.92 | 2,072 | 0.0 | 0% |
| gpt-oss:20b | recursive | plain | 12 | 0.25 | 1,098 | 0.0 | 75% |
| gpt-oss:20b | recursive | structured | 12 | 0.83 | 2,856 | 0.0 | 8% |
| gpt-oss:20b | tool | plain | 12 | 0.17 | 4,668 | 0.0 | 75% |
| gpt-oss:20b | tool | structured | 12 | 0.92 | 6,079 | 0.0 | 0% |
| qwen3.5:9b | recursive | plain | 12 | 0.50 | 10,391 | 0.0 | 16% |
| qwen3.5:9b | recursive | structured | 12 | 0.92 | 2,175 | 0.0 | 0% |
| qwen3.5:9b | tool | plain | 12 | 0.42 | 56,362 | 0.0 | 50% |
| qwen3.5:9b | tool | structured | 12 | 0.92 | 1,844 | 0.0 | 0% |
| qwen3:8b | recursive | plain | 12 | 0.58 | 8,788 | 1.2 | 8% |
| qwen3:8b | recursive | structured | 12 | 0.92 | 1,691 | 0.0 | 0% |
| qwen3:8b | tool | plain | 12 | 0.17 | 10,670 | 0.0 | 0% |
| qwen3:8b | tool | structured | 12 | 0.75 | 1,405 | 0.0 | 0% |
