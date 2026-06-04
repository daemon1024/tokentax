# Cross-model RLM matrix (autonomous run)

Live results, 15 cells so far. Local Ollama, 12 multifault OTel windows (3 normal + 3 each product-catalog/cart/ad), RLM navigation, root-cause task.

## RLM: accuracy, mean tokens, abort rate by (model, condition)

| model | cond | n | acc | mean_tok | mean_rounds | abort% |
|---|---|---|---|---|---|---|
| qwen3:8b | plain | 8 | 0.50 | 18,881 | 4.6 | 12% |
| qwen3:8b | structured | 7 | 1.00 | 3,376 | 2.9 | 0% |
