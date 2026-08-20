# Corrected 3-arm matrix — analysis

288 cells, 0 failed. Bootstrap: 10,000 resamples, seed 20260820, 95% CI on the MEDIAN.

## Token cost by arm (answered cells)

| condition | n | acc | mean | median | p90 | max | median 95% CI |
|---|---|---|---|---|---|---|---|
| plain | 96 | 0.95 | 29,072 | 5,328 | 120,345 | 286,925 | [3,738, 6,599] |
| structured_no_trace | 96 | 0.98 | 15,154 | 3,266 | 26,548 | 289,411 | [3,012, 3,640] |
| structured | 96 | 1.00 | 19,817 | 3,698 | 17,008 | 281,891 | [3,186, 4,425] |

## Paired contrasts — same model, same window

Positive `median Δ` means the SECOND arm is cheaper. Ratio is median(b)/median(a) over pairs where both arms answered.

| contrast | pairs | median Δ tok | 95% CI on median Δ | median ratio | acc a → b |
|---|---|---|---|---|---|
| plain → structured_no_trace | 96 | 1,092 | [21, 2,916] (excludes 0) | 0.77× | 91/96 → 94/96 |
| structured_no_trace → structured | 96 | -514 | [-654, -374] (excludes 0) | 1.20× | 94/96 → 96/96 |
| plain → structured | 96 | -194 | [-478, 905] (crosses 0) | 1.07× | 91/96 → 96/96 |

## Paired accuracy contrasts

| contrast | acc a → b | paired Δ | 95% CI | verdict |
|---|---|---|---|---|
| plain → structured_no_trace | 0.948 → 0.979 | +0.031 | [-0.021, +0.083] | crosses 0 |
| structured_no_trace → structured | 0.979 → 1.000 | +0.021 | [+0.000, +0.052] | crosses 0 |
| plain → structured | 0.948 → 1.000 | +0.052 | [+0.010, +0.104] | excludes 0 |

## Misses

- **plain** (5):
    - qwen3.5:397b · truth=cart · pred='unknown' · 99,256 tok
    - qwen3.5:397b · truth=ad · pred='unknown' · 200,720 tok
    - kimi-k3 · truth=product-catalog · pred='unknown' · 133,030 tok
    - kimi-k3 · truth=product-catalog · pred='unknown' · 56,537 tok
    - mistral-large-3:675b · truth=none · pred='otel-collector' · 1,183 tok
- **structured_no_trace** (2):
    - mistral-large-3:675b · truth=product-catalog · pred='recommendation' · 48,024 tok
    - nemotron-3-super · truth=none · pred='otelcol-contrib' · 1,624 tok
- **structured**: none

## Per-model median tokens (is the direction consistent?)

| model | plain | structured_no_trace | structured | plain→struct |
|---|---|---|---|---|
| deepseek-v4-pro:0813 | 8,112 | 4,892 | 8,868 | 1.09× MORE EXPENSIVE |
| gemma4:31b | 9,705 | 3,264 | 3,520 | 0.36× cheaper |
| glm-5.2 | 5,569 | 3,048 | 3,565 | 0.64× cheaper |
| gpt-oss:120b | 2,290 | 3,586 | 1,352 | 0.59× cheaper |
| kimi-k3 | 11,500 | 3,054 | 4,666 | 0.41× cheaper |
| mistral-large-3:675b | 1,088 | 11,768 | 3,110 | 2.86× MORE EXPENSIVE |
| nemotron-3-super | 4,026 | 1,622 | 2,080 | 0.52× cheaper |
| qwen3.5:397b | 4,718 | 3,168 | 3,888 | 0.82× cheaper |

## Failures

None — every cell answered.

## First tool called

- **plain**: errors_by_cluster=94, errors_by_cluster
</parameter=1, overview=1
- **structured_no_trace**: errors_by_service=96
- **structured**: errors_by_service=96
