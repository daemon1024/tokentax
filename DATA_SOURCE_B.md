# Data Source B — Selection & Design

## Recommendation

**PRIMARY: Nezha (FSE 2023, IntelligentDDS).** It is the *only* candidate where the load-bearing property was verified from the raw data bytes, not docs: dedicated `TraceID`/`SpanID` columns at **100% coverage** (24,841/24,841 log rows in one window), **497 distinct interleaved traces per 1-minute window** across two real microservice systems (Online Boutique + Train Ticket), and code-faults that emit trace-correlated ERROR logs — a single MIT `git clone`, zero capture infra, no K8s/flagd. This is precisely the multi-concurrent-trace + real-trace-id-in-logs + log-visible-fault regime where a trace-aware RLM can demonstrably win on tokens, and it is the property the OTel Demo failed and LogHub HDFS structurally lacks (one block = one trace, `extract_trace_ids()` is a no-op per THESIS-2).

**FALLBACK: minimally-patched OpenTelemetry Demo (Docker Compose).** Verified correlation `confirmed` (9+ services across 6 languages emit genuine OTLP LogRecords with auto-populated `trace_id`, collector logs pipeline is OTLP-only so correlation is true by construction), giving a *natively-OTLP* arm Nezha lacks — at the cost of a ~5–10-line `logger.Error` patch series to make span-only faults log-visible.

We use **both**: Nezha as the primary confirmatory cell (no build risk, real trace IDs), the patched OTel Demo as the native-OTLP secondary that defends against "Nezha is CSV-not-OTLP" reviewer objections.

## Requirements scorecard

| Candidate | log↔trace corr | trace richness | log-visible faults | OTLP pipeline | reprod | low leakage | build effort⁻¹ | research cred | **VERIFIED corr** |
|---|---|---|---|---|---|---|---|---|---|
| **Nezha** | 5 | 5 | 3 | 2 | 5 | 4 | 4 | 5 | **confirmed** |
| **OTel Demo (patched)** | 5 | 5 | 3 | 5 | 4 | 3 | 4 | 5 | **confirmed** |
| **Train Ticket (DeepTraLog)** | 4 | 5 | 4 | 2 | 4 | 3 | 2 | 5 | **confirmed** |
| Custom app | 5 | 4 | 5 | 5 | 5 | 5 | 2 | 2 | confirmed (mechanism only) |
| Vendor/Grafana MLTP demos | 4 | 4 | 2 | 2 | 5 | 3 | 3 | 2 | confirmed (body-substring only) |
| DeathStar/SockShop/Boutique | 1 | 4 | 1 | 1 | 3 | 3 | 2 | 4 | **refuted** |

**Takeaway:** Only Nezha pairs a *verified-from-data* 100% trace-in-logs property with zero build risk; the OTel Demo matches it on correlation and beats it on native-OTLP shape but needs fault patches; everything else is either refuted (the three classic demos), high-effort-to-build (Train Ticket, custom app), or not turnkey/not-citeable (vendor demos).

## Why not the others

- **DeathStarBench / Sock Shop / Online Boutique** — `correlation_verdict: refuted`. Primary code shows trace_id is absent from log records in all three: DeathStarBench's Boost.Log pattern `"[%TimeStamp%] <%Severity%>: %Message%"` and its Jaeger tracer are fully decoupled (`logger.h`/`tracing.h`); Online Boutique's logrus emits only timestamp/severity/message with a TRACE-only `otlptracegrpc` exporter; Sock Shop is archived with at-best non-default Zipkin MDC. Fails rubric #1 outright.
- **Train Ticket (DeepTraLog)** — `correlation_verdict: confirmed` but **`otlp_log_pipeline: 2`, `build_effort_inverse: 2`**. The shipped data is SkyWalking `SW_CTX` text + ES, not OTLP LogRecords; the OTLP path requires standing up ~40 polyglot services and hand-wiring per-language log correlation for the Node/Python/Go third (weeks). RCAEval is *not* a fast path (verified: `logs.csv` = `time,timestamp,container_name,message,level,req_path,error`, no trace_id). Strong **secondary candidate if a deeper-topology native-OTLP source is later needed**, but build cost rules out primary.
- **Custom app** — `confirmed` only at the *mechanism* level (the app does not exist); `research_credibility: 2` (bespoke/synthetic, reviewers can object the author engineered logs that flatter trace-navigation) and `build_effort_inverse: 2` (~3–7 days). When a verified pre-built dataset with the identical property exists (Nezha), building one is unjustified effort and weaker credibility.
- **Vendor/community demos (Grafana MLTP, blueswen, Honeycomb)** — `confirmed` but trace_id is a **body substring**, not an OTLP LogRecord field (Grafana pushes straight to Loki; `otel.yml` has no `logs:` pipeline), and only a **single random fault**. `research_credibility: 2` (teaching demos, bespoke after forking). Honeycomb's demo was caught *failing* correlation (stdlib `logging`, bare `flask run`). Best as a fork-base, not a source.

## Recommended design (detailed) — Nezha as primary

**Source.** `git clone https://github.com/IntelligentDDS/Nezha` (MIT, © 2023 IntelligentDDS; cite *Yu et al., "Nezha", ESEC/FSE 2023*, [doi:10.1145/3611643.3616249](https://dl.acm.org/doi/abs/10.1145/3611643.3616249)). **No capture infrastructure, no Docker, no K8s, no flagd** — the data is git-tracked in-repo (303 per-minute log CSVs across 4 days). This eliminates Phase 2's entire deploy/capture/toggle burden and sidesteps every OTEL-5/OTEL-1 blocker from the REVIEW.

**Files & format** (verified schema):
- `rca_data/<DATE>/log/<HH_MM>_log.csv` — header exactly `Timestamp,TimeUnixNano,Node,PodName,Container,TraceID,SpanID,Log`. `TraceID` (32-hex), `SpanID` (16-hex) at **100% coverage**; trace_id is *also* redundant in the `Log` body (`"message":"TraceID: <id> SpanID: <id> ..."`).
- `rca_data/<DATE>/trace/<HH_MM>_trace.csv` — header `TraceID,SpanID,ParentID,PodName,OperationName,StartTimeUnixNano,EndTimeUnixNano,Duration` (full span tree; 100% of log trace_ids resolve to spans here).
- `rca_data/<DATE>/<DATE>-fault_list.json` — per-episode ground truth `{inject_time, inject_timestamp, inject_pod, inject_type}`.
- `construct_data/root_cause_hipster.json`, `root_cause_ts.json` — inner-service code-region root-cause labels.
- Systems: `2022-08-22`/`08-23` = Online Boutique (10 services); `2023-01-29`/`01-30` = Train Ticket (Java/Spring).

**Window → label mapping** (replaces Phase 2 Task 4–7 capture loop with a pure offline windowizer, `src/log_bench/data/nezha.py`):
1. Each per-minute CSV *is* a window — deterministic, re-runnable, no warm-up/hot-reload races.
2. Join `fault_list.json` inject timestamps to windows: a window overlapping an inject episode → `{anomaly: anomalous, root_cause: <inject_pod>, fault_type: <type>}`; non-fault windows → `{anomaly: normal}`.
3. **Hard capture gate (satisfies REVIEW OTEL-1 / LEAK-4):** retain an anomalous window only if it contains ≥1 ERROR/anomaly-bearing LogRecord. Verified true for `exception`/`return` faults (e.g. window 04_19, exception injected 04:18:35 → 24 ERROR rows `error:"failed to complete the order"`, each carrying trace_id), **false for the metric faults** — see below.
4. **Scope the log-visible class set to `exception` + `return`** (~38/101 episodes). Bucket `cpu_contention`/`cpu_consumed`/`network_delay` (63 episodes, **zero ERROR logs**, verified) into an explicit **"metrics-only" floor class** exactly as REVIEW OTEL-2 mandates. Root-cause-from-logs is scoped to **service-level** (the `exception` vs `return` types are *not* separable from log text — both render as generic errors), so report root cause as "which pod," not "which fault type."

**OTLP variant production (reuse `strip.py`).** Nezha is CSV; write one mechanical `csv→OTLP-JSON LogRecord` map (`src/log_bench/data/nezha.py::to_otlp`): `TimeUnixNano→timeUnixNano`, `TraceID→traceId` (hex), `SpanID→spanId` (hex), body severity→`severityText`/`severityNumber` (ERROR=17), `Log→body.stringValue`, `PodName`/`Container`/`Node`→resource attributes. Then:
- **structured** = the OTLP-JSON LogRecords (with `traceId`/`spanId`).
- **plain** = `strip.py` keeps only `body.stringValue`.
- **structured-no-trace** (the THESIS-3 condition the REVIEW demands to isolate trace IDs) = OTLP envelope with `traceId`/`spanId` fields dropped.

**Anti-leakage (verified favorable).** Fault-type label strings (`exception`/`return`/`cpu_contention`) appear **0 times** in log bodies in the fault windows — error messages are generic (`"product id not specified"`, `"failed to complete the order"`), so root-cause-from-logs is *not* a trivial substring match. **One mandatory scrub:** trace_id appears verbatim in both the column AND the body, so `strip.py` must strip it identically from the body in the plain/structured-no-trace variants, or the comparison leaks the ID through the body. Pre-commit an any-ERROR-regex baseline (LEAK-4) and a majority-class baseline (LEAK-3).

**Concurrency guarantee (the RLM punchline, verified).** 497 distinct interleaved trace_ids per window, 461 spanning >1 service, avg 5.32 services/trace → `extract_trace_ids()` returns ~500 IDs and `lines_for_trace()` does real selective work. **Must measure tokens/window** (~25k records/window is large) to confirm windows exceed the RLM context budget (REVIEW RLM-3 crossover ~2¹⁴ tokens) so in-context is forced to chunk and RLM navigation is non-vacuous.

**Fallback design — patched OTel Demo (only if a native-OTLP arm is required):** fork at a pinned tag, Docker Compose (avoids the K8s flagd blocker OTEL-5); add a 3-line OTLP-JSON file exporter to `otelcol-config-extras.yml`; **keep** the log-visible-today flags `llmRateLimitError` (product-reviews `logger.error`) and `kafkaQueueProblems` (fraud-detection, leaky — redact or anomaly-only); **patch** the span-only sites (`product-catalog` `GetProduct`, `payment` `charge` catch) with one-line `logger.Error` each. **Drop** the verified-false claim that `cartFailure` drives a Redis `LogError` (it routes to `_badCartStore`, records on the Activity only). Read flag names from a pinned `demo.flagd.json` (OTEL-4).

## Should we keep LogHub and/or the OTel Demo at all?

**Final source lineup (3 arms):**
1. **LogHub HDFS** → **keep, but demoted** to *scale + envelope-tax + Drain baseline only*. Per THESIS-2 its synthetic trace_id is constant per window (one block = one trace), so `extract_trace_ids()` is a no-op and RLM trace-navigation is structurally impossible there. Use it for the established Drain F1 baseline (≥0.85), the per-line envelope-tax measurement (`tokens(structured) − tokens(body)`), and scale — **never** as a trace-navigation arm. Report HDFS as *descriptive only* (its 2.93% base rate saturates F1 per LEAK-3).
2. **Nezha** → **new PRIMARY trace-aware arm.** Carries the real multi-concurrent-trace + trace-in-logs property. This is the primary confirmatory cell (RLM on anomaly detection over real interleaved trace IDs).
3. **Patched OTel Demo** → **demoted from primary to native-OTLP secondary.** Defends the "genuine OTel envelope" requirement and provides controllable live faults; not load-bearing for the headline.

## Integration: changes to BENCHMARK_PLAN

**Phase 2 (§5) — rewrite from "deploy + capture" to "ingest + windowize":**
- Replace §5 Goal and the entire deploy/Helm/flagd capture pipeline (Tasks 1–4, lines 266–277) with: *clone Nezha; write `nezha.py` (CSV loader + per-minute windowizer + `fault_list.json` join + `csv→OTLP-JSON` map)*. Delete `infra/otel-demo/` from the critical path (move to the optional fallback).
- §5 Background (lines 262): delete the `productCatalogFailure`-is-root-cause framing (OTEL-1) and the renamed-flag list (OTEL-4); replace with Nezha's `exception`/`return`/metric fault taxonomy and the service-level root-cause scoping.
- §5 Task 6 (line 280): `strip.py` now also produces the **structured-no-trace** variant (THESIS-3), and **must scrub trace_id from the body** (Nezha-specific leakage).
- §5 Task 7 (line 282): the ≥50-windows/class target applies to the **audited log-visible set** (`exception`+`return`, service-level) only; metric faults are an explicit floor class (OTEL-2). Empirically verify per-class counts (20 exception + 18 return across 4 days — confirm splittable ≥50/class per system, open question).
- §5 Validation (lines 287–292): delete *"Toggling `productCatalogFailure` produces a window labeled with that root cause"*; add *"every retained anomalous window contains ≥1 ERROR LogRecord carrying a populated trace_id"* and *"`extract_trace_ids()` returns ≥100 distinct IDs per window."*
- §5 "Watch out for" (line 293): replace flagd/file-rotation warnings (now moot) with: *CSV body JSON-parse failures (`<parse_fail>` rows) — confirm the `TraceID` column is still populated and the windowizer keeps them.*

**Ripple — §1 data table (lines 68–71):** replace the OTel Demo row with **Nezha** (Real OTel-equivalent trace context via instrumented MDC; Anomaly + service-level root cause). Mark HDFS trace IDs explicitly "synthetic, constant-per-window — no navigation."

**Ripple — §9 Phase 6 Task 3 (line 370):** root-cause classes become **Nezha pods** (Online Boutique / Train Ticket services), exact-match at service level, with a `metrics-only` bucket — not the OTel flag set.

**Ripple — §8 Phase 5 Task 7 (line 349):** "demonstrate the trace-ID effect" now runs on Nezha windows (real ~500-trace interleaving), not OTel Demo captures.

**Ripple — §11 Phase 8 / §15 DoD (lines 415, 459):** the Pareto headline is expected **from Nezha** (the trace-aware arm); HDFS is the envelope-tax/cost axis. The primary confirmatory cell (REVIEW SEQ-5) = **RLM on Nezha anomaly detection**.

**§2 file tree:** add `src/log_bench/data/nezha.py`; `scripts/capture_otel_demo.py` and `infra/otel-demo/` move to optional-fallback status.

## Risks & what still needs LIVE verification

Verified-from-data (high confidence, no live step needed): 100% trace_id coverage, 497 traces/window, exception/return ERROR logs, metric faults emitting zero error logs, zero fault-name leakage in bodies. Remaining gates:

1. **OTLP round-trip fidelity** — confirm the `csv→OTLP-JSON` map round-trips cleanly (severity→`severityNumber`; ns `TimeUnixNano`; resource attrs) and that `strip.py`'s plain output is information-equivalent except envelope+IDs. *Mechanical, but untested.*
2. **Per-window token distribution** — measure tokens/window (~25k records is large) to confirm at least one condition exceeds the RLM context budget (RLM-3 crossover ~2¹⁴), else RLM is structurally dominated and the win is vacuous.
3. **Per-class log-visible window counts** — confirm `exception`+`return` yield ≥50 windows/class per system after the train/test split (20+18 episodes total across 4 days; need to verify the splittable count).
4. **`<parse_fail>` body rows** — verify the windowizer retains them with populated trace_id (the column is populated even when body JSON fails to parse — likely fine, confirm).
5. **Normal-window balance** — confirm `construct_data` (fault-free phase) supplies enough NORMAL windows to balance the anomaly base rate (LEAK-3 discipline).
6. **(Fallback only)** If the OTel Demo arm is built: live coverage probe asserting non-empty trace_id per service/flag (especially the unverified **Java-agent** ad/fraud-detection and **.NET** accounting paths), and confirm patched `logger.Error` sites emit trace-correlated ERROR LogRecords (THESIS-6 exit gate).