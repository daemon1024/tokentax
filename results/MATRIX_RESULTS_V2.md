# Corrected cross-model matrix (tool-RLM vs recursive-RLM)

48/192 cells. 4 tool-capable models x 12 multifault OTel windows x 2 methods x 2 conditions. Fixed code: plain truly plain; structured has svc/sev/trace tags + the errors_by_service digest. Cell = accuracy, mean tokens, mean sub-calls, abort%.

| model | method | cond | n | acc | mean_tok | mean_sub | abort% |
|---|---|---|---|---|---|---|---|
| qwen3:8b | recursive | plain | 12 | 0.58 | 8,788 | 1.2 | 8% |
| qwen3:8b | recursive | structured | 12 | 0.92 | 1,691 | 0.0 | 0% |
| qwen3:8b | tool | plain | 12 | 0.17 | 10,670 | 0.0 | 0% |
| qwen3:8b | tool | structured | 12 | 0.75 | 1,405 | 0.0 | 0% |
