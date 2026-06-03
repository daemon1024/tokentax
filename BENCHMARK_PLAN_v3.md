# Log Analysis Cost Benchmark — Plan v3 (tokentax)

> Supersedes `BENCHMARK_PLAN.md` (v2). This revision is driven by four artifacts produced in
> review: `REVIEW.md` (adversarial review, 54 findings / 6 blockers), `DATA_SOURCE_B.md` and
> `SOURCE_DECISION.md` (source selection), and `GATE_RESULTS.md` + `scripts/validate_design.py`
> (empirical validation on real data, GPU-free). The thesis' cost axis is **already validated**;
> what remains is to build the methods and run the matrix.

---

## 0. What changed from v2 (read this first)

| Area | v2 | v3 (why) |
|---|---|---|
| **Data source** | LogHub HDFS + OTel Demo capture (K8s/flagd) | **Nezha dataset, BOTH systems (Train Ticket + Online Boutique), one pipeline, `git clone` — no infra.** OTel Demo failed (faults on spans not logs); LogHub HDFS has constant-per-window trace_id (no navigation). Both **dropped** from the critical path. |
| **"Single app"** | implicit per-method data | **One dataset + identical pipeline for all 3 methods** (the real anti-confound goal). |
| **Primary task** | binary anomaly detection | **Root-cause / culprit-service localization** (clean `inject_pod` labels). Window-binary-anomaly is **ill-posed** here — ERROR logs pervade normal windows (median 11, one had 44), so error volume carries no fault signal. |
| **Secondary task** | — | **Trace-level anomaly localization** — derived label "trace touches `inject_pod`" gives **31,142 balanced (window,trace) examples**, fixing the small-n problem. |
| **Model** | 7B for in-context, 14B+ for RLM | **One `OLLAMA_MODEL` per cross-method facet** (the v2 split confounds the headline). Qwen tags corrected (see §8). |
| **GPU metric** | `eval_duration` only | **`prompt_eval_duration + eval_duration`** (v2 under-prices the input-heavy in-context method). |
| **≥50 windows/class** | a target | **Dropped** — Nezha has 38 log-visible episodes max; pre-register the real n with bootstrap CIs. |
| **Kill-test** | planned | **Done** on real data; token win confirmed (84×/446× compression handle). |
| **Determinism** | unspecified | `temperature=0`, fixed `seed`, explicit `num_ctx`. |

---

## 1. Thesis (refined)

OpenTelemetry trace context is **free input compression for selective-navigation log analysis**. The
same information, structured with a real `trace_id`, lets a trace-aware navigator (RLM) reach a
conclusion in far fewer tokens than reading the whole window — at equal-or-better accuracy.

Pre-registered hypotheses (the headline is judged on these, not on a vibe):
- **H1 (primary):** on the OTel-correlated data, a **trace-aware RLM** Pareto-improves *tokens-per-correct-conclusion* over the in-context method, with **non-inferior** accuracy.
- **H2 (control):** for the **in-context** method, the structured (OTLP-JSON) condition costs **strictly more** tokens than plain — the "envelope tax." This is the expected control, not evidence for H1. (Measured: **1.76×** on Train Ticket.)

The thesis is about *selectivity*, not smaller logs. v2's unqualified "structured is cheaper" is false for the dump-everything method and is reframed as H2.

---

## 2. Measured ground truth (already validated, GPU-free)

From `scripts/measure_gates.py` + `scripts/validate_design.py` over the cloned data (tiktoken
`cl100k_base` proxy; a Qwen-tokenizer cross-check is a Phase-4 step):

| quantity | Train Ticket | Online Boutique |
|---|---|---|
| windows (per-minute) | 135 | 168 |
| records / window (p50) | 2,033 | — |
| distinct traces / window (p50) | 52 (100% multi-pod) | larger |
| **tokens / window, plain (p50)** | **327,095** | **397,980** |
| tokens / single trace, plain (p50) | 3,905 | 891 |
| windows > 8,192 chunk cap | 135/135 | 168/168 |
| **RLM compression handle (window/trace)** | **84×** | **446×** |
| envelope tax (structured/plain) | 1.76× | (measure in Phase 1) |
| trace_id coverage | 100% | 100% |

Fault catalog (both systems): 101 episodes — **20 exception + 18 return (= 38 log-visible)**, plus
33 cpu + 30 network (metrics-only floor class). Derived trace labels: **31,142 (window,trace) pairs,
15,891 anomalous / 15,251 normal**; exclude **17 entry-point-degenerate** fault windows.

---

## 3. Methods (3)

1. **Drain** — `drain3` template extraction → template-occurrence features → `LogisticRegression`. Token cost = 0. The cost floor.
2. **In-context LLM** — Qwen via Ollama; the whole window in one prompt, chunking above the input cap, aggregate by majority vote. The "read everything" baseline.
3. **Recursive Language Model (RLM)** — Qwen root + sub-LLM over a persistent Python REPL with `peek / grep / find_lines / chunk_indices / extract_trace_ids / lines_for_trace`. Root sees only metadata (line count, available trace_ids) and navigates. The centerpiece; trace-aware navigation is the punchline.

**Model rule (non-negotiable, REVIEW RLM-1):** `model` is a property of a *run*. Every method on a
cross-method headline facet shares one `OLLAMA_MODEL`. A 7B dev smoke point is never plotted against a
27B RLM point.

---

## 4. Conditions (3) — isolate structure from trace IDs

Produced from the single Nezha source via `src/tokentax/nezha.py` (already built):
- **plain** — message body only; `trace_id`/`span_id` scrubbed from the body text (they leak verbatim there).
- **structured** — OTLP-JSON LogRecord (`traceId`/`spanId` as fields).
- **structured-no-trace** — OTLP envelope with the id fields dropped (REVIEW THESIS-3, isolates trace IDs from JSON structure).

All three carry identical message content; only the envelope/ids differ.

---

## 5. Tasks & labels (2)

1. **Primary — root-cause / culprit-service localization.** Given a fault window, name the culprit
   **service** (`inject_pod` → service). Multi-class, exact match. 38 log-visible episodes over 12
   services; report metric-only faults as an explicit "metrics-only floor" tier. Bootstrap 95% CIs;
   **majority-class baseline** mandatory.
2. **Secondary — trace-level anomaly localization.** Within a fault window, identify the anomalous
   traces (derived label: trace touches `inject_pod`; topology-based, no error-text leak). 31,142
   labeled pairs. Unit stays the **whole window** so the RLM advantage holds. **any-ERROR-regex
   baseline** mandatory (it will be ~useless here — that is the point: the task needs correlation,
   not error counting). Exclude the 17 entry-point-degenerate windows.

Window-binary-anomaly from v2 is **demoted** (ill-posed: noisy ERROR baseline).

---

## 6. Metrics (corrected)

| metric | definition |
|---|---|
| input / output / **total tokens** | `Σ (prompt_eval_count + eval_count)` over **every** call (RLM: root turns + all sub-calls + tool-result feedback). |
| **cost_per_correct** (headline x) | `Σ total_tokens over all examples in a cell / count(correct)`. "correct" = exact label match. |
| **gpu_seconds** | `Σ (prompt_eval_duration + eval_duration)/1e9` per call (REVIEW MEASURE-1). **Local-only** — Ollama exposes no per-request GPU time; cloud → tokens + wall-clock only. |
| latency_ms | wall-clock; single-flight for the throughput number (concurrent runs contaminate it). |
| rlm_rounds | tool-call rounds (convergence). |
| F1 / accuracy | with bootstrap 95% CI per cell. |
| envelope_tax, compression_handle | first-class per-record/per-window quantities. |

Determinism: `temperature=0`, fixed `seed`, explicit `num_ctx`, recorded per row. Ollama KV prefix
caching is ON by default (affects gpu_seconds, not the token axis) — control cache state for the
compute metric.

---

## 7. Pre-registered decision rule (REVIEW SEQ-5)

Fixed **before** the final run:
- **Token effect size:** structured-RLM uses ≤ **X%** (pick, e.g. 60%) of in-context-plain's `cost_per_correct`.
- **Accuracy non-inferiority:** RLM F1 ≥ in-context F1 − **δ** (e.g. 0.05), judged via bootstrap CI.
- **Primary confirmatory cell:** **RLM on the trace-anomaly task, structured vs plain** (real trace IDs, 31k examples).
- **Combination rule:** thesis confirmed iff H1 holds on the primary cell; H2 (envelope tax) reported as the expected control; root-cause (small-n) is supporting.

---

## 8. Phases

**Phase 0 — Setup.** `uv` project; `ollama_client.py` (local + cloud via `OLLAMA_HOST`/`OLLAMA_MODEL`/
`OLLAMA_API_KEY`; cloud base `https://ollama.com/api`, Bearer auth — **not** `api.ollama.com`); `Method`
ABC returning the §6 fields incl. `prompt_eval_duration`. **Qwen tags (verify in registry):** dev
`qwen3.5:9b`, RLM `:27b`/`:35b`, final `:122b`/cloud — the v2 `7b/14b/32b` tags **do not exist**;
27b/35b need ~24 GB. Record Ollama version (tool-calling fixed ≥ v0.17.6).

**Phase 1 — Data (Nezha, both systems).** *Largely built* (`src/tokentax/nezha.py`,
`scripts/measure_gates.py`, `scripts/validate_design.py`). Finalize: `csv→OTLP-JSON` map, the three
condition variants, per-trace + per-window windowizer, root-cause + trace-anomaly label join,
group-aware (episode-keyed) train/test split (REVIEW LEAK-5), entry-point-degenerate exclusion, and
the envelope-tax measurement on both systems.

**Phase 2 — (optional) native-OTLP appendix.** Patched OTel Demo (Docker Compose, file exporter,
`logger.Error` patches) only if a "genuine OTLP, not CSV-mapped" arm is later demanded. Not load-bearing.

**Phase 3 — Drain.** Template extraction + LogisticRegression on both tasks; report template count +
majority-class baseline (Drain is the acknowledged weak/volume arm here).

**Phase 4 — In-context LLM.** Window formatter for all 3 conditions; chunk above the input cap;
token accounting from Ollama with a **Qwen-tokenizer cross-check applying the chat template** (REVIEW
MEASURE-2 — compare to `prompt_eval_count`, expect a few % from ChatML overhead, not 5% on bare body).

**Phase 5 — RLM (centerpiece).** REPL helpers incl. `extract_trace_ids`/`lines_for_trace` (bespoke —
build + unit-test first); Ollama tools API; cycle limit + hard `max_total_tokens_per_run`; **ceiling-abort
⇒ scored incorrect, full tokens counted, `aborted:true`** (REVIEW RLM-4). Demonstrate the trace effect:
plain (navigate by content) vs structured (`extract_trace_ids` → per-trace dispatch) on real Nezha windows.

**Phase 6 — Tasks & scoring.** `Task` ABC; root-cause multi-class exact-match + trace-anomaly P/R/F1;
majority-class + any-ERROR baselines; sklearn-verified; bootstrap CIs (resample at **episode level** to
respect autocorrelation, REVIEW STATS-6).

**Phase 7 — Runner.** Config = methods × conditions × tasks × systems; explicit `eval_n` per
(task, system); JSONL row incl. `model`, `aborted`, `gpu_seconds` split into prefill/decode; token
ceiling; resumable; → parquet.

**Phase 8 — Analysis.** Headline `cost_per_correct` vs F1, color by method, shape by condition, facet by
task; token decomposition; RLM rounds histogram (plain vs structured); bootstrap CIs; `make figures`.

---

## 9. Project structure (delta from v2)

- `src/tokentax/` (was `log_bench`) — `nezha.py` ✅, `schemas.py`, `methods/`, `tasks/`, `metrics/`, `runner.py`, `analysis.py`.
- `scripts/measure_gates.py` ✅, `scripts/validate_design.py` ✅.
- `data/raw/Nezha/` (sparse clone, gitignored). **No `infra/` on the critical path.**
- `infra/otel-demo/` + `scripts/capture_otel_demo.py` → optional appendix only.
- **LogHub removed.**

---

## 10. Risks (updated)

| risk | mitigation |
|---|---|
| Small-n accuracy axis (38 RCA episodes) | trace-anomaly task (31k examples) is the primary accuracy axis; RCA reported with bootstrap CIs as supporting; lead with the token headline. |
| Drain weak on Nezha volume | acknowledged; report template count + majority baseline; Drain is the cost floor, not a contender. |
| Entry-point-degenerate trace labels (17 windows) | exclude/flag (frontend etc.). |
| Qwen tool-calling reliability at chosen size | 50-session smoke; fall back to prompt-engineered JSON < 95%; Ollama ≥ v0.17.6. |
| tiktoken proxy ≠ Qwen tokens | Phase-4 Qwen-tokenizer cross-check; gate conclusions hold with huge margin (windows ≫ cap). |
| Root-cause label leak (culprit name in body) | per-flag leakage audit; require beating a substring-match baseline. |

---

## 11. Definition of done

1. `results/runs/combined.parquet` exists for the full matrix on one final model.
2. `summary_table.csv`: F1, tokens, gpu_seconds, latency per (method, condition, task, system) with bootstrap CIs.
3. `headline.png` regenerates via `make figures` and shows whether structured-RLM Pareto-improves per the §7 rule.
4. RLM traces for ≥3 sessions/system inspected; plain vs structured behavior differs as predicted.
5. The §7 decision rule is evaluated and the thesis is **confirmed or honestly revised** — the token axis is already validated; the open question is accuracy-at-low-token-cost.
