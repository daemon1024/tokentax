# tool-RLM vs recursive-RLM — cross-model, structured vs unstructured

One productCatalogFailure window (capped ~200 records / ~40k tokens), root-cause task, local Ollama. Cell = total tokens + correct(✓)/wrong(✗)/error(ERR); recursive also shows sub-call count and max single root-prompt (the offloaded-context signature). truth=product-catalog.

| model | tool plain | tool struct | recursive plain | recursive struct |
|---|---|---|---|---|
| qwen3:8b | 5,097 ✓ | 3,361 ✓ | 19,499 ✓ (sub=1,maxRoot=850) | 19,715 ✓ (sub=2,maxRoot=3,338) |
| qwen3.5:9b | 16,600 ✗ | 7,362 ✓ | 2,976 ✓ (sub=0,maxRoot=1,087) | 5,699 ✓ (sub=0,maxRoot=3,450) |
| gpt-oss:20b | 30,806 ✓ | 5,480 ✓ | 6,418 ✓ (sub=1,maxRoot=702) | 6,010 ✓ (sub=0,maxRoot=2,634) |
| gemma4:e4b | 5,478 ✗ | 6,676 ✓ | 6,745 ✓ (sub=1,maxRoot=873) | 7,158 ✓ (sub=0,maxRoot=3,281) |

## Recursive RLM — root context stays tiny (max single root-prompt, tokens)

| model | plain maxRoot | struct maxRoot | plain sub-calls | struct sub-calls |
|---|---|---|---|---|
| qwen3:8b | 850 | 3,338 | 1 | 2 |
| qwen3.5:9b | 1,087 | 3,450 | 0 | 0 |
| gpt-oss:20b | 702 | 2,634 | 1 | 0 |
| gemma4:e4b | 873 | 3,281 | 1 | 0 |

## Summary

- **tool / plain**: acc 0.50, mean 14,495 tok (n=4)
- **tool / structured**: acc 1.00, mean 5,719 tok (n=4)
- **recursive / plain**: acc 1.00, mean 8,909 tok (n=4)
- **recursive / structured**: acc 1.00, mean 9,645 tok (n=4)

## Findings (corrected — true-plain navigation)

Methodology fix vs the earlier run: `LogREPL` used to prepend `svc=`/severity to EVERY grep line regardless of condition, so the RLM's 'plain' secretly contained the service name. Now plain lines are the bare message body; structured lines expose svc=/sev=/trace= tags + the trace tools. This makes plain genuinely require inferring the culprit.

1. **Structure's real benefit is correct ATTRIBUTION, not token savings.** On true-plain, tool-RLM is only **2/4 correct** — qwen3.5:9b and gemma4:e4b answer `recommendation`, a service that errors *because it calls* the failing product-catalog (symptom, not cause). The explicit `svc=` field (structured) fixes attribution → **4/4**. The earlier 'structure = cheaper navigation' was largely the leak.
2. **Token effect is now method-dependent, not a clean win.** tool-RLM: structure cheaper (plain 14.5k → struct 5.7k) because true-plain makes it flail (no svc to grep → many rounds; gpt-oss 30.8k, qwen3.5 16.6k). recursive: structure slightly *costlier* (plain 8.9k → struct 9.6k) because svc=/sev= tags make grep lines longer (maxRoot 700–1,090 plain vs 2,600–3,450 structured).
3. **Recursive RLM is more ROBUST on plain** — 4/4 vs tool-RLM's 2/4. Its prompt directs it to infer the culprit from content, and it reads carefully (sometimes a sub-LM call), so it resists the recommendation symptom-distractor that fools tool-RLM on plain.
4. **Recursion still rarely *invoked*** — most recursive cells used 0–1 sub-LM calls; the sparse signal is grep-localizable. The mechanism's value (offloaded context, tiny root, inputs beyond the context window) is real but this task doesn't force it. qwen3:8b recursive is the cost outlier (~19k — over-navigates).

_Caveat: single window (~40k tok, 200 records, productCatalog fault), local Ollama, one run per cell — directional, not error-barred. Earlier leaky-plain run kept at results/runs/rlm_compare_leaky.jsonl for comparison._
