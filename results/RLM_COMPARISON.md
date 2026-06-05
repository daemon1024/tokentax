# tool-RLM vs recursive-RLM — cross-model, structured vs unstructured

One productCatalogFailure window (capped ~200 records / ~40k tokens), root-cause task, local Ollama. Cell = total tokens + correct(✓)/wrong(✗)/error(ERR); recursive also shows sub-call count and max single root-prompt (the offloaded-context signature). truth=product-catalog.

| model | tool plain | tool struct | recursive plain | recursive struct |
|---|---|---|---|---|
| qwen3:8b | 5,336 ✓ | 3,216 ✓ | 6,435 ✓ (sub=1,maxRoot=873) | 2,207 ✓ (sub=0,maxRoot=831) |
| qwen3.5:9b | 40,706 ✓ | 7,000 ✓ | 2,825 ✓ (sub=0,maxRoot=1,040) | 2,840 ✓ (sub=0,maxRoot=1,045) |
| gpt-oss:20b | 5,427 ✓ | 5,271 ✓ | 1,274 ✓ (sub=0,maxRoot=631) | 1,307 ✓ (sub=0,maxRoot=634) |
| gemma4:e4b | 7,191 ✓ | 6,221 ✓ | 1,315 ✓ (sub=0,maxRoot=669) | 1,338 ✓ (sub=0,maxRoot=679) |

## Recursive RLM — root context stays tiny (max single root-prompt, tokens)

| model | plain maxRoot | struct maxRoot | plain sub-calls | struct sub-calls |
|---|---|---|---|---|
| qwen3:8b | 873 | 831 | 1 | 0 |
| qwen3.5:9b | 1,040 | 1,045 | 0 | 0 |
| gpt-oss:20b | 631 | 634 | 0 | 0 |
| gemma4:e4b | 669 | 679 | 0 | 0 |

## Summary

- **tool / plain**: acc 1.00, mean 14,665 tok (n=4)
- **tool / structured**: acc 1.00, mean 5,427 tok (n=4)
- **recursive / plain**: acc 1.00, mean 2,962 tok (n=4)
- **recursive / structured**: acc 1.00, mean 1,923 tok (n=4)

## Findings

1. **All 16 cells correct** (recoverable task) — accuracy doesn't separate methods/models here; the signal is TOKENS and the root-context ceiling.
2. **Recursive RLM is cheaper than our tool-RLM on average** (plain 2,962 vs 14,665; structured 1,923 vs 5,427). The gap is biggest where tool-RLM flails: qwen3.5:9b plain tool=40,706 vs recursive=2,825 (~14x). tool-RLM *accumulates* grep results in a growing root transcript re-sent each round; the recursive root stays disciplined and small.
3. **The root-context ceiling is tiny and ~constant across models** (maxRoot 631–1,045 tokens) regardless of window size — the offloaded-context signature, now shown for all 4 model families, not just qwen3:8b.
4. **Structure helps both methods** (tool 14.7k→5.4k; recursive 3.0k→1.9k).
5. **Honest nuance: recursion was rarely *invoked*** — 7/8 recursive cells did 0 sub-LM calls (only qwen3:8b-plain made 1). For this sparse, grep-localizable signal the root solved it by examining (overview+grep) without dispatching sub-LMs. So this run mainly demonstrates the *offloaded-context discipline* (tiny root), not the sub-LM recursion itself — which only pays off when the relevant region is too big to examine directly.

_Caveat: single window (~40k tok, 200 records, productCatalog fault), local Ollama, one run per cell — directional, not error-barred._
