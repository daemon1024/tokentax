# Corrected 3-arm matrix — Ollama Cloud

Matched aggregation power across arms; parallel prompts; one variable per contrast.
Supersedes `MATRIX_RESULTS_V2.md` (see `WITHDRAWAL.md` for why that run does not hold).

Fixed config: timeout=240s, max_rounds=14, num_ctx=32,768. 18 cells.

`mean_tok` covers ANSWERED cells only; `fail` is reported separately and is never folded in as a zero.

| model | condition | n | acc | mean_tok | mean_rounds | fail | cost_per_correct |
|---|---|---|---|---|---|---|---|
| gpt-oss:120b | plain | 3 | 1.00 | 3,429 | 3.3 | 0 | 3,429 |
| gpt-oss:120b | structured | 3 | 1.00 | 2,658 | 3.0 | 0 | 2,658 |
| gpt-oss:120b | structured_no_trace | 3 | 1.00 | 5,263 | 4.0 | 0 | 5,263 |
| qwen3.5:397b | plain | 3 | 1.00 | 68,274 | 6.7 | 0 | 68,274 |
| qwen3.5:397b | structured | 3 | 1.00 | 4,764 | 3.3 | 0 | 4,764 |
| qwen3.5:397b | structured_no_trace | 3 | 1.00 | 3,283 | 3.0 | 0 | 3,283 |

## Pooled across models — the contrast

| condition | n | acc | mean_tok | fail | cost_per_correct |
|---|---|---|---|---|---|
| plain | 6 | 1.00 | 35,851 | 0 | 35,851 |
| structured_no_trace | 6 | 1.00 | 4,273 | 0 | 4,273 |
| structured | 6 | 1.00 | 3,711 | 0 | 3,711 |

## First tool called (what the models actually reach for)

- **plain**: errors_by_cluster=6
- **structured_no_trace**: errors_by_service=6
- **structured**: errors_by_service=6
