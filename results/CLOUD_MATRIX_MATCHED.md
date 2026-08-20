# Corrected 3-arm matrix — Ollama Cloud

Matched aggregation power across arms; parallel prompts; one variable per contrast.
Supersedes `MATRIX_RESULTS_V2.md` (see `WITHDRAWAL.md` for why that run does not hold).

Fixed config: timeout=240s, max_rounds=14, num_ctx=32,768. 144 cells.

`mean_tok` covers ANSWERED cells only; `fail` is reported separately and is never folded in as a zero.

| model | condition | n | acc | mean_tok | mean_rounds | fail | cost_per_correct |
|---|---|---|---|---|---|---|---|
| glm-5.2 | plain | 12 | 0.83 | 60,190 | 7.1 | 0 | 72,229 |
| glm-5.2 | structured | 12 | 1.00 | 25,578 | 4.2 | 0 | 25,578 |
| glm-5.2 | structured_no_trace | 12 | 1.00 | 3,338 | 3.2 | 0 | 3,338 |
| gpt-oss:120b | plain | 12 | 1.00 | 10,995 | 3.8 | 0 | 10,995 |
| gpt-oss:120b | structured | 12 | 0.92 | 6,495 | 2.9 | 1 | 6,495 |
| gpt-oss:120b | structured_no_trace | 12 | 0.92 | 2,098 | 2.8 | 0 | 2,289 |
| kimi-k3 | plain | 12 | 0.75 | 57,347 | 8.2 | 0 | 76,463 |
| kimi-k3 | structured | 12 | 1.00 | 20,090 | 4.9 | 0 | 20,090 |
| kimi-k3 | structured_no_trace | 12 | 1.00 | 24,284 | 4.3 | 0 | 24,284 |
| qwen3.5:397b | plain | 12 | 0.58 | 106,474 | 9.0 | 0 | 182,527 |
| qwen3.5:397b | structured | 12 | 1.00 | 4,434 | 3.2 | 0 | 4,434 |
| qwen3.5:397b | structured_no_trace | 12 | 1.00 | 3,625 | 2.9 | 0 | 3,625 |

## Pooled across models — the contrast

| condition | n | acc | mean_tok | fail | cost_per_correct |
|---|---|---|---|---|---|
| plain | 48 | 0.79 | 58,752 | 0 | 74,213 |
| structured_no_trace | 48 | 0.98 | 8,336 | 0 | 8,514 |
| structured | 48 | 0.98 | 14,312 | 1 | 14,312 |

## First tool called (what the models actually reach for)

- **plain**: errors_by_cluster=48
- **structured_no_trace**: errors_by_service=48
- **structured**: errors_by_service=47, (none)=1
