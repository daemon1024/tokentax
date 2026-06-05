# tool-RLM vs recursive-RLM — cross-model, structured vs unstructured

One productCatalogFailure window (capped ~200 records / ~40k tokens), root-cause task, local Ollama. Cell = total tokens + correct(✓)/wrong(✗)/error(ERR); recursive also shows sub-call count and max single root-prompt (the offloaded-context signature). truth=product-catalog.

| model | tool plain | tool struct | recursive plain | recursive struct |
|---|---|---|---|---|
| qwen3:8b | 5,097 ✓ | 1,383 ✓ | 19,499 ✓ (sub=1,maxRoot=850) | 1,670 ✓ (sub=0,maxRoot=843) |
| qwen3.5:9b | 16,600 ✗ | 1,823 ✓ | 2,976 ✓ (sub=0,maxRoot=1,087) | 2,154 ✓ (sub=0,maxRoot=1,085) |
| gpt-oss:20b | 30,806 ✓ | 6,511 ✓ | 6,418 ✓ (sub=1,maxRoot=702) | 2,488 ✓ (sub=0,maxRoot=835) |
| gemma4:e4b | 5,478 ✗ | 1,303 ✓ | 6,745 ✓ (sub=1,maxRoot=873) | 1,634 ✓ (sub=0,maxRoot=825) |

## Recursive RLM — root context stays tiny (max single root-prompt, tokens)

| model | plain maxRoot | struct maxRoot | plain sub-calls | struct sub-calls |
|---|---|---|---|---|
| qwen3:8b | 850 | 843 | 1 | 0 |
| qwen3.5:9b | 1,087 | 1,085 | 0 | 0 |
| gpt-oss:20b | 702 | 835 | 1 | 0 |
| gemma4:e4b | 873 | 825 | 1 | 0 |

## Summary

- **tool / plain**: acc 0.50, mean 14,495 tok (n=4)
- **tool / structured**: acc 1.00, mean 2,755 tok (n=4)
- **recursive / plain**: acc 1.00, mean 8,909 tok (n=4)
- **recursive / structured**: acc 1.00, mean 1,986 tok (n=4)

## Findings — thesis confirmed once the RLM can EXPLOIT structure

Two fixes vs the first run: (a) `LogREPL` lines are now condition-aware (plain = bare body; structured = svc/sev/trace tags) so 'plain' is genuinely plain; (b) a structured-only `errors_by_service()` tool returns a tiny per-service ERROR-count digest — computable ONLY because structured logs carry `service.name`. That digest is the actual 'free input compression' the thesis is about; grepping verbose lines was not exploiting structure.

1. **Structure = free input compression for the navigator — confirmed.** Structured cells call errors_by_service() once → ~10-token digest ('product-catalog=2') → answer, 0 sub-calls. Means: **structured ~2–2.8k vs plain ~8.9–14.5k** — ~5–7x cheaper. Plain can't aggregate by service (no field) → must read + infer.
2. **recursive + structured is the cheapest AND correct cell (mean 1,986 tok, 4/4)** — what the thesis predicts. recursive-struct (1,986) < tool-struct (2,755); both ≪ their plain.
3. **Plain is genuinely hard.** tool-RLM plain = **2/4** — qwen3.5:9b & gemma4:e4b answer `recommendation`, the service that errors because it *calls* the failing product-catalog (symptom, not cause); no service field to disambiguate. recursive plain is more robust (4/4) but expensive (must read+infer; 8.9k mean).
4. **The earlier 'anti-thesis' result was a missing tool, not a refutation.** With only verbose grep, the RLM had no way to use structure, so structured wasn't cheaper. The structure's value shows up exactly when the navigator can compute a compact, field-derived digest in the environment (the RLM/REPL idea) instead of reading raw lines.
5. qwen3:8b recursive-plain is the cost outlier (~19.5k — over-navigates); structured fixes it (1.7k). Most recursive cells used 0 sub-LM calls (signal is digest-localizable).

_Caveat: single window (~40k tok, 200 records, productCatalog fault, only product-catalog errors present), local Ollama, one run/cell — directional. Prior runs kept at results/runs/rlm_compare_leaky*.jsonl._
