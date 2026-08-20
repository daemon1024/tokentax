# Corrected 3-arm matrix — Ollama Cloud

Matched aggregation power across arms; parallel prompts; one variable per contrast.
Supersedes `MATRIX_RESULTS_V2.md` (see `WITHDRAWAL.md` for why that run does not hold).

Fixed config: timeout=240s, max_rounds=14, num_ctx=32,768. 288 cells.

`mean_tok` covers ANSWERED cells only; `fail` is reported separately and is never folded in as a zero.

| model | condition | n | acc | mean_tok | mean_rounds | fail | cost_per_correct |
|---|---|---|---|---|---|---|---|
| deepseek-v4-pro:0813 | plain | 12 | 1.00 | 28,940 | 5.1 | 0 | 28,940 |
| deepseek-v4-pro:0813 | structured | 12 | 1.00 | 17,921 | 5.7 | 0 | 17,921 |
| deepseek-v4-pro:0813 | structured_no_trace | 12 | 1.00 | 21,379 | 4.4 | 0 | 21,379 |
| gemma4:31b | plain | 12 | 1.00 | 47,653 | 6.9 | 0 | 47,653 |
| gemma4:31b | structured | 12 | 1.00 | 49,741 | 5.1 | 0 | 49,741 |
| gemma4:31b | structured_no_trace | 12 | 1.00 | 47,061 | 5.1 | 0 | 47,061 |
| glm-5.2 | plain | 12 | 1.00 | 36,379 | 4.8 | 0 | 36,379 |
| glm-5.2 | structured | 12 | 1.00 | 38,024 | 4.8 | 0 | 38,024 |
| glm-5.2 | structured_no_trace | 12 | 1.00 | 15,953 | 4.4 | 0 | 15,953 |
| gpt-oss:120b | plain | 12 | 1.00 | 2,862 | 2.9 | 0 | 2,862 |
| gpt-oss:120b | structured | 12 | 1.00 | 1,866 | 2.5 | 0 | 1,866 |
| gpt-oss:120b | structured_no_trace | 12 | 1.00 | 5,020 | 3.8 | 0 | 5,020 |
| kimi-k3 | plain | 12 | 0.83 | 55,026 | 6.8 | 0 | 66,031 |
| kimi-k3 | structured | 12 | 1.00 | 37,470 | 5.5 | 0 | 37,470 |
| kimi-k3 | structured_no_trace | 12 | 1.00 | 8,035 | 4.0 | 0 | 8,035 |
| mistral-large-3:675b | plain | 12 | 0.92 | 1,081 | 2.0 | 0 | 1,180 |
| mistral-large-3:675b | structured | 12 | 1.00 | 5,125 | 3.2 | 0 | 5,125 |
| mistral-large-3:675b | structured_no_trace | 12 | 0.92 | 16,740 | 3.4 | 0 | 18,262 |
| nemotron-3-super | plain | 12 | 1.00 | 15,148 | 4.5 | 0 | 15,148 |
| nemotron-3-super | structured | 12 | 1.00 | 4,018 | 2.6 | 0 | 4,018 |
| nemotron-3-super | structured_no_trace | 12 | 0.92 | 3,749 | 2.8 | 0 | 4,090 |
| qwen3.5:397b | plain | 12 | 0.83 | 45,480 | 6.0 | 0 | 54,576 |
| qwen3.5:397b | structured | 12 | 1.00 | 4,366 | 3.1 | 0 | 4,366 |
| qwen3.5:397b | structured_no_trace | 12 | 1.00 | 3,288 | 2.9 | 0 | 3,288 |

## Pooled across models — the contrast

| condition | n | acc | mean_tok | fail | cost_per_correct |
|---|---|---|---|---|---|
| plain | 96 | 0.95 | 29,071 | 0 | 30,668 |
| structured_no_trace | 96 | 0.98 | 15,153 | 0 | 15,476 |
| structured | 96 | 1.00 | 19,816 | 0 | 19,816 |

## First tool called (what the models actually reach for)

- **plain**: errors_by_cluster=94, errors_by_cluster
</parameter=1, overview=1
- **structured_no_trace**: errors_by_service=96
- **structured**: errors_by_service=96
