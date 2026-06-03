# Benchmark Plan — Adversarial Review

## Verdict

The thesis as written **does not survive scrutiny in its unconditional form** and the plan is **not buildable as-is** — it needs targeted revision first. The single biggest threat to a valid result is a stack of mutually reinforcing confounds on the headline chart (§1 line 92): mixed model sizes across methods (7B in-context vs 14B+ RLM), an undefined x-axis formula, label leakage on the OTel Demo, and a "free input compression" claim that is *falsified by construction* for the in-context method (where the OTLP-JSON envelope inflates tokens 2.5–5× per line). The thesis is salvageable but only if scoped to the RLM/selective-navigation regime, with the in-context method reframed as the control that measures the envelope tax. Critically, the OTel Demo arm — the *only* source carrying real trace IDs — is far thinner than assumed: its headline flag emits no log record at all, three of five named flags are renamed in the current repo, and the toggle mechanism does not work on the mandated Kubernetes deployment.

## Blockers (must resolve before building)

### 1. The headline flag `productCatalogFailure` emits no log record (OTEL-1)
The plan's named example flag records its failure only on the trace span (`span.SetStatus` + `span.AddEvent`), never via a logger, and no service in the failure call chain (frontend/checkout/payment) exports OTLP logs. The window gets labeled anomalous from the flag toggle while the label is unrecoverable from the logs a log-based method actually sees — systematic label noise penalizing every method.
**EDIT (§5 Background + Validation):** Drop `productCatalogFailure` as the headline example and delete the validation line *"Toggling `productCatalogFailure` produces a window labeled with that root cause."* Add a hard capture gate: *"A window is retained only if its ground-truth label is recoverable from the captured signal a method can see — assert ≥1 error/anomaly-bearing LogRecord per anomalous window."*

### 2. Most named flags surface only in metrics/traces, not error logs (OTEL-2, corrected to major but lands with OTEL-1/3 as a blocker-class data problem)
`kafkaQueueProblems`, `adServiceHighCpu`, `recommendationCacheFailure`, `emailMemoryLeak`, `imageSlowLoad`, `loadgeneratorFloodHomepage` are latency/CPU/GC/memory incidents with no distinctive error-log signature. Even the "error" flags (cart, payment, product-catalog) put their signal on spans, not log bodies. A multi-class root-cause-from-logs task over these classes manufactures failures unrelated to log shape.
**EDIT (§9 Task 3, §5 Task 7):** Restrict the root-cause class set to flags empirically confirmed to emit a trace-correlated ERROR LogRecord. Bucket all metrics/trace-only flags into a single explicitly-acknowledged "metrics-only" class (expected floor, not method failure), and size the ≥50-windows/class target to the audited set, not the full flag list.

### 3. Mixed model sizes across methods confound the headline (RLM-1)
§0 (line 20) and §5 (line 339) put the in-context method on 7B and RLM on 14B+. The headline scatter (line 92) carries the method dimension, so any RLM F1 or token profile is confounded by model capability — and the more capable model is handed to the method the authors want to win.
**EDIT (§0 Model strategy):** Replace the "7B for other methods, 14B+ for RLM" rule with: *"`model` is a property of a RUN, not a method. Every method on a cross-method headline facet must share one `OLLAMA_MODEL`. 7B is a dev/smoke target only and must never be plotted against a 14B+ RLM point."* Add `OLLAMA_MODEL` to the Phase 7 JSONL schema (line 384) and a Phase 8 plot-time guard that filters to one model per facet.

### 4. GPU-seconds uses `eval_duration` only, undercounting input compute (MEASURE-1)
§1 (line 86) and §7 Task 5 (line 326) derive "true compute cost" from `eval_duration` alone, which measures *output generation only* and excludes `prompt_eval_duration` (input processing). The in-context method is huge-prompt/tiny-output, so its compute is dominated by `prompt_eval_duration` — the metric structurally under-prices in-context and over-prices RLM.
**EDIT (§1 Metrics, §0 Phase 0 Task 4, §7 Task 5):** Have `ollama_client.py` also return `prompt_eval_duration_ns`. Redefine `gpu_seconds = (prompt_eval_duration + eval_duration)/1e9` per call, summed over root + all sub-calls for RLM. Exclude `load_duration`. Report prefill and decode compute separately so the cross-method asymmetry is visible. (Note: the *token* headline x-axis is unaffected; this fix scopes to the compute metric and DoD item 2.)

### 5. LLM eval-set size is never defined — the matrix is empty or intractable (STATS-1)
§7 Task 1 defines the runner only as "methods × conditions × data sources × tasks" with no per-cell example count N. Reusing ≥50/class gives CIs too wide for the headline; running the full 10k–100k HDFS subset gives ~10⁵–10⁶ inferences (RLM at ~20 rounds/example) — infeasible on one GPU. The runner has no number to iterate to.
**EDIT (§7 Task 1):** Add a pre-registered, stratified `eval_n` per (data_source, task) as a first-class config field, e.g. ~300–500 HDFS blocks for the LLM/RLM methods (keep Drain on the full set), plus the captured OTel windows. Record the total inference-call budget = Σ(eval_n × calls/example) and gate the run on it before scheduling.

### 6. No early kill-test / go-no-go gate before the full 8-phase build (SEQ-1, corrected to major but operationally blocker-class)
The thesis is first observable only after Phases 0/1/2/5 — after building K8s Ollama, two data pipelines, and three methods. The decisive sub-claim (RLM-with-`extract_trace_ids()` vs without, on one synthetic multi-trace window) is a few-hours experiment.
**EDIT (§0 dependency graph):** Insert a "Phase 0.5 minimal kill-test" before Phases 1–2: local `ollama serve`, one hand-authored ~2–5k-line multi-trace window, only `extract_trace_ids()`/`lines_for_trace()` + a one-prompt baseline. Pre-commit: *if structured does not reduce total tokens by ≥X% at equal-or-better correctness, stop and revise the thesis before building infra.*

## Major issues (will bias results or waste effort)

### Thesis framing
- **"Free input compression" is method-dependent (THESIS-1).** For the in-context method the OTLP envelope costs 2.5–5× more tokens/line (measured on real HDFS lines with cl100k_base). **EDIT (§1 Thesis):** scope to selective-navigation methods; pre-register H1 (RLM-structured Pareto-dominates) and H2 (in-context-structured costs strictly *more* tokens — the expected envelope-tax control).
- **HDFS synthetic trace_id is constant per window (THESIS-2).** One block = one trace = `extract_trace_ids()` returns a single ID → RLM navigation is a no-op on LogHub. **EDIT (§1 data table, §8 Task 7, line 415, line 459):** demote LogHub to a Drain/scale baseline + isolated envelope-tax measurement; expect the Pareto headline *only* from the OTel Demo.
- **Thesis bundles JSON-structure AND trace-navigability (THESIS-3).** `strip.py` drops the whole envelope, so plain lacks both; a structured win can't be attributed to trace IDs. **EDIT (§1):** add a `structured-no-trace` condition (a near-free field drop given `strip.py` already isolates the envelope), or weaken causal language to "the structured+trace bundle."
- **"Same information" is false (THESIS-4).** Structured keeps `severity_number`/ns-timestamps/`span_id`; plain drops them (line 239). On the OTel Demo, ERROR severity is near a label. **EDIT (§4 Task 5/6):** inline severity+timestamp into the plain body (Option A) so the only difference is JSON shape + IDs, and reconcile the §7 Task 2 "same information" claim with `strip.py`.
- **Headline x-axis is undefined (THESIS-5).** "Total tokens per correct conclusion" (lines 92, 405) has no formula; candidates reorder methods. **EDIT:** pin `cost_per_correct = sum(total_tokens over all examples in cell) / count(correctly classified)`, define "correct" = exact label match, report mean tokens and F1 separately.

### RLM cost accounting
- **Multi-turn token accounting under-specified (RLM-2).** Ollama's `prompt_eval_count` re-bills the full growing transcript every root turn; "root + subs" (line 354) reads as one-root + N-subs and risks undercounting the dominant cost. **EDIT (§5):** state `total_input = Σ prompt_eval_count over every root turn AND every sub-call`; add a scripted multi-turn unit test in `test_rlm.py`.
- **RLM can cost more on small windows (RLM-3).** The paper's crossover is ~2¹⁴ tokens; HDFS block-sessions (~19 lines) and possibly 60s OTel buckets sit below the 8k chunking cap, so in-context never chunks and RLM is structurally dominated. **EDIT (§4/§5 + risk log):** measure window token distributions first; size at least one condition to exceed the context budget; add the named risk.
- **Ceiling-abort scoring undefined (RLM-4).** §5/§7 abort on the token ceiling but never define the row's fate; DROP causes survivorship bias inflating RLM. **EDIT:** abort ⇒ scored incorrect, full tokens counted, `aborted:true` + `abort_reason` flag added to the §0 Method contract and §7 JSONL; report per-cell abort rate; reconcile with "no NaNs" (line 414).

### Measurement
- **No temperature/seed/num_ctx pinned (MEASURE-3).** Ollama defaults to temp ~0.8, no seed — predictions, `eval_count`, and RLM trajectories vary run to run, contradicting "consistent across two identical calls" (line 215) and DoD item 3. **EDIT (§0 Task 4):** pass `temperature=0`, fixed `seed`, explicit `num_ctx`; record options per row; report variance across N seeds for RLM.
- **`gpu_seconds` not comparable local vs cloud (INFRA-2, MEASURE-5).** The Ollama API exposes no per-request GPU-time; cloud meters GPU-time at the account level only. **EDIT (§1 Metrics):** scope `gpu_seconds` to local-only; for cloud rely on tokens (hardware-independent) + wall-clock; never compare `gpu_seconds` across backends.
- **Latency contaminated by the concurrent runner (MEASURE-4).** `latency_ms` (line 384) is client-side wall-clock under a capped replica pool; queueing differs for RLM vs in-context. **EDIT:** relabel as "wall-clock under load"; use `prompt_eval_duration + eval_duration` as the contention-free proxy for the §8 box plot; measure true wall-clock only single-flight.
- **Tokenizer cross-check ignores the chat template (MEASURE-2, corrected to minor).** Comparing `encode(body)` to `prompt_eval_count` omits ChatML wrappers + system prompt → spurious >5% flags; "match exactly" (line 332) is unachievable. **EDIT (§4 Task 4):** use `apply_chat_template(..., add_generation_prompt=True, tokenize=True)`; relax validation to "within 1–2% of `prompt_eval_count`."

### Infrastructure
- **Nonexistent Qwen tags throughout (INFRA-1, STATS-4, SEQ-3).** `qwen3.5:7b`/`14b`/`32b` do not exist (real sizes: 0.8b/2b/4b/9b/27b/35b/122b). Every config, PVC/GPU sizing, and validation string is wrong. **EDIT:** dev → `qwen3.5:9b` (~6.6 GB); RLM → `:27b`/`:35b`; final → `:122b`/cloud. Re-size GPU (27b/35b need ~24 GB, not 8–16 GB) and PVC. Promote tag verification to a Phase 0 prerequisite *before* manifest authoring.
- **"No prompt caching in Ollama" is false (INFRA-3).** Ollama reuses KV cache across byte-for-byte prefixes; this deflates `eval_duration`/GPU-seconds asymmetrically (helps RLM's repeated sub-calls and the stable structured prefix). `prompt_eval_count` is *immune*, so the token axis is safe. **EDIT (§4 Task 1):** delete the false claim; control cache state for the GPU-seconds metric (cold-load per example or a fixed warm-prefix protocol).
- **Cloud base URL likely wrong (INFRA-5).** The plan hardcodes `https://api.ollama.com` (lines 198, 449); official endpoints are `https://ollama.com/api` (native) and `https://ollama.com/v1` (OpenAI-compat). **EDIT:** use `https://ollama.com`, read host from `OLLAMA_HOST`, make the cloud smoke test assert a real round-trip.
- **GPU budget mismatched to real sizes (INFRA-6); flag toggle broken on K8s (OTEL-5).** flagd has no write API and ignores ConfigMap edits on K8s (only the writable copy is read; open issue #1953). **EDIT (§5 Task 4):** capture via Docker Compose (file-watch hot-reload works) or script the flagd-ui backend + poll a flagd evaluation before capturing — replace the fixed-sleep assumption.
- **Three named flags are renamed in the repo (OTEL-4).** `paymentServiceFailure`→`paymentFailure`, `cartServiceFailure`→`cartFailure`, `adServiceFailure`→`adFailure`; file is `demo.flagd.json`, not `flagd-config.json`. Patching wrong keys silently no-ops → baseline windows mislabeled anomalous. **EDIT:** read flag names from a pinned tag's `demo.flagd.json`; assert each key exists before toggling.

### Leakage & stats
- **HDFS near-saturated at 2.93% base rate (LEAK-3).** All methods may land at ~0.97 F1, flattening the headline y-axis; no base-rate control or majority-class baseline. **EDIT (§3/§8):** position HDFS as the token/cost axis; fix and report the eval positive ratio; always report a majority-class baseline; state the eval n.
- **Window label is "contains ≥1 ERROR line" (LEAK-4).** Most flags fire on a fraction of requests, so a 60s anomalous window is mostly-normal. **EDIT (§5/§9):** add a mandatory zero-token "any-ERROR-in-window" regex baseline that methods must beat; report per-window error density; prefer trace-scoped labels.
- **Drain OTel split risks cross-episode leakage (LEAK-5).** Sequential per-flag capture yields autocorrelated near-duplicate windows; a random split inflates the Drain cost-floor. **EDIT (§6 Task 2):** group-aware split keyed on episode id; stamp episode ids in the manifest; assert no episode spans train+test.
- **Root-cause label leaks into the body (LEAK-1, corrected to major).** Some flags (e.g. payment via `logger.warn({err})`) write a self-naming string into the log body, reducing root-cause to substring match. **EDIT (§1/§5):** per-flag leakage audit; redact culprit tokens or require methods to beat a substring-match baseline; drop "labels for free" for root cause (anomaly labels are free, clean root-cause labels are not).
- **No pre-registered decision rule (SEQ-5, STATS-2/3).** DoD #3/#5 are qualitative ("Pareto-dominates", "solid enough"); F1 CIs (line 409) are computed but never tied to a verdict, and the AND/ANY quantifier across sources is ambiguous. **EDIT (§15):** pre-register a token effect-size threshold, an F1 non-inferiority margin (using the bootstrap CIs), a primary confirmatory cell (RLM on OTel anomaly), and the LogHub-vs-OTel combination rule; reframe F1 as non-inferiority rather than strict dominance.
- **OTel root-cause class set mis-scoped (STATS-5).** 15 flags exist; `adFailure` fires "1/10th of the time" so 50 attributable windows is hard; several classes are log-indistinguishable. **EDIT (§5/§9):** freeze a curated keep-set; document exclusions; empirically verify achievable per-class counts before committing to ≥50/class.

## Minor issues & nits

- **OTel log-trace coverage is a documented gap (THESIS-6, OTEL-3):** ~half the services emit no OTLP logs; even Go services that do log put failures on spans. Run a coverage probe (fraction of LogRecords with non-empty `trace_id` per service/flag) as a Phase 2 exit criterion — the matrix's load-bearing source rides on it.
- **Envelope token tax not measured as a first-class quantity (THESIS-7):** add `tokens(structured record) − tokens(body)` per record so the break-even window size is reportable.
- **`opencode_RLM` is OpenCode/subagent-specific, no Ollama path (RLM-5):** reframe §5 Task 1 to use it for REPL-helper *design* only; the tool-loop must be reimplemented against the Ollama tools API.
- **Same-size root/sub disables the paper's cost lever (RLM-6):** state this explicitly; an RLM token win here is a *stronger* result than the paper's.
- **qwen3.5 tool-calling bugs were fixed in Ollama v0.17.6 (INFRA-4, corrected to minor):** not a blocker, but record the Ollama version in run metadata and run the 50-session smoke test on the actual tag.
- **K8s `postStart` pull + bare `nvidia.com/gpu:1` (INFRA-7, corrected to minor):** use an initContainer/Job for the pull; document NVIDIA device-plugin + `runtimeClassName: nvidia` prerequisites.
- **qwen3.5 is multimodal MoE, 256K context (INFRA-8):** pin a `transformers` version that supports its tokenizer before relying on the cross-check.
- **Bootstrap over autocorrelated windows under-estimates CI width (STATS-6):** resample at the episode level; prefer many independent episodes over many windows from one.
- **Drain template-per-flag is leakage, not strength (LEAK-7):** self-labeling error strings become unique templates; flag this in §8 so Drain doesn't visually "win" the root-cause chart for the wrong reason.
- **RLM/chunking input-token summation (MEASURE-6):** state `total_tokens = Σ over all calls of (prompt_eval_count + eval_count)`, including every sub-call and every re-sent chunk.
- **`extract_trace_ids`/`lines_for_trace` are bespoke, not in `opencode_RLM` (SEQ-7):** build and unit-test them first (in the kill-test), as the load-bearing novelty.
- **Collector file-exporter is the de-risked piece (OTEL-6):** but verify `transform/sanitize_logs` doesn't strip `traceId`, pin the OTLP-JSON encoding, and run this validation *first* as the Phase 2 go/no-go.
- **Premature infra (SEQ-6, corrected to minor):** defer K8s-Ollama and the cloud client to a "Phase 0b" gated behind the local kill-test; parquet/CIs are already correctly sequenced late.

## Recommended path forward

**(1) Run the kill-test and a Phase-2 spike BEFORE the full build.** Two cheap gates, each ~a day on local `ollama serve`:
- **Kill-test (thesis falsification):** one hand-authored multi-trace window, `extract_trace_ids()`/`lines_for_trace()` + a one-prompt baseline. Measure RLM-with-trace-IDs vs without, and in-context plain vs structured. Pre-commit a token-reduction gate; if structured doesn't save tokens at equal-or-better correctness, stop and rethink.
- **OTel feasibility spike (data reality):** against a live demo, for each candidate flag, answer (a) does a ✅-log service emit a LogRecord with a populated `trace_id`? (b) does the flag produce a trace-correlated ERROR LogRecord (not just a span)? (c) is the root cause recoverable from those logs? Note: `kafkaQueueProblems` is actually the *most* log-visible flag (fraud-detection consumer logs the literal flag name); `productCatalog`/`payment` failures live on spans. Restrict the benchmark to flags that survive this spike, and verify the toggle mechanism (Docker Compose hot-reload or flagd-ui) actually flips flags.

**(2) Remove these confounds or the headline chart is uninterpretable:**
- Hold the model **fixed** across all methods on any cross-method facet (RLM-1).
- Predict and label the **in-context envelope tax** (2.5–5×/line) as the control, not as evidence for the thesis (THESIS-1).
- Fix the GPU metric to **`prompt_eval_duration + eval_duration`** and scope it local-only (MEASURE-1, INFRA-2).
- Make **plain information-equivalent** (inline severity/timestamp) and add a **`structured-no-trace`** condition to isolate trace IDs (THESIS-3/4).
- Add **majority-class** and **any-ERROR-regex** baselines; require methods to beat them (LEAK-3/4).
- Pin **temperature=0, seed, num_ctx** (MEASURE-3).

**(3) Pre-register the decision rule** (before any final run, in BENCHMARK_PLAN.md §15 and CLAUDE.md):
- Token effect size: structured uses ≤ X% of plain's tokens-per-correct (pick X, e.g. ≤80%).
- F1 non-inferiority: structured F1 ≥ plain F1 − δ (e.g. δ=0.02), judged via the bootstrap CI.
- Primary confirmatory cell: **RLM on OTel anomaly detection** (real trace IDs); LogHub and in-context are supporting/control.
- Combination rule: thesis confirmed iff H1 holds on the OTel Demo primary cell; H2 (in-context envelope tax) is reported as the expected control; LogHub is descriptive only.
- The kill-test passing is a precondition for trusting the full run.

**(4) Corrected factual checklist (verified during review):**
- [ ] Qwen tags: dev `qwen3.5:9b`, RLM `:27b`/`:35b`, final `:122b`/cloud — NOT `7b`/`14b`/`32b`.
- [ ] GPU sizing: 27b/35b need ~24 GB (not 8–16 GB); 122b needs multi-GPU/cloud; PVC sized for all weights pulled.
- [ ] Cloud base URL: `https://ollama.com/api` (native) or `/v1` (OpenAI-compat) — NOT `api.ollama.com`; auth `Authorization: Bearer $OLLAMA_API_KEY`.
- [ ] Flag names (from pinned `demo.flagd.json`): `paymentFailure`, `cartFailure`, `adFailure`, `productCatalogFailure`, `kafkaQueueProblems` — drop `*ServiceFailure`; file is `demo.flagd.json`.
- [ ] Flag toggle: no flagd write API, no K8s ConfigMap hot-reload (issue #1953) — use Docker Compose or flagd-ui + evaluate-confirm.
- [ ] API fields: GPU-seconds needs `prompt_eval_duration + eval_duration`; `prompt_eval_count` reports full context (immune to cache); no per-request cloud GPU-time field; no GPU/cost/billing field exists.
- [ ] Ollama KV prefix caching is ON by default (delete the "no prompt caching" claim).
- [ ] qwen3.5 tool-calling fixed in Ollama ≥ v0.17.6; record Ollama version per run.
- [ ] HDFS base rate = 2.93% (16,838 / 575,061); supervised F1 ceiling ~0.96–0.99.
- [ ] `productCatalogFailure` and most flag failures emit on spans, not log bodies.

## What this review did NOT cover

- **No code was run and no live infra exists**, so every empirical claim still needs live verification once a demo and Ollama are stood up: actual `trace_id` population per service in captured OTLP-JSON, actual per-flag log visibility, actual window token distributions (the RLM-3 crossover hinges on this), and actual qwen3.5 tool-call reliability at the chosen size.
- **REFUTED/downgraded findings were dropped** from the blocker tier: INFRA-4 (tool-calling — fixed in shipped Ollama), SEQ-6 (premature infra — partly mis-sequenced in the critique itself, since parquet/CIs are correctly late), and LEAK-6 (the "plain reveals culprit via propagation" claim was largely refuted — the strings live in spans, not log bodies, which actually *supports* the plan's correlation framing).
- **Not independently re-derived:** the exact token ratios per flag/service on the OTel Demo (only HDFS lines were tokenizer-measured), the precise OTel demo service count and current log-coverage matrix (the official matrix lags the repo for Go services — verify against a pinned tag), and the Drain3 tuning/accuracy on the OTel windows.
- **Out of scope of the source findings:** prompt-engineering quality of the in-context/RLM system prompts, statistical treatment beyond power/leakage (e.g. calibration, inter-run drift on cloud), and any security/cost-of-compute budgeting in real currency (explicitly deferred per §12).