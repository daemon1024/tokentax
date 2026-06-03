# Log Analysis Cost Benchmark — Experiment Plan (v2)

> Reproducible benchmark comparing three log-analysis approaches (Drain, in-context LLM, Recursive Language Model) across log conditions (unstructured vs structured with OpenTelemetry trace IDs). Runs on **Qwen via Ollama** — small local model for development, larger local or Ollama Cloud models for final runs. Two data sources: **LogHub** (scale + baselines) and the **OpenTelemetry Demo** (real trace IDs + flag-labeled incidents). Output is an experimental result log — no slides, no demo, no public release in this scope.

---

## 0. How to use this plan with Claude Code

Phases are designed to be parallelizable. Several can run simultaneously across independent Claude Code agents once dependencies are met.

For each phase, paste the phase content into a Claude Code session with:

> "Work through the tasks in this phase one at a time. After each task, stop and show me what you produced before moving on. Confirm validation criteria are met before marking a task complete. Treat the plan as the source of truth — flag anything ambiguous instead of guessing."

A `CLAUDE.md` lives at the project root with stable context (commands, conventions, deps). Generate it in Phase 0.

### Model strategy: start small, scale later

- **Development (Phases 0–7):** a **small local Qwen** (Qwen 3.5 7B) via Ollama in Kubernetes. Fast iteration, fits modest GPU, near-zero turnaround.
- **RLM caveat:** the RLM method (Phase 5) relies on reliable tool-calling. A 7B model may be flaky at this. Expect to bump to **14B+ for RLM development** even while other methods stay on 7B.
- **Final benchmark runs (Phase 7):** swap to a **larger Qwen (32B)** locally, or a bigger variant via **Ollama Cloud**, by changing a single config value. The harness never hardcodes a model.

The model is selected by three env vars everywhere: `OLLAMA_HOST`, `OLLAMA_MODEL`, and optional `OLLAMA_API_KEY` (for cloud). Local and cloud share the same client code.

### Phase dependency graph (for parallelization)

```
Phase 0 (Setup + Ollama local & cloud config)
   ↓
   ├─→ Phase 1 (Data: LogHub) ──────────┐
   └─→ Phase 2 (Data: OTel Demo) ───────┤
                                        │
        ┌───────────────────────────────┤
        ├─→ Phase 3 (Drain) ────────────┤   (3, 4, 5, 6 are
        ├─→ Phase 4 (LLM) ──────────────┤    independent and
        ├─→ Phase 5 (RLM) ──────────────┤    parallelizable once
        └─→ Phase 6 (Tasks) ────────────┤    data exists)
                                        │
Phase 7 (Runner) ←──────────────────────┘
   ↓
Phase 8 (Analysis)
```

Phases 1 and 2 (the two data sources) are independent of each other and can run in parallel. After either lands, the method phases (3/4/5) can begin.

---

## 1. Experiment overview

### Thesis

OpenTelemetry trace context is free input compression for AI log analysis. The same information, structured differently, costs fewer tokens to analyze with comparable or better accuracy.

### Methods

1. **Drain** — classical template extraction (He et al., 2017). Library: [`drain3`](https://github.com/IBM/Drain3). Token cost = 0.
2. **In-context LLM** — Qwen via Ollama. Single-prompt-per-window with chunking when needed.
3. **Recursive Language Model (RLM)** — Qwen as both root and sub-LLM. Root model navigates large logs via a Python REPL with grep/peek/chunk/trace-aware helpers. Pattern from Zhang, Kraska, Khattab ([arXiv:2512.24601](https://arxiv.org/abs/2512.24601)). Reference: [opencode_RLM](https://github.com/maclarensg/opencode_RLM).

### Log conditions

Same underlying data, two shapes:
- **Plain** — unstructured log text only (message bodies).
- **Structured + trace IDs** — OpenTelemetry-shaped JSON LogRecords with `trace_id`/`span_id` as first-class fields.

### Data sources

| Source | Role | Trace IDs | Labels |
|---|---|---|---|
| **LogHub HDFS** | Scale, established Drain baselines | Synthetic (derived from block IDs) | Anomaly (built-in) |
| **OTel Demo** | Realistic multi-service logs, controllable incidents | **Real OTel trace context** | **Anomaly + root cause (from feature flags)** |

### Tasks

- **Primary: anomaly detection** — binary, F1/precision/recall. Both data sources support it.
- **Secondary: root-cause identification** — multi-class, exact match. The OTel Demo provides labels for free (the active failure flag is the root cause).

### Metrics

| Metric | Why |
|---|---|
| Input tokens | Primary cost proxy |
| Output tokens | Especially important for RLM (multi-call output) |
| Total tokens | Headline number |
| Wall-clock latency per example | Throughput proxy |
| GPU seconds | True compute cost (works for both local Ollama `eval_duration` and Ollama Cloud GPU-time metering) |
| Tool-call rounds (RLM only) | Convergence efficiency |
| F1 / accuracy | The other axis of the headline result |

### Headline result

2D scatter: **total tokens per correct conclusion** (x-axis) vs **F1 accuracy** (y-axis). Each point is `(method, condition)`. If structured + trace IDs Pareto-dominates plain, thesis confirmed.

---

## 2. Project structure

```
log-bench/
├── CLAUDE.md
├── README.md
├── pyproject.toml
├── .env.example                    # OLLAMA_HOST, OLLAMA_MODEL, OLLAMA_API_KEY
├── Makefile
├── BENCHMARK_PLAN.md
│
├── infra/
│   ├── ollama/
│   │   ├── deployment.yaml          # K8s Ollama (local model serving)
│   │   ├── service.yaml
│   │   ├── pvc.yaml                  # model weights volume
│   │   └── README.md                # local + cloud setup notes
│   └── otel-demo/
│       ├── values.yaml              # Helm overrides for the demo
│       ├── collector-logs-file.yaml # Collector patch: file exporter for logs
│       ├── flagd-config.json        # baseline flag config
│       └── README.md
│
├── src/log_bench/
│   ├── __init__.py
│   ├── data/
│   │   ├── loghub.py                # LogHub loaders + synthetic trace injection
│   │   ├── otel_demo.py             # OTLP-JSON LogRecord loader + windowing
│   │   ├── trace_inject.py          # synthetic trace ID injection (LogHub)
│   │   ├── strip.py                 # produce 'plain' variant from structured
│   │   └── schemas.py               # OTel LogRecord pydantic model
│   ├── methods/
│   │   ├── base.py                  # Method abstract base class
│   │   ├── drain.py
│   │   ├── llm_incontext.py
│   │   ├── rlm.py
│   │   ├── repl.py                  # REPL helpers (peek/grep/trace-aware)
│   │   └── ollama_client.py         # local + cloud Ollama wrapper
│   ├── tasks/
│   │   ├── anomaly_detection.py
│   │   └── root_cause.py
│   ├── metrics/
│   │   ├── tokens.py
│   │   └── scoring.py
│   ├── runner.py
│   └── analysis.py
│
├── scripts/
│   └── capture_otel_demo.py         # flag-driven log capture loop
│
├── data/
│   ├── raw/                         # LogHub downloads (gitignored)
│   ├── otel_demo/                   # captured OTLP-JSON logs (gitignored)
│   └── processed/                   # plain + structured variants
│
├── results/
│   ├── runs/                        # per-experiment JSONL
│   └── figures/                     # internal-review charts
│
├── notebooks/
│   ├── 01_explore_loghub.ipynb
│   ├── 02_explore_otel_demo.ipynb
│   ├── 03_validate_methods.ipynb
│   └── 04_results_review.ipynb
│
└── tests/
    ├── test_drain.py
    ├── test_llm.py
    ├── test_rlm.py
    ├── test_otel_demo.py
    └── fixtures/
```

---

## 3. Phase 0 — Setup & environment

**Goal:** Working Python project; Ollama serving a small Qwen locally in K8s; client wrapper that works against both local Ollama and Ollama Cloud via config.

**Deliverables:**
- `pyproject.toml`, `Makefile`, `CLAUDE.md`
- `infra/ollama/` manifests; Qwen 3.5 7B pulled and reachable
- `ollama_client.py` supporting local + cloud
- `Method` abstract base class
- Smoke test passing

**Tasks:**

1. **Initialize the repo.** `uv init`, Python ≥ 3.11. `.gitignore` for `data/raw/`, `data/otel_demo/`, `.env`, `results/`.

2. **Pin dependencies:** `drain3`, `ollama`, `httpx`, `transformers` (Qwen tokenizer for token cross-checks), `pandas`, `numpy`, `scikit-learn`, `matplotlib`, `seaborn`, `pydantic`, `pytest`, `pytest-asyncio`, `ruff`, `mypy`.

3. **Kubernetes manifests for local Ollama** in `infra/ollama/`:
   - `Deployment` running `ollama/ollama`
   - `Service` exposing port 11434
   - `PVC` for model weights (7B needs ~5–8 GB at Q4; size generously)
   - GPU resource request (`nvidia.com/gpu: 1`; a single 8–16 GB GPU is enough for 7B)
   - Readiness/liveness probes on `/api/version`
   - A job or `postStart` that runs `ollama pull qwen3.5:7b` — **verify the exact tag in the Ollama registry first**

4. **Ollama client wrapper** (`ollama_client.py`):
   - Reads `OLLAMA_HOST` (default `http://ollama.default.svc:11434`), `OLLAMA_MODEL` (default `qwen3.5:7b`), and optional `OLLAMA_API_KEY`.
   - When `OLLAMA_API_KEY` is set, point at `https://api.ollama.com` and send the auth header — this is the **Ollama Cloud** path. Same code, different config.
   - Methods: `generate(prompt, system=None, **kw)` and `chat(messages, tools=None, **kw)`, both returning `content`, `prompt_eval_count`, `eval_count`, `eval_duration_ns`.
   - Async via `httpx.AsyncClient` for parallel calls.
   - Retries with exponential backoff.
   - **Never read the API key from code or args — environment only.** Document in `.env.example` (placeholder values, no real keys).

5. **Package skeleton** at `src/log_bench/`, each module with a docstring.

6. **`Method` abstract base class.** Accepts `List[LogRecord]` or raw text + a `Task`; returns `Result`: `prediction`, `input_tokens`, `output_tokens`, `total_tokens`, `latency_ms`, `gpu_seconds`, `raw_trace`. Non-negotiable contract for all methods.

7. **`CLAUDE.md`.** Project goal, the three methods, two data sources, model strategy (small-then-large), directory layout, Makefile commands, naming conventions, the `Method` contract rule, and the rule that the API key comes only from the environment.

8. **Smoke test.** Loads the client, sends "respond with OK", asserts a response with non-zero token counts. Add a second smoke test (skippable if `OLLAMA_API_KEY` unset) that hits Ollama Cloud.

**Validation:**
- `make test` and `make lint` pass
- `make ollama-status` lists Qwen 3.5 7B and answers a hello prompt
- Token counts non-zero and consistent across two identical calls
- Switching to cloud is a pure config change (no code edits) — verified by toggling `OLLAMA_API_KEY`/`OLLAMA_HOST`

---

## 4. Phase 1 — Data source A: LogHub

**Goal:** LogHub HDFS in plain and structured+trace-ID variants with anomaly labels.

**Deliverables:**
- `src/log_bench/data/loghub.py`, `trace_inject.py`, `schemas.py`, `strip.py`
- `data/processed/hdfs_{plain,otel}.jsonl`
- Notebook with dataset statistics

**Tasks:**

1. **Download LogHub HDFS** from [`logpai/loghub`](https://github.com/logpai/loghub). Use a 10k–100k block subset. Cite: Zhu, J. et al., *Loghub* (ISSRE 2023).

2. **Define the OTel LogRecord schema** (`schemas.py`) per the [OTel Logs Data Model](https://opentelemetry.io/docs/specs/otel/logs/data-model/): `timestamp`, `severity_text`, `severity_number`, `body`, `trace_id` (16-byte hex), `span_id` (8-byte hex), `attributes`.

3. **Plain loader.** Yields raw HDFS lines grouped by block-session.

4. **Structured + trace ID loader.** Per block-session: synthesize a deterministic trace ID from block ID (`md5(block_id)[:32]`), parse each line into a LogRecord, set `trace_id` on all records, emit JSONL.

5. **`strip.py`.** A shared utility that produces the plain variant from any structured variant by dropping the envelope (keep only `body`). Used by both data sources so the plain↔structured comparison is defined identically everywhere.

6. **Equivalence test.** Plain and structured carry identical message content; only the envelope differs.

7. **Anomaly labels.** Materialize `block_id, label` from LogHub's `anomaly_label.csv`. Stratified train/test split for Drain's classifier.

**Validation:**
- Loading 1k blocks < 5 s
- Plain and structured contain identical message content (test enforces)
- Labels correctly aligned (inspect 10 of each class)

---

## 5. Phase 2 — Data source B: OpenTelemetry Demo

**Goal:** Capture realistic, multi-service logs with **real OTel trace IDs** and **flag-labeled incidents** from the [OpenTelemetry Demo](https://github.com/open-telemetry/opentelemetry-demo), in plain and structured variants.

**Deliverables:**
- `infra/otel-demo/` — Helm values, Collector logs-to-file patch, flagd config
- `scripts/capture_otel_demo.py` — flag-driven capture loop
- `src/log_bench/data/otel_demo.py` — OTLP-JSON loader + windowing + labeling
- `data/processed/otel_demo_{plain,otel}.jsonl` with anomaly + root-cause labels

**Background (why this source matters):** The demo is the Astronomy Shop — ~15–20 instrumented microservices over gRPC/HTTP producing distributed traces. Its flagd feature-flag service injects controlled failures (`productCatalogFailure`, `paymentServiceFailure`, `cartServiceFailure`, `kafkaQueueProblems`, `adServiceFailure`, and more). When a flag is on, **the flag name is the ground-truth root cause**, and logs emitted during the request carry the real `trace_id`/`span_id`. This gives both anomaly labels (flag on/off) and root-cause labels (which flag) for free.

**Tasks:**

1. **Deploy the demo in Kubernetes** via its Helm chart (`open-telemetry/opentelemetry-demo`). Put overrides in `infra/otel-demo/values.yaml`. Verify the frontend, load generator, and flagd are running.

2. **Patch the OTel Collector to export logs to a file.** Add a `file` exporter to the logs pipeline so LogRecords (OTLP/JSON, including `trace_id`/`span_id` when present) are written to a mounted volume. Keep `collector-logs-file.yaml` in `infra/otel-demo/`. This file becomes the **structured + trace ID** capture.

3. **Verify log-trace correlation coverage.** Not every service injects `trace_id` into logs by default. Identify which services emit correlated logs; for the benchmark, prefer those services, or add trace-context enrichment at the Collector. Document the coverage in `infra/otel-demo/README.md`.

4. **Write the capture loop** (`scripts/capture_otel_demo.py`):
   - Ensure all failure flags are off; run the load generator; capture a baseline window of logs → label `{anomaly: normal, root_cause: none}`.
   - For each target failure flag: enable it (patch `flagd-config.json` and let flagd hot-reload, or use the flagd API); run load; capture a window → label `{anomaly: anomalous, root_cause: <flag_name>}`; disable it.
   - Window definition: fixed time buckets (e.g., 60 s) — realistic for incident triage, where an engineer inspects a time range, not a single trace. Record window start/end so logs can be sliced deterministically.
   - Save raw captures to `data/otel_demo/` with a manifest mapping window → labels.

5. **Loader** (`otel_demo.py`): parse the OTLP-JSON captures into `LogRecord` objects, group into the labeled windows from the manifest. This is the **structured + trace ID** variant.

6. **Plain variant.** Apply `strip.py` to drop the envelope — keep only message bodies. Same information, no structure. (Note: in the plain variant, the demo's multi-service interleaving with no trace IDs is exactly the hard case the thesis targets — the method must reconstruct correlation itself.)

7. **Balance the dataset.** Capture enough normal and per-flag anomalous windows for a usable F1 (aim for ≥ 50 windows per class to start; more is better). Document counts.

8. **Test** (`test_otel_demo.py`): load a fixture capture, assert windows parse, trace IDs are present in the structured variant and absent in the plain variant, and labels are attached.

**Validation:**
- Demo deploys and the load generator drives traffic
- A captured window contains real `trace_id` values in the structured variant
- Toggling `productCatalogFailure` produces a window labeled with that root cause
- Plain and structured variants of the same window carry identical message bodies
- ≥ 50 windows per class captured

**Watch out for:** flagd hot-reload timing (allow a few seconds after a flag change before capturing); load-generator warm-up (discard the first window after any change); Collector file-exporter rotation (ensure captures aren't truncated mid-window).

---

## 6. Phase 3 — Drain baseline

**Goal:** Drain-based anomaly detector. Cost-floor reference (zero LLM tokens). Works on both data sources.

**Tasks:**

1. **Wrap Drain3**; tune `sim_th`/`depth` per dataset. Verify template counts are reasonable.
2. **Classifier.** Template-occurrence feature vectors → `LogisticRegression`. Train/test split. Standard LogHub-style pipeline. For the OTel Demo, the same approach applies on its windows.
3. **Implement `Method`.** Token counts = 0; record wall-clock latency.
4. **Run on plain and structured variants** for both sources. Drain should be ~invariant to log shape (it parses bodies). Confirm this as a sanity check.
5. **Unit test** on a 100-line fixture: template count in `[5, 30]`, predictions produced.

**Validation:**
- F1 on HDFS anomaly detection ≥ 0.85
- F1 on OTel Demo anomaly detection reported (no fixed threshold — it's a new dataset)
- Latency per window < 10 ms; zero LLM calls (mock-verified)

---

## 7. Phase 4 — In-context LLM method (Qwen)

**Goal:** Qwen analyzer that processes a window in a single prompt and returns a prediction. Develop on Qwen 3.5 7B.

**Tasks:**

1. **System prompt** (short — every token recomputed; no prompt caching in Ollama by default). For anomaly detection: classify the window as `normal|anomalous`, respond as JSON. For root cause (OTel Demo): also return the most likely failing service/component.
2. **User-prompt formatter**, two variants: plain (concatenated bodies) and OTel (JSONL with `trace_id`). Both must carry the same information.
3. **Chunking** above a conservative input-token cap (e.g., 8k); aggregate chunk predictions by majority vote.
4. **Token counting** from Ollama's `prompt_eval_count`/`eval_count`; cross-check with the Qwen tokenizer via `transformers`. Flag discrepancies > 5%.
5. **GPU time** from `eval_duration` (ns → s). This is the compute-cost metric; it stays consistent if you later move to Ollama Cloud (GPU-time metered).
6. **Async `predict`** for parallel calls across Ollama replicas / cloud.
7. **Tests:** mock the client, verify prompt structure, token accounting, JSON parsing.

**Validation:**
- Single inference on a 200-line window completes in reasonable time on 7B (< 10 s at default settings)
- Token counts match Ollama exactly; tokenizer cross-check within 5%
- 10 concurrent calls all succeed

---

## 8. Phase 5 — Recursive Language Model method (Qwen root + sub)

**Goal:** Clean RLM implementation; Qwen as root orchestrator and sub-LLM. Trace-ID-aware navigation is the centerpiece. **Develop on Qwen 3.5 14B+ for reliable tool-calling**, even if other methods stay on 7B.

**Tasks:**

1. **Study the reference** (`opencode_RLM` REPL script + the RLM paper). Root LLM has a persistent Python session with `peek`, `grep`, `find_lines`, `chunk_indices`, `llm_query`, and decides what to call.
2. **REPL helpers** (`repl.py`), persistent state: `peek(start,end)`, `grep(pattern,max_matches)`, `find_lines(pattern)`, `chunk_indices(size,overlap)`, `extract_trace_ids()` ← **the punchline**, `lines_for_trace(trace_id)`.
3. **Orchestrator.** Root LLM invoked with REPL functions as Ollama tool schemas, a task, and only metadata (line count, byte size, available trace IDs) — **not** the full log. It emits tool calls; the runner executes and loops to a final answer.
4. **Sub-LLM calls.** `llm_query(prompt, chunk)` dispatches an independent Ollama call (same Qwen). Sub-call tokens accumulate into the cell total.
5. **Tool-calling format** via Ollama's tools API. Verify Qwen emits structured tool calls reliably; if < 95% across 50 sessions, fall back to prompt-engineered JSON parsing.
6. **Cycle limit** (e.g., 20 rounds) + hard `max_total_tokens_per_run`. Record rounds used per task.
7. **Demonstrate the trace-ID effect.** Plain variant: no trace IDs to grep, must navigate by content. Structured variant: `extract_trace_ids()` then per-trace sub-LLM dispatch. Log full execution traces for ≥ 3 sessions per condition on both data sources for manual inspection.
8. **Integration test** on a 5k-line window: final prediction within the cycle limit on both variants.

**Validation:**
- Completes a 5k-line window within 30 rounds
- Total tokens correctly accumulated (root + subs)
- Trace-ID-aware RLM uses meaningfully fewer total tokens than trace-ID-blind RLM on the same input
- Tool-call parse rate ≥ 95% (else fall back)

**Watch out for:** runaway loops on small models — keep the token ceiling hard and log every tool call.

---

## 9. Phase 6 — Tasks & scoring

**Goal:** Reusable task definitions and rigorous scoring.

**Tasks:**

1. **`Task` base class** with `score(prediction, ground_truth)`.
2. **Anomaly detection:** binary; F1, precision, recall. Both data sources.
3. **Root cause:** multi-class over the OTel Demo flag set (`product_catalog | payment | cart | kafka | ad | none | ...`). Exact match. OTel Demo only.
4. **Tests:** scoring matches `sklearn.metrics` on fixtures; multi-class handles missing classes.

**Validation:** F1 matches `sklearn`; root-cause scorer handles all flag labels.

---

## 10. Phase 7 — Experiment runner

**Goal:** One command runs the full matrix and logs results.

**Tasks:**

1. **Config** (`experiments/full_run.yaml`): methods × conditions × data sources × tasks. Each combination is a cell. Model is set via env (`OLLAMA_MODEL`), so the same config runs against 7B for a dry run and 32B/cloud for the real run.
2. **Cell executor.** Per cell, iterate examples, invoke method, score, write JSONL: `{cell_id, example_id, data_source, prediction, ground_truth, score, input_tokens, output_tokens, total_tokens, latency_ms, gpu_seconds, rlm_rounds}`.
3. **Concurrency.** asyncio for LLM-bound; multiprocessing for Drain. Concurrency cap respecting Ollama replica count (or cloud rate limits).
4. **Token ceiling.** `max_total_tokens_per_run` aborts if exceeded. Live telemetry every 100 examples: cell, progress, running F1, total tokens, GPU minutes.
5. **Resumability.** Skip completed cells on re-run (idempotent by output presence).
6. **Consolidation.** Merge JSONL → `results/runs/combined.parquet`.

**Validation:**
- Dry run on a 1k-example subset (7B) completes; result files well-formed
- Re-running skips completed cells
- Live telemetry prints correctly
- Switching `OLLAMA_MODEL` to a larger/cloud model needs no code change

---

## 11. Phase 8 — Analysis & results review

**Goal:** Internal review — tables and charts to understand results (not slides).

**Tasks:**

1. **Summary table** per cell `(method, condition, data_source, task)`: F1, precision, recall, mean total tokens, mean latency, mean GPU seconds, mean rounds (RLM), n.
2. **Headline chart:** total tokens per correct conclusion vs F1; color by method, shape by condition; faceted by data source.
3. **Token decomposition:** stacked bar (input + output + RLM sub-call tokens).
4. **Latency distribution:** box plot by method × condition.
5. **RLM trace-ID effect:** histogram of rounds, plain vs trace-ID, per data source.
6. **Confidence:** bootstrap 95% CI on F1 per cell.
7. **Reproducibility:** all outputs regenerate from `combined.parquet` via `make figures`.

**Validation:**
- `make figures` reproduces every PNG from a clean checkout
- Summary table complete, no NaNs
- Headline chart visibly shows whether the thesis holds — separately for LogHub and the OTel Demo

---

## 12. What we're not doing (deferred)

Out of scope for this experimental phase: slide deck, public OSS release, real-production-incident case study, USD/NOK cost reporting, demo video, multi-model comparisons beyond Qwen, local-vs-cloud as a studied variable (cloud is just a backend option here, not a benchmark axis).

---

## 13. Risk log

| Risk | Mitigation |
|---|---|
| Small Qwen unreliable at RLM tool-calling | Develop RLM on 14B+; fall back to prompt-engineered JSON parsing |
| GPU memory insufficient | Start at 7B (Q4); scale up only for final runs, or use Ollama Cloud |
| Ollama Cloud quota throttles full runs | Free tier is GPU-time metered with 5h/weekly caps — use Pro/Max for full runs, or run finals locally |
| OTel Demo log-trace correlation incomplete | Verify per-service coverage; enrich at the Collector; focus on correlated services |
| flagd hot-reload race during capture | Add delay + discard warm-up window after each flag change |
| RLM runaway token loops | Hard token ceiling + cycle limit + per-cell budget |
| Qwen 3.5 tag differs in Ollama registry | Verify exact tags in Phase 0; update config |
| LogHub download slow/blocked | Mirror locally; pin to a LogHub commit |

---

## 14. References

- He, P., Zhu, J., Zheng, Z., Lyu, M. R. *Drain: An Online Log Parsing Approach with Fixed Depth Tree.* ICWS 2017.
- Zhu, J. et al. *Loghub: A Large Collection of System Log Datasets for AI-driven Log Analytics.* ISSRE 2023.
- Zhang, A. L., Kraska, T., Khattab, O. *Recursive Language Models.* arXiv:2512.24601, MIT CSAIL, Dec 2025.
- OpenTelemetry [Logs Data Model](https://opentelemetry.io/docs/specs/otel/logs/data-model/)
- [OpenTelemetry Demo](https://github.com/open-telemetry/opentelemetry-demo) and its [feature flag system](https://opentelemetry.io/docs/demo/feature-flags/)
- [opencode_RLM](https://github.com/maclarensg/opencode_RLM) — Python RLM implementation for SRE workflows
- [logpai/Drain3](https://github.com/logpai/Drain3) and [logpai/loghub](https://github.com/logpai/loghub)
- [Ollama API docs](https://github.com/ollama/ollama/blob/main/docs/api.md) and Ollama Cloud (base URL `https://api.ollama.com`)

---

## 15. Definition of done

The experiment is complete when:

1. All cells in `experiments/full_run.yaml` have run on a final model and `results/runs/combined.parquet` exists.
2. `results/figures/summary_table.csv` reports F1, tokens, latency, GPU seconds for every `(method, condition, data_source, task)`.
3. `results/figures/headline.png` regenerates reproducibly and shows whether structured + trace IDs Pareto-dominates plain — for both LogHub and the OTel Demo.
4. RLM execution traces for ≥ 3 sessions per data source are inspected and confirmed to behave differently between plain and trace-ID conditions.
5. Results are solid enough to commit to the thesis — or honest enough to revise it.
