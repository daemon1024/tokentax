> [!CAUTION]
> **SUPERSEDED AND WITHDRAWN (2026-08-20).** This is the pre-fix ("leaky") 120-cell run.
>
> At the time these cells ran, `LogREPL` emitted the same tagged lines in both conditions, so the
> **"plain" arm still leaked `service.name`** into every grep result — the condition contrast is invalid.
> That leak was found and fixed in `bc1db3d`. The header below ("Live results, 120 cells so far") is
> stale; the run finished at 120/120 and was then superseded twice.
>
> The successor run (`MATRIX_RESULTS_V2.md`) fixes the leak but introduces a **different** fatal
> confound — a structured-only `errors_by_service()` digest that reproduces the labelling function.
> Neither run supports the structure-is-cheaper claim. **Do not cite either.** See `WITHDRAWAL.md`.

# Cross-model RLM matrix (autonomous run)

Live results, 120 cells so far. Local Ollama, 12 multifault OTel windows (3 normal + 3 each product-catalog/cart/ad), RLM navigation, root-cause task.

## RLM: accuracy, mean tokens, abort rate by (model, condition)

| model | cond | n | acc | mean_tok | mean_rounds | abort% |
|---|---|---|---|---|---|---|
| deepseek-v2:16b | plain | 12 | 0.00 | 0 | 0.0 | 100% |
| deepseek-v2:16b | structured | 12 | 0.00 | 0 | 0.0 | 100% |
| gemma4:e4b | plain | 12 | 0.92 | 9,515 | 4.5 | 8% |
| gemma4:e4b | structured | 12 | 1.00 | 5,907 | 3.5 | 0% |
| gpt-oss:20b | plain | 12 | 0.92 | 41,671 | 7.9 | 16% |
| gpt-oss:20b | structured | 12 | 1.00 | 12,066 | 5.4 | 0% |
| qwen3.5:9b | plain | 12 | 0.50 | 83,312 | 11.1 | 75% |
| qwen3.5:9b | structured | 12 | 0.92 | 22,605 | 6.3 | 8% |
| qwen3:8b | plain | 12 | 0.50 | 17,558 | 4.6 | 8% |
| qwen3:8b | structured | 12 | 1.00 | 3,861 | 2.8 | 0% |
