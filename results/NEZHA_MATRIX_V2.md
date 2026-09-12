# 3-arm matrix on Nezha Train Ticket

Pre-registered in `results/NEZHA_PREREG.md` before the first cell. Raw: `results/runs/nezha_matrix.jsonl`. Harness: `scripts/run_nezha_matrix.py`.

Fixed config: timeout=240s, max_rounds=14, num_ctx=32,768, matched_schemas=True. 756 cells.

`median_tok`/`mean_tok` cover ANSWERED cells only. `fail` is reported separately and is never folded in as a zero. A give-up (`unknown`) is scored as its own outcome and is NOT credited as a correct `none`.

### All cells — 756 cells

| condition | n | acc | gave_up | median_tok | mean_tok | fail | cost_per_correct |
|---|---|---|---|---|---|---|---|
| plain | 252 | 0.04 | 27 | 14,720 | 49,768 | 68 | 915,736 |
| structured_no_trace | 252 | 0.07 | 22 | 19,168 | 43,881 | 74 | 459,457 |
| structured | 252 | 0.06 | 26 | 27,328 | 56,236 | 84 | 629,845 |

### Fault windows — culprit REACHABLE by trace_id — 378 cells

| condition | n | acc | gave_up | median_tok | mean_tok | fail | cost_per_correct |
|---|---|---|---|---|---|---|---|
| plain | 126 | 0.06 | 14 | 19,665 | 57,541 | 33 | 668,917 |
| structured_no_trace | 126 | 0.08 | 13 | 28,748 | 55,376 | 38 | 487,310 |
| structured | 126 | 0.06 | 12 | 31,498 | 67,111 | 42 | 805,337 |

### Fault windows — culprit NOT reachable — 270 cells

| condition | n | acc | gave_up | median_tok | mean_tok | fail | cost_per_correct |
|---|---|---|---|---|---|---|---|
| plain | 90 | 0.02 | 8 | 10,831 | 31,369 | 25 | 1,019,498 |
| structured_no_trace | 90 | 0.08 | 3 | 14,150 | 23,608 | 23 | 225,967 |
| structured | 90 | 0.09 | 7 | 17,606 | 29,894 | 27 | 235,415 |

### Normal control windows — 108 cells

| condition | n | acc | gave_up | median_tok | mean_tok | fail | cost_per_correct |
|---|---|---|---|---|---|---|---|
| plain | 36 | 0.00 | 5 | 19,499 | 67,963 | 10 | — |
| structured_no_trace | 36 | 0.00 | 6 | 18,953 | 58,952 | 13 | — |
| structured | 36 | 0.00 | 7 | 52,987 | 91,761 | 15 | — |

## Per model

| model | condition | n | acc | median_tok | fail |
|---|---|---|---|---|---|
| deepseek-v4.1-flash | plain | 28 | 0.04 | 36,770 | 0 |
| deepseek-v4.1-flash | structured | 28 | 0.07 | 45,873 | 0 |
| deepseek-v4.1-flash | structured_no_trace | 28 | 0.11 | 38,628 | 0 |
| glm-5.3 | plain | 28 | 0.00 | — | 28 |
| glm-5.3 | structured | 28 | 0.04 | 254,691 | 25 |
| glm-5.3 | structured_no_trace | 28 | 0.00 | — | 28 |
| gpt-oss:120b | plain | 28 | 0.07 | 10,368 | 0 |
| gpt-oss:120b | structured | 28 | 0.11 | 29,044 | 0 |
| gpt-oss:120b | structured_no_trace | 28 | 0.07 | 16,763 | 0 |
| gpt-oss:20b | plain | 28 | 0.07 | 8,886 | 8 |
| gpt-oss:20b | structured | 28 | 0.04 | 19,258 | 18 |
| gpt-oss:20b | structured_no_trace | 28 | 0.11 | 19,281 | 12 |
| minimax-m3 | plain | 28 | 0.07 | 35,614 | 0 |
| minimax-m3 | structured | 28 | 0.11 | 38,024 | 0 |
| minimax-m3 | structured_no_trace | 28 | 0.07 | 25,328 | 0 |
| nemotron-3-ultra | plain | 28 | 0.00 | — | 28 |
| nemotron-3-ultra | structured | 28 | 0.00 | — | 28 |
| nemotron-3-ultra | structured_no_trace | 28 | 0.00 | 1,262 | 27 |
| qwen3.5:397b | plain | 28 | 0.04 | 82,886 | 3 |
| qwen3.5:397b | structured | 28 | 0.07 | 68,820 | 0 |
| qwen3.5:397b | structured_no_trace | 28 | 0.11 | 62,438 | 3 |
| qwen3.5:9b | plain | 28 | 0.00 | 6,582 | 0 |
| qwen3.5:9b | structured | 28 | 0.07 | 4,200 | 6 |
| qwen3.5:9b | structured_no_trace | 28 | 0.11 | 2,447 | 1 |
| qwen3:14b | plain | 28 | 0.07 | 10,824 | 1 |
| qwen3:14b | structured | 28 | 0.04 | 20,028 | 7 |
| qwen3:14b | structured_no_trace | 28 | 0.04 | 18,953 | 3 |

## First tool called

- **plain**: errors_by_cluster=182, (none)=68, overview=1, errors_by_service=1
- **structured_no_trace**: errors_by_service=176, (none)=75, overview=1
- **structured**: errors_by_service=168, (none)=84
