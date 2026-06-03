# OTel Demo — log-recoverable dataset (the accuracy axis, finally)

Native-OTLP capture from the patched OpenTelemetry Demo v2.2.0. Unlike Nezha, the fault is
**recoverable from logs**: the origin service emits a trace-correlated ERROR log when its fault fires.

## Recoverability check (`scripts/check_otel_recoverability.py`)
6 windows (3 normal + 3 `productCatalogFailure`), ~3,000–3,700 records each:

| class | recs | traces | errors | error service | error-traces |
|---|---|---|---|---|---|
| anomalous | 2,872–3,655 | ~1,800 | 34–54 | **product-catalog (origin), 100%** | 34–54 |
| normal | 3,406–3,499 | ~1,950 | 0–1 | (none / 1 otelcol internal) | 0 |

**Verdict: `productCatalogFailure` → origin `product-catalog` emits ERROR in 3/3 anomalous, 0/3
normal → RECOVERABLE ✓**

## Why this beats Nezha
- Nezha: culprit silent in 26/38 windows; anomalous vs normal traces both 0.06 errors/trace.
- OTel Demo (patched): culprit emits the error in every anomalous window; normal windows are clean;
  the ~50 error-traces among ~1,800 ARE the affected requests — a clean, recoverable label.
- Bonus: ~1,800 concurrent multi-service traces/window (even richer than Nezha) + native OTLP
  trace_id (not a CSV mapping) + the find-the-failed-requests task is the trace-navigation sweet spot.

## Method
- Collector file exporter (`infra/otel-demo/otelcol-config-extras.yml`) writes OTLP-JSON LogRecords.
- Origin-error patch (`infra/otel-demo/patches/product-catalog-origin-log.patch`): a trace-correlated
  `logger.Error` at the fault site (otelslog attaches trace_id from ctx).
- `scripts/capture_otel.py` toggles flagd, records labeled windows → `data/otel_demo/manifest.json`.
- `otel_loader.windows_from_manifest` slices the stream into `LabeledWindow`s on the shared LogRecord.

## Next
- Expand faults: patch + rebuild cart/payment/ad for a multi-class root-cause set.
- Run Drain / in-context / RLM on this dataset — the accuracy axis is now well-posed.
- Tasks: (a) find-failed-request-traces (recoverable, navigation-favoring), (b) culprit-service.
