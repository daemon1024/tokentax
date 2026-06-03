# CLAUDE.md — tokentax

**Goal.** Benchmark whether OpenTelemetry trace context is "free input compression" for AI log
analysis: a trace-aware Recursive Language Model that greps `trace_id` and reads per-trace slices
should reach a conclusion in far fewer tokens than reading the whole window, at equal-or-better
accuracy. `BENCHMARK_PLAN_v3.md` is the source of truth (supersedes `BENCHMARK_PLAN.md` v2).

**Status (2026-06-03).** Source decided + validated on real bytes. Building the infra-free slice
(Phase 0 + 1 + 3 Drain + 6 scoring); LLM methods (Phases 4-5) gated on a running Ollama.

## Decision trail (read in order)
`REVIEW.md` → `DATA_SOURCE_B.md` → `SOURCE_DECISION.md` → `GATE_RESULTS.md` → `BENCHMARK_PLAN_v3.md`.

## Methods (3) & the model rule
Drain (0 tokens), in-context LLM, RLM (trace-aware). **`model` is a property of a RUN, not a method** —
every method on a cross-method facet shares one `OLLAMA_MODEL` (no 7B-vs-27B confound).

## Data — Nezha, BOTH systems, one pipeline (no infra)
`data/raw/Nezha/` (sparse git clone). Train Ticket (`2023-01-29/30`) + Online Boutique (`2022-08-22/23`).
Log CSV per minute = one window; `TraceID`/`SpanID` columns at 100% coverage. The `Log` field is a JSON
envelope — Train Ticket inner is plain text, Online Boutique inner is `{"message","severity"}` JSON.
Three conditions from one source: **plain** (body, ids scrubbed) / **structured** (OTLP-JSON +ids) /
**structured-no-trace** (OTLP, ids dropped). LogHub and the OTel Demo are NOT used (dropped / optional).

## Tasks (2)
1. Root-cause / culprit-service localization (multi-class, 38 log-visible episodes / 12 services, bootstrap CIs).
2. Trace-anomaly localization (binary, 31,142 balanced (window,trace) pairs; label = trace touches `inject_pod`).
Window-binary-anomaly is demoted (ERROR logs pervade normal windows — volume carries no fault signal).

## Metrics
`total_tokens = Σ(prompt_eval_count + eval_count)` over every call (RLM: root + subs + tool feedback).
`gpu_seconds = Σ(prompt_eval_duration + eval_duration)/1e9` (LOCAL only). `temperature=0`, fixed `seed`,
explicit `num_ctx`. Headline x = `cost_per_correct = Σtotal_tokens / count(correct)`.

## Conventions
Package `src/tokentax/`. Run via venv: `.venv/bin/python`. `make data` (gates), `make drain` (baseline),
`make test`, `make lint`. **`Method.predict(window, task) -> Result`** is the non-negotiable contract
(`Result`: prediction, input/output/total tokens, latency_ms, gpu_seconds, rlm_rounds, aborted, raw_trace).
**API key from the environment only**, never code/args. tiktoken `cl100k_base` is a token PROXY; a
Qwen-tokenizer cross-check is a Phase-4 step.

## Pre-registered decision rule
Token effect size (structured-RLM ≤ X% of in-context-plain cost_per_correct) + F1 non-inferiority (≥ −δ via
bootstrap CI). Primary confirmatory cell = RLM on trace-anomaly, structured vs plain.
