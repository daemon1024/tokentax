# Cross-model RLM matrix (autonomous run)

Live results, 24 cells so far. Local Ollama, 12 multifault OTel windows (3 normal + 3 each product-catalog/cart/ad), RLM navigation, root-cause task.

## RLM: accuracy, mean tokens, abort rate by (model, condition)

| model | cond | n | acc | mean_tok | mean_rounds | abort% |
|---|---|---|---|---|---|---|
| qwen3:8b | plain | 12 | 0.50 | 17,558 | 4.6 | 8% |
| qwen3:8b | structured | 12 | 1.00 | 3,861 | 2.8 | 0% |
