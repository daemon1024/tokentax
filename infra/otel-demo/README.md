# OTel Demo — native-OTLP, log-recoverable fault capture

Why: the recoverability finding (`../../REDESIGN.md`) showed real micro-fault datasets don't encode
faults in logs. Here we use the OpenTelemetry Demo (v2.2.0) but make each fault **emit a realistic
ERROR log at its origin service**, so the fault is log-recoverable *and* carries a real `trace_id`
(native OTLP) across a multi-service distributed trace — the substrate the thesis needs.

Labels come from our **capture manifest** (which flag is on), NOT from a marker in the log — so the
task is not a trivial substring match; the method must reason from realistic error text.

## How capture works (no rebuild needed)
- `otelcol-config-extras.yml` (copied into the clone's `src/otel-collector/`) adds a `file/capture`
  exporter to the collector's **logs** pipeline → writes OTLP-JSON LogRecords (trace_id/span_id
  included; `transform/sanitize_logs` only touches an `otelcol.signal` attr, verified) to `/capture`.
- `compose.capture.yaml` mounts `data/otel_demo/` → `/capture`.
- Run from the clone:
  `docker compose -f compose.yaml -f <repo>/infra/otel-demo/compose.capture.yaml up -d`

## Faults (16 flags in src/flagd/demo.flagd.json)
**Already log at origin (capture-first, no patch):**
- `paymentFailure` — payment (JS) throws `Error('Payment request failed. Invalid token...')`.
- `kafkaQueueProblems` — checkout (Go) `logger.Info("...overloading queue now")` at origin.
- `llmRateLimitError`, `paymentUnreachable` — verify on capture.

**Span-only today → patch + rebuild to add a realistic origin ERROR log:**
- `productCatalogFailure` — Go, `src/product-catalog/main.go` GetProduct (~L362-410). Add
  `log.Error("failed to retrieve product <id>: catalog lookup error")` with `ctx` (trace attaches).
- `cartFailure` — .NET, `src/cart/.../CartService.cs` ~L83 catch. Add
  `_logger.LogError(ex, "cart store unavailable for user {UserId}", request.UserId)`.
- `adFailure` — Java, `src/ad/.../AdService.java` ~L164. Add `logger.error(...)` at the fault.
Patched services must be rebuilt: `docker compose up -d --build product-catalog cart ad`.

## Capture loop (scripts/capture_otel.py — to build once stack is up)
1. all flags off → drive load (load-generator runs automatically) → capture a baseline window →
   label `{anomaly: normal}`.
2. for each target flag: set it on via flagd (edit `src/flagd/demo.flagd.json` defaultVariant +
   hot-reload, or the flagd-ui API), wait for warm-up, capture a 60s window → label
   `{anomaly: anomalous, fault: <flag>}`, set off.
3. window = file slice by timestamp; write a manifest mapping window → label.

## Validate recoverability BEFORE trusting it (the lesson from Nezha)
After a first capture, run the same offline check we ran on Nezha: for each fault window, does the
origin service actually emit a trace-correlated ERROR LogRecord, and is the culprit distinguishable
from baseline noise? Only keep flags that pass.
