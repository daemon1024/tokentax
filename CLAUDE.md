# CLAUDE.md — tokentax

> **Read `WITHDRAWAL.md` first.** The pre-registered claim was withdrawn on 2026-08-20; the headline
> result in `results/` is an artifact of a tool given to one arm. This file describes the repo as it
> actually is, not as `BENCHMARK_PLAN_v3.md` planned it.

**Question.** Does OpenTelemetry trace context act as free input compression for AI log analysis — can a
trace-aware navigator reach the same conclusion for materially fewer tokens than reading the whole window?
**Status: open.** The only tool-matched measurement in the repo
(`results/runs/rlm_compare_matched_tools.jsonl`) is a *null* — structured cost slightly more than plain at
equal accuracy. The question has never faced a clean test.

## Status (2026-08-20)

Dormant since 2026-06-05 (48 commits). Being restarted. `make test` passes (20 tests).
`make data` and `make drain` **crash** — they target `data/raw/Nezha/`, which is not on disk.
`import tokentax` fails outside pytest; the package was never installed into `.venv`
(pytest's `pythonpath=["src"]` is what makes tests work).

## What the data actually is

`data/otel_demo/` — 391 MB, **gitignored, one machine, no backup, not reproducible**. Captured from a
locally patched OpenTelemetry Demo v2.2.0 via `infra/otel-demo/`. Manifests key windows by absolute
wall-clock nanoseconds.

**Nezha is not present.** The project pivoted to the OTel Demo on ~2026-06-03 and no document records the
decision — `REDESIGN.md` recommends injection onto *Nezha* traces; the code went elsewhere. Treat
`BENCHMARK_PLAN_v3.md`, `SOURCE_DECISION.md` and `DATA_SOURCE_B.md` as history, not as the current plan.

**The labels are constructed.** `infra/otel-demo/` patches a hand-authored `logger.error` into each
fault-origin service, so the culprit is the only erroring service in 9 of 9 anomalous windows. This makes
the dataset a legitimate **control** (a known-recoverable signal for measuring cost) and an illegitimate
basis for accuracy claims. `infra/otel-demo/README.md`'s claim that labels are "NOT from a marker in the
log" is wrong.

## Decision trail (historical, in order)

`REVIEW.md` → `DATA_SOURCE_B.md` → `SOURCE_DECISION.md` → `GATE_RESULTS.md` → `BENCHMARK_PLAN_v3.md` →
`REDESIGN.md` → **`WITHDRAWAL.md` (current)**.

## What survives

1. **Envelope tax** — OTLP-JSON costs 1.47–2.19× plain tokens to read the same content.
2. **Compression handle** — fault signal is 0.02–0.34% of a ~1.07M-token window.
3. **Recoverability finding** (`results/RCA_RECOVERABILITY.md`) — the best result here. In Nezha the
   injected service emits any ERROR in 12/38 windows and is named in the failure text in 2/38. Real
   micro-fault datasets largely do not encode their labels in logs.
4. **Negative engineering results** — `deepseek-v2:16b` cannot drive the Ollama tools API; format alone
   does not rescue an 8B on a 70k-token window.

## What does not survive

Every plain-vs-structured token and accuracy claim in `results/MATRIX_*.md`, `RLM_COMPARISON.md`, and the
condition contrast in `RECURSIVE_RLM.md`. All carry correction banners. `gpu_seconds` is hardcoded to `0.0`
in both LLM methods and was never measured.

## Hard rules for any successor experiment

- **Matched tool capability across arms is a precondition, not a nicety.** If one arm gets an aggregator,
  every arm gets an equally powerful one. Adding a task-specific tool to one arm measures the tool.
- **No mid-run parameter changes.** Timeouts, round caps and budgets are fixed before the first cell.
  If a run must be restarted with different settings, it is a *new* run with a new output file.
- **Failures are data.** A timeout is a censored observation, never `total_tok=0` folded into a mean.
  Report the failure rate separately and state which cells the means cover.
- **Pre-register, then run.** The metric you commit to is the metric you compute. `cost_per_correct` must
  exist in code before it appears in a document.
- **Vary one thing.** `structured` currently changes service name, severity, `trace_id` *and* the tool set
  at once. `structured_no_trace` (`nezha.py:270`) is built, tested, and never run — it isolates the actual
  hypothesis.
- **Scrub identity from the message TEXT, not just the field.** Instrumentation writes trace context and
  service name into the body, where dropping a column cannot remove it: Train Ticket logback emits
  `TraceID: <hex> SpanID: <hex>`, and OTel logging emits `otelTraceID=` / `otelSpanID=` /
  `otelTraceSampled=` / `otelServiceName=`. `LogRecord.body()` removes both families and every arm goes
  through it. Before trusting any new source, measure the residual: a hex-token scan over the rendered
  `plain` lines must return zero. On `data/otel_demo` the otel* form was on 15.3% of records and went
  unmatched until 2026-09-11 (no ERROR line leaked, so published results stand).

## Conventions

Package `src/tokentax/`. Run via venv: `.venv/bin/python`. `make test`, `make lint`.
`Method.predict(window, task) -> Result` is the *intended* contract but is currently dead code — nothing
subclasses it, and four methods return three result types. Fix or delete it before adding a fifth.
**API keys from the environment only**, never in code or args. tiktoken `cl100k_base` is a token PROXY;
a real-tokenizer cross-check remains outstanding.

**Provenance is not optional.** There is no git remote. Push before doing anything else.
