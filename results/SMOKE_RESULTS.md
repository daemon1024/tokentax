# Live smoke results (Ollama Cloud, qwen3-coder:480b)

First real LLM numbers on the tokentax benchmark. Cost-bounded validation, **not** full-matrix
results. Model: `qwen3-coder:480b-cloud` (non-thinking, clean JSON, strong tool-calling).
Cloud returns no per-request GPU time, so cost is accounted by **tokens** (+ total_duration latency).

## Drain baseline (GPU-free, `make drain`)
Trace-anomaly localization, 22,461 examples, group-aware split:
- Drain **F1 0.510** (P 0.36 / R 0.89, 95% CI [0.26, 0.73]), 368 templates, **0 tokens**.
- majority baseline F1 0.00; any-ERROR baseline F1 **0.067** → error volume carries no fault signal
  (confirms the task needs correlation, not counting).

## In-context vs RLM — root cause, one fault window (`scripts/smoke_compare.py --rank 0`)
Window `2023-01-29/10_20`, true culprit `ts-travel-service`, 244 records.

| method | condition | in+out tokens | rounds | predicted | correct |
|---|---|---|---|---|---|
| in-context | plain | 31,447 | 1 | ts-basic-service | ✗ |
| in-context | structured | 68,808 | 1 | ts-basic-service | ✗ |
| RLM | plain | 12,935 | 4 | ts-basic-service | ✗ |
| RLM | structured | 11,234 | 5 | ts-order-service | ✗ |

**Cost axis (thesis) — CONFIRMED directionally:**
- plain: RLM = **0.41×** in-context tokens; structured: RLM = **0.16×** (6× cheaper).
- envelope tax (in-context structured/plain) = **2.19×** on real Qwen tokens (H2 control confirmed).
- structure is *free compression for the navigator* (trace-aware RLM cheapest at 11.2k, and cheaper
  than trace-blind RLM) but a *tax for the reader* (in-context structured costs 2.19× plain).

**Accuracy — UNRESOLVED:** 0/4 on this single hard window. The injected fault in `ts-travel-service`
surfaces as errors in services it calls (`ts-basic-service`/`ts-order-service`) — classic
symptom-vs-cause. Needs (a) many windows to measure, (b) likely prompt/method tuning (have the RLM
trace an error to its ORIGIN service, not where symptoms appear).

## What this validates / what's open
- ✅ Cloud plumbing, token accounting, both LLM methods, the RLM tool-loop all work on real data.
- ✅ The token-cost thesis holds live (RLM ≪ in-context; trace-aware cheapest).
- ❓ Accuracy across many windows (costs cloud budget) + prompt tuning for symptom-vs-cause.
- Next: the runner (Phases 7-8) to sweep windows, and a costed decision on full-matrix spend.
