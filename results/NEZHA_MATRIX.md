# 3-arm matrix on Nezha Train Ticket

Pre-registered in `results/NEZHA_PREREG.md` before the first cell. Raw: `results/runs/nezha_matrix.jsonl`. Harness: `scripts/run_nezha_matrix.py`.

Fixed config: timeout=240s, max_rounds=14, num_ctx=32,768, matched_schemas=True. 336 cells.

`median_tok`/`mean_tok` cover ANSWERED cells only. `fail` is reported separately and is never folded in as a zero. A give-up (`unknown`) is scored as its own outcome and is NOT credited as a correct `none`.

### All cells — 336 cells

| condition | n | acc | gave_up | median_tok | mean_tok | fail | cost_per_correct |
|---|---|---|---|---|---|---|---|
| plain | 112 | 0.02 | 24 | 12,796 | 70,629 | 29 | 2,931,118 |
| structured_no_trace | 112 | 0.04 | 9 | 14,501 | 27,817 | 55 | 396,395 |
| structured | 112 | 0.02 | 16 | 27,519 | 53,794 | 56 | 1,506,240 |

### Fault windows — culprit REACHABLE by trace_id — 168 cells

| condition | n | acc | gave_up | median_tok | mean_tok | fail | cost_per_correct |
|---|---|---|---|---|---|---|---|
| plain | 56 | 0.04 | 11 | 12,116 | 71,823 | 14 | 1,508,277 |
| structured_no_trace | 56 | 0.04 | 7 | 20,572 | 39,640 | 28 | 554,967 |
| structured | 56 | 0.02 | 10 | 36,362 | 68,769 | 28 | 1,925,537 |

### Fault windows — culprit NOT reachable — 120 cells

| condition | n | acc | gave_up | median_tok | mean_tok | fail | cost_per_correct |
|---|---|---|---|---|---|---|---|
| plain | 40 | 0.00 | 8 | 10,514 | 60,176 | 10 | — |
| structured_no_trace | 40 | 0.05 | 0 | 6,353 | 12,218 | 19 | 128,286 |
| structured | 40 | 0.03 | 2 | 20,858 | 32,077 | 20 | 641,537 |

### Normal control windows — 48 cells

| condition | n | acc | gave_up | median_tok | mean_tok | fail | cost_per_correct |
|---|---|---|---|---|---|---|---|
| plain | 16 | 0.00 | 5 | 30,281 | 94,583 | 5 | — |
| structured_no_trace | 16 | 0.00 | 2 | 25,187 | 27,384 | 8 | — |
| structured | 16 | 0.00 | 4 | 63,079 | 55,676 | 8 | — |

## Per model

| model | condition | n | acc | median_tok | fail |
|---|---|---|---|---|---|
| glm-5.2 | plain | 28 | 0.00 | — | 28 |
| glm-5.2 | structured | 28 | 0.00 | — | 28 |
| glm-5.2 | structured_no_trace | 28 | 0.00 | — | 28 |
| gpt-oss:120b | plain | 28 | 0.04 | 5,012 | 0 |
| gpt-oss:120b | structured | 28 | 0.04 | 21,780 | 0 |
| gpt-oss:120b | structured_no_trace | 28 | 0.07 | 12,963 | 0 |
| kimi-k3 | plain | 28 | 0.04 | 147,927 | 1 |
| kimi-k3 | structured | 28 | 0.00 | — | 28 |
| kimi-k3 | structured_no_trace | 28 | 0.00 | 7,254 | 27 |
| qwen3.5:397b | plain | 28 | 0.00 | 18,250 | 0 |
| qwen3.5:397b | structured | 28 | 0.04 | 79,464 | 0 |
| qwen3.5:397b | structured_no_trace | 28 | 0.07 | 24,133 | 0 |

## First tool called

- **plain**: errors_by_cluster=83, (none)=29
- **structured_no_trace**: errors_by_service=57, (none)=55
- **structured**: errors_by_service=56, (none)=56
