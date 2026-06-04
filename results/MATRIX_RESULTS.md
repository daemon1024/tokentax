# Cross-model RLM matrix (autonomous run)

Live results, 72 cells so far. Local Ollama, 12 multifault OTel windows (3 normal + 3 each product-catalog/cart/ad), RLM navigation, root-cause task.

## RLM: accuracy, mean tokens, abort rate by (model, condition)

| model | cond | n | acc | mean_tok | mean_rounds | abort% |
|---|---|---|---|---|---|---|
| gpt-oss:20b | plain | 12 | 0.92 | 41,671 | 7.9 | 16% |
| gpt-oss:20b | structured | 12 | 1.00 | 12,066 | 5.4 | 0% |
| qwen3.5:9b | plain | 12 | 0.50 | 83,312 | 11.1 | 75% |
| qwen3.5:9b | structured | 12 | 0.92 | 22,605 | 6.3 | 8% |
| qwen3:8b | plain | 12 | 0.50 | 17,558 | 4.6 | 8% |
| qwen3:8b | structured | 12 | 1.00 | 3,861 | 2.8 | 0% |
