# 3-arm matrix on Nezha Train Ticket

Pre-registered in `results/NEZHA_PREREG.md` before the first cell. Raw: `results/runs/nezha_matrix.jsonl`. Harness: `scripts/run_nezha_matrix.py`.

Fixed config: timeout=240s, max_rounds=14, num_ctx=32,768, matched_schemas=True. 9 cells.

`median_tok`/`mean_tok` cover ANSWERED cells only. `fail` is reported separately and is never folded in as a zero. A give-up (`unknown`) is scored as its own outcome and is NOT credited as a correct `none`.

### All cells — 9 cells

| condition | n | acc | gave_up | median_tok | mean_tok | fail | cost_per_correct |
|---|---|---|---|---|---|---|---|
| plain | 3 | 0.00 | 0 | 5,839 | 9,645 | 0 | — |
| structured_no_trace | 3 | 0.00 | 0 | 2,432 | 2,432 | 1 | — |
| structured | 3 | 0.00 | 0 | 4,155 | 4,921 | 0 | — |

### Fault windows — culprit REACHABLE by trace_id — 3 cells

| condition | n | acc | gave_up | median_tok | mean_tok | fail | cost_per_correct |
|---|---|---|---|---|---|---|---|
| plain | 1 | 0.00 | 0 | 20,844 | 20,844 | 0 | — |
| structured_no_trace | 1 | 0.00 | 0 | — | — | 1 | — |
| structured | 1 | 0.00 | 0 | 8,123 | 8,123 | 0 | — |

### Fault windows — culprit NOT reachable — 3 cells

| condition | n | acc | gave_up | median_tok | mean_tok | fail | cost_per_correct |
|---|---|---|---|---|---|---|---|
| plain | 1 | 0.00 | 0 | 2,253 | 2,253 | 0 | — |
| structured_no_trace | 1 | 0.00 | 0 | 2,417 | 2,417 | 0 | — |
| structured | 1 | 0.00 | 0 | 2,485 | 2,485 | 0 | — |

### Normal control windows — 3 cells

| condition | n | acc | gave_up | median_tok | mean_tok | fail | cost_per_correct |
|---|---|---|---|---|---|---|---|
| plain | 1 | 0.00 | 0 | 5,839 | 5,839 | 0 | — |
| structured_no_trace | 1 | 0.00 | 0 | 2,446 | 2,446 | 0 | — |
| structured | 1 | 0.00 | 0 | 4,155 | 4,155 | 0 | — |

## Per model

| model | condition | n | acc | median_tok | fail |
|---|---|---|---|---|---|
| qwen3.5:9b | plain | 3 | 0.00 | 5,839 | 0 |
| qwen3.5:9b | structured | 3 | 0.00 | 4,155 | 0 |
| qwen3.5:9b | structured_no_trace | 3 | 0.00 | 2,432 | 1 |

## First tool called

- **plain**: errors_by_cluster=3
- **structured_no_trace**: errors_by_service=2, (none)=1
- **structured**: errors_by_service=3
