# Corrected cross-model matrix (tool-RLM vs recursive-RLM)

192/192 cells. 4 tool-capable models x 12 multifault OTel windows x 2 methods x 2 conditions. Fixed code: plain truly plain; structured has svc/sev/trace tags + the errors_by_service digest. Cell = accuracy, mean tokens, mean sub-calls, abort%.

| model | method | cond | n | acc | mean_tok | mean_sub | abort% |
|---|---|---|---|---|---|---|---|
| gemma4:e4b | recursive | plain | 12 | 0.25 | 1,125 | 0.0 | 50% |
| gemma4:e4b | recursive | structured | 12 | 0.92 | 2,651 | 0.0 | 0% |
| gemma4:e4b | tool | plain | 12 | 0.50 | 4,916 | 0.0 | 8% |
| gemma4:e4b | tool | structured | 12 | 0.92 | 2,072 | 0.0 | 0% |
| gpt-oss:20b | recursive | plain | 12 | 0.25 | 1,098 | 0.0 | 75% |
| gpt-oss:20b | recursive | structured | 12 | 0.83 | 2,856 | 0.0 | 8% |
| gpt-oss:20b | tool | plain | 12 | 0.17 | 4,668 | 0.0 | 75% |
| gpt-oss:20b | tool | structured | 12 | 0.92 | 6,079 | 0.0 | 0% |
| qwen3.5:9b | recursive | plain | 12 | 0.50 | 10,391 | 0.0 | 16% |
| qwen3.5:9b | recursive | structured | 12 | 0.92 | 2,175 | 0.0 | 0% |
| qwen3.5:9b | tool | plain | 12 | 0.42 | 56,362 | 0.0 | 50% |
| qwen3.5:9b | tool | structured | 12 | 0.92 | 1,844 | 0.0 | 0% |
| qwen3:8b | recursive | plain | 12 | 0.58 | 8,788 | 1.2 | 8% |
| qwen3:8b | recursive | structured | 12 | 0.92 | 1,691 | 0.0 | 0% |
| qwen3:8b | tool | plain | 12 | 0.17 | 10,670 | 0.0 | 0% |
| qwen3:8b | tool | structured | 12 | 0.75 | 1,405 | 0.0 | 0% |
