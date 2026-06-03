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

## Multi-fault dataset (3 culprit services)
Patched + rebuilt **product-catalog (Go), ad (Java), cart (.NET)** to emit trace-correlated origin
ERROR logs. Captured 12 windows (3 normal + 3 per fault), ~5,400 records / ~3,000 traces each.

**Recoverability: all three RECOVERABLE ✓** — origin emits ERROR in 3/3 anomalous, 0/3 normal:
| fault | origin | errors/window | err-traces |
|---|---|---|---|
| productCatalogFailure | product-catalog | 71–82 | 71–82 |
| cartFailure | cart | 2–12 (sparse: checkout-gated) | 1–6 |
| adFailure | ad | 4–6 (1/10 of ad reqs) | 4–6 |
| (normal) | — | 0–1 (otelcol internal) | 0 |

**Drain results (`scripts/run_otel_drain.py`, 0 tokens):**
- find-failed-traces (binary): **F1 1.000** (any-ERROR baseline 1.000) — recoverable.
- root-cause / culprit-service (3-class, 250 affected traces): **acc 1.000, macro-F1 1.000** vs
  majority macro-F1 0.474 — Drain genuinely localizes the culprit, the axis is well-posed.

## Interpretation (honest)
Because the fault is recoverable, its error *names the culprit*, so **accuracy saturates** (Drain &
baselines hit ~1.0). The benchmark's discriminating axis with recoverable faults is therefore **token
cost** (RLM greps ~50–80 errors among ~3,000 traces in a ~700k-token window; in-context reads it all).
A genuinely accuracy-*hard* task would require overlapping/ambiguous faults — a later scope choice.

## Patches (reproducible, in infra/otel-demo/patches/)
`product-catalog-origin-log.patch` (Go otelslog), `ad-origin-log.patch` (Java log4j2),
`cart-origin-log.patch` (.NET ILogger via constructor + Program.cs DI). Note: cartFailure needs
payment OFF (checkout must complete to reach EmptyCart); the capture loop resets all flags per class.

## Next (cloud-gated)
Run in-context + RLM on this recoverable dataset to quantify the token win at saturated accuracy.
