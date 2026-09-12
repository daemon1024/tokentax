# rca-lab, measured: the errors are in the spans, not the logs

> [!CAUTION]
> **PARTIALLY RETRACTED the same day, by the author.** The capture below was taken with **no scenario
> active**. The scenario operator never installed — `make deploy` aborts at the app-rollout wait
> because `order-service` cannot pull an arm64 image, and the operator step runs after it — so
> `kubectl get maintenancejobs` returns nothing and the maintenance CRD does not exist. The 322 log
> records are **ambient baseline traffic**, not an injected fault.
>
> The load-generator's 10.1% error rate is its own client-side view of 4xx/5xx responses; it does not
> mean a fault was injected.
>
> This invalidates the central claim below. `product-catalog:142` already contains
> `slog.ErrorContext(r.Context(), "recommendations rpc failed", "error", err)` — trace-correlated, on
> the request span, and exactly the symptom line sc-10 is designed to produce. `fulfillment-service`
> has four more `ErrorContext` sites with request context. **These call sites have never fired.**
>
> What still stands, because it does not depend on a scenario: the per-service source facts
> (`review-service`, `cart-service` and `recommendation-service` genuinely do not log request-path
> errors), `api-gateway` exporting zero records despite correct configuration, the 3.1% trace_id
> coverage on the records that did arrive, and both instrumentation predictions.
>
> What does NOT stand: "the log-only comparison cannot be run here", and the 680x error-span-to-
> error-log ratio as a statement about rca-lab under fault. Neither was tested. Re-measure with
> sc-10 active before citing anything here.


**This is the finding that ends the log-only framing.** rca-lab was the best candidate found — the
only source meeting all six requirements on paper (`RCA_LAB_EVALUATION.md`). Deployed and captured,
its logs are nearly empty while its traces are rich. The project's independent variable barely exists
in the signal the project reads.

Capture: kind cluster `rca-lab`, `SINGLE_NODE=1 SEED_SIZE_GB=0`, 47 pods, continuous load-generator
traffic at a self-reported **10.1% error rate** (442,352 requests / 44,895 errors). Telemetry
forwarded from the lab's collector to a host-side collector on the `kind` network, written as OTLP
JSON by the file exporter, parsed with the repo's own `otel_loader.parse_otlp_jsonl`.

## The measurement

| | logs | traces |
|---|---|---|
| records captured | **322** | 187,487 spans (120 MB sample) |
| carrying an error | **6 ERROR + 6 WARN** | **4,107 error-status spans (2.2%)** |
| carrying `trace_id` | **10 of 322 (3.1%)** | n/a |
| ERROR records with `trace_id` | 2 of 6 | n/a |

Roughly **580× more spans than log records**, and about **680× more error spans than error logs**.
Over an hour of sustained failing traffic the entire cluster produced six error log lines.

Log records by service: `load-generator` 271 (INFO statistics lines), `payment-service` 21,
`fulfillment-service` 20, `product-catalog` 4, `review-service` 4, `recommendation-service` 2,
**`api-gateway` 0**.

## Why, service by service — verified in source, then confirmed in the capture

The applications do not log their error paths. This is not a misconfiguration:

- **`product-catalog`** returns `writeError(w, 500, fmt.Sprintf("query error: %v", err))` — the error
  goes into the HTTP body, never to a logger. Its one request-path ERROR site is
  `slog.ErrorContext(r.Context(), "recommendations rpc failed", ...)`.
- **`review-service`** — all six route handlers end `catch (err) { res.status(500).json({error: err.message}) }`.
  Zero request-scoped logging. Its only `logger.error` is a boot-time Mongo connect failure.
- **`cart-service`** — zero logger calls in the whole service.
- **`recommendation-service`** — `GetRecommendations` has no logging at all.
- **`api-gateway`** logs ERROR only on *transport* failures (connect/timeout/protocol). A downstream
  returning a well-formed 500 produces an INFO line reading `... (status 500)`.

**`api-gateway` exported nothing despite being configured correctly.** Its pod has `envFrom` the
`otel-env` ConfigMap carrying `OTEL_LOGS_EXPORTER=otlp`,
`OTEL_PYTHON_LOGGING_AUTO_INSTRUMENTATION_ENABLED=true` and
`OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4317`, and it runs under `opentelemetry-instrument`.
It logs to stdout continuously. Not one record reached the collector. Traces from the same process
arrived throughout. Correct configuration is not sufficient for log export; it is for traces.

## Two predictions from source analysis, one right and one wrong

Before capture, a source-level pass predicted which services would lose trace context on error paths.
Recording both outcomes:

- **Right:** `fulfillment-service` errors arrive with an **empty `trace_id`** — its
  `slog.Error("Fetch error", ...)` sits in a background consume-loop goroutine with no request
  context, exactly as predicted.
- **Wrong:** `payment-service` (Rust) was predicted to have empty `trace_id` on *every* record
  because its appender lacks `experimental_use_tracing_span_context`. In the capture both of its
  ERROR records **do** carry a `trace_id`. The prediction was plausible, specific, and false — which
  is why it was worth capturing rather than reasoning about.

## What this means for the project

**The log-only comparison cannot be run here, and the reason is not fixable by choosing a different
scenario.** A benchmark needs error lines to navigate. This cluster produces six an hour, of which
two carry trace context. No scenario toggle changes the fact that four of the eleven services never
log their failures.

**It also generalises the pattern seen everywhere else.** RCAEval RE2: a CPU-stress case with 171k
log lines and zero error lines. Nezha OnlineBoutique: 5 of 14 log-visible windows contain any error.
OpenRCA Bank/Market: GC and access logs. `data/otel_demo`: errors exist only because
`infra/otel-demo/` patched a `logger.error` in by hand. Every time this project has gone looking for
error logs in a modern instrumented system, it has found spans instead.

**The honest reframing.** Errors in an OTel-instrumented system live in span status, not log text.
That is not a defect of rca-lab — it is what the instrumentation is for, and `expectedSymptoms`
across the scenario library is written in terms of latency, saturation and status, not log messages.
A project asking "does trace context make log analysis cheaper" is asking about the wrong signal.

The comparison worth running on this data is **logs versus spans**, not logs with and without a
`trace_id` field:

- arm P: logs only — grep/peek over 322 records, of which 6 are errors
- arm S: span tree — 187k spans with parent/child, service, status and duration

That is a different and more defensible question, and this capture already suggests the answer is
lopsided. It is also the question an OpenTelemetry audience would actually ask.

## Reproducing

```bash
kind create cluster --name rca-lab
cd rca-lab && make deploy SINGLE_NODE=1 SEED_SIZE_GB=0 YES=1
docker run -d --name tokentax-capture --network kind --ip 172.18.0.250 \
  -v "$PWD/rcalab-capture-collector.yaml:/etc/otelcol/config.yaml:ro" \
  -v "$HOME/tokentax-capture:/capture" \
  ghcr.io/open-telemetry/opentelemetry-collector-releases/opentelemetry-collector-contrib:0.158.0 \
  --config=/etc/otelcol/config.yaml
make otel OTLP_ENDPOINT=172.18.0.250:4317 OTLP_SIGNALS=traces,logs
```

**Two things that will bite anyone repeating this.** rca-lab publishes **linux/amd64 images only**;
on Apple Silicon every app pod is `ImagePullBackOff` with "no match for platform in manifest" and all
11 services must be rebuilt locally (10 of 11 build clean; `order-service` needs a reliable network
path to the OpenTelemetry Java agent release asset). And `make deploy` aborts at the app-rollout wait
*before* installing the scenario operator, so `kubectl get maintenancejobs` returns nothing until the
images resolve — the scenario library is not available until every deployment goes Ready.

Trace capture writes ~3 GB/hour; forward `OTLP_SIGNALS=logs` alone unless spans are being analysed.
