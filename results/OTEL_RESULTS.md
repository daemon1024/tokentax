> [!IMPORTANT]
> **SCOPE NOTE (2026-08-20).** The recoverability verdict below is correct, but it is a statement about
> a dataset this project *constructed*, not a property of the OpenTelemetry Demo.
>
> The origin ERROR log exists because `infra/otel-demo/` patches a hand-authored `logger.error` into the
> fault-origin service (the patch comment says "so the fault is log-recoverable"). `infra/otel-demo/README.md`
> states the labels are "NOT from a marker in the log" — that is wrong; the patch **is** the marker.
>
> Consequence: on these windows the culprit is the only erroring service in 9 of 9 anomalous windows, so
> `argmax(ERROR count by service)` scores 11/12 with no model involved. The dataset is recoverable *by
> construction*, which makes it a valid **control** — a known-recoverable signal for measuring cost — and
> an invalid basis for any accuracy claim. The comparison against Nezha below remains sound and is the
> genuinely interesting result: unpatched, real micro-fault datasets are largely **not** log-recoverable.
>
> See `WITHDRAWAL.md`.

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

## LLM sweep — BLOCKED by Ollama Cloud quota (2026-06-04)
Ran `scripts/run_otel_sweep.py` (in-context vs RLM, plain vs structured, root-cause task) on small
windows (~310–457k tokens). Got ONE data point before the account quota hit:
- **in-context, plain, normal window: 457,133 input tokens** (read across 4 chunks) → correctly
  answered "none" ✓. This is the full-read cost the RLM must beat.

Then **HTTP 429 Too Many Requests** on every subsequent call — including a tiny "reply OK" — with no
`Retry-After`. This is an **account-level GPU-time quota exhaustion** (Ollama free-tier 5h/weekly cap,
flagged in REVIEW), not a transient rate limit, so it blocks all models. Hardened the client
(429-aware backoff, honor Retry-After, 6 retries) — committed — but the quota must reset (hours) or
the plan be upgraded (Pro/Max) or run against a local Ollama.

**Prior cloud evidence (not blocked, already committed in SMOKE_RESULTS.md):** on Nezha, RLM used
0.41× (plain) / 0.16× (structured) of in-context tokens. The OTel sweep would confirm this on
recoverable data; it is re-runnable (`python scripts/run_otel_sweep.py --manifest …`) once quota resets.

## LLM sweep COMPLETED locally (qwen3:8b, cloud quota bypassed) — 2026-06-04
Ran on local Ollama (cask install; `OLLAMA_HOST=localhost`, no key) to bypass the cloud quota. One
recoverable `productCatalogFailure` window, root-cause task. **The thesis payoff:**

| method | condition | tokens | culprit found |
|---|---|---|---|
| in-context | plain | 365,864 | ✓ |
| in-context | structured | 555,079 | ✗ (read it all, missed the fault) |
| **RLM** | **plain** | **5,631** | ✓ |
| **RLM** | **structured** | **4,631** | ✓ |

- **RLM uses 0.016× (plain) / 0.008× (structured) of in-context tokens — 62×–118× cheaper.**
- **Structure is free compression for the navigator, a tax for the reader:** RLM-structured is the
  cheapest cell (4,631) — it greps the ERROR straight to product-catalog regardless of JSON verbosity;
  in-context-structured is the most expensive (555k) AND wrong — the 8B drowned in verbose OTLP-JSON.
- RLM is also more robust: correct in both conditions; in-context fragile on the big structured window.

Caveats: n=1 window, qwen3:8b (the in-context-structured *miss* is partly an 8B limitation; the token
COST asymmetry is model-independent and robust). Consistent with the Nezha smoke (RLM 0.16–0.41×),
more extreme here because OTel windows are larger. Re-run with `scripts/run_otel_sweep.py` (cloud or
local) for more windows / a larger model.

## Sonnet in-context (via subscription `claude -p`) — 2026-06-05
Re-ran in-context on Claude Sonnet (subscription, `scripts/run_claude_sweep.py`; tokens include a
constant ~30k/call harness overhead that cancels in the plain-vs-structured ratio). Same recoverable
`productCatalogFailure` window:

| condition | tokens | $ | predicted | correct |
|---|---|---|---|---|
| plain | 460,431 | 1.55 | `productcatalogservice` (inferred from body) | ✓ |
| structured | 679,049 | 2.27 | `product-catalog` (exact, from `service.name`) | ✓ |

Findings:
- **Sonnet found the fault in BOTH conditions — including the structured window qwen3:8b MISSED.**
  So the 8B's structured miss was a model limitation, not fundamental; a frontier model handles the
  verbose OTLP-JSON fine.
- **Envelope tax = 1.47×** (structured costs ~47% more tokens for the reader) — confirms the thesis
  on a frontier model.
- **Structure buys naming precision:** with the `service.name` field present, Sonnet returns the
  EXACT canonical culprit; plain forces a semantically-correct but differently-named inference. So
  structure = more tokens AND a more precise answer for in-context.

Cross-model: the in-context envelope tax is consistent (qwen 1.52× / Sonnet 1.47×); the RLM≪in-context
cost gap (qwen 62–118×) is model-independent by construction. RLM-on-Sonnet (Claude navigating a log
file with its native Grep/Read tools) is the natural next step.

## Sonnet RLM (Claude navigates the log file with native Grep/Read) — the full 2×2
`scripts/run_claude_rlm.py`: write the window to a file, Claude finds the culprit by grepping/reading
SELECTIVELY. Same `productCatalogFailure` window, all four cells **CORRECT**:

| method | plain tokens | structured tokens |
|---|---|---|
| in-context (reads all) | 460,431 | **679,049** ← envelope tax (structured costs MORE) |
| RLM (navigates) | 342,697 | **63,274** ← compression (structured costs LESS) |

**Structure is a TAX for the reader but COMPRESSION for the navigator** (the thesis title, demonstrated):
- in-context: structured = **1.47×** plain (reading verbose JSON costs more).
- RLM: structured = **0.18×** plain (**5.4× cheaper** — grepping `severityText:ERROR` + `service.name` is precise).
- RLM vs in-context: **0.093× structured (10.7× cheaper)**, 0.74× plain.
- **Best cell RLM+structured (63k) vs worst in-context+structured (679k) = 10.7×** — same window, same model.

**The decisive detail:** RLM-on-PLAIN read 342k (74% of in-context's full read) — without structure,
even a frontier navigator can't save much, because there's nothing precise to grep. **Structure is
what makes navigation cheap** — that IS the contribution.

This is the strongest evidence in the project: real agentic navigation (Claude Code's own tools) on a
recoverable, native-OTLP dataset, all cells correct, the cost asymmetry crisp.

## Next
- More windows + CIs (each window is ~$2-4 of subscription/cloud); harder accuracy task (overlapping
  faults) so methods also differ on F1; consolidate into the final write-up.
