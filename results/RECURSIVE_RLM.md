# Faithful RLM (recursive sub-LM) vs grep-navigator vs in-context

Implements the actual mechanism from arXiv:2512.24601 (`src/tokentax/methods/rlm_recursive.py`): the
root LM keeps the window in an environment (never its own context) and dispatches `llm_query(question,
start, end)` — an INDEPENDENT sub-LM call on a slice — getting back only the sub-LM's short answer.
Contrast with `rlm.py` (grep-navigator: greps and reads results into the root's own context) and
in-context (reads the whole window).

## Result (qwen3:8b, one productCatalogFailure window capped to 200 records ≈ 39,845 plain tok, 2 pc errors)
`scripts/run_recursive_compare.py --max-records 200 --chunk-lines 70`

| method | cond | pred | ok | total_tok | mechanism |
|---|---|---|---|---|---|
| rlm_recursive | plain | product-catalog | ✓ | 6,435 | root 3,096 + sub 3,339, **1 sub-call, maxRootPrompt=873** |
| rlm_recursive | structured | product-catalog | ✓ | 2,207 | root 2,207, **0 sub-calls, maxRootPrompt=831** |
| rlm_navigate (grep) | plain | product-catalog | ✓ | 5,336 | 3 rounds |
| rlm_navigate | structured | product-catalog | ✓ | 3,216 | 3 rounds |
| in_context (read-all) | plain | catalog | ~ | 48,059 | reads whole window (chunked); 8B partial |
| in_context | structured | unknown | ✗ | 71,424 | reads whole window; 8B drowns |

## What this shows
1. **The recursion is faithful.** `maxRootPrompt ≈ 830–873 tokens` — the root model never held more
   than ~870 tokens even though the window is ~40k. The chunk it needed was read by a *sub-LM*
   (the 3,339-token sub-call); only the sub's one-line answer returned to the root. That ceiling is
   ~constant in window size — it would stay ~870 on a 1M-token window. In-context cannot do this:
   it must hold/chunk all 48–71k here (and the 8B still fails).
2. **For a SPARSE signal, recursion does not save tokens over navigation.** rlm_recursive (6.4k/2.2k)
   ≈ rlm_navigate (5.3k/3.2k). Both are cheap because the answer is grep-localizable (~18 error lines).
   On structured, the recursive root even solved it with **0 sub-calls** (overview+grep sufficed).
   Recursion's distinctive value is **capability** (root context stays tiny → inputs far beyond the
   context window), not token efficiency on localizable tasks.
3. **Clarifies the project's earlier "RLM".** Our prior RLM numbers were the grep-NAVIGATOR (same
   family as Claude Code's tool loop), not the paper's recursion. The token-cost thesis (navigate ≪
   read-all; structure makes navigation cheap) stands and is about retrieval efficiency. The paper's
   recursion is an orthogonal axis (handle huge inputs with a tiny root) — now implemented and shown.

## Caveat
Single window, 8B, sparse signal. To make recursion *win on tokens* you need a task whose relevant
region is large (so a sub-LM must compress it) and/or an input that exceeds the model context (so
in-context can't run at all). The mechanism is in place to test that next.
