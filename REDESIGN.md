# Holistic redesign — what the recoverability finding breaks, and the coherent fix

Triggered by `results/RCA_RECOVERABILITY.md` + a third check (below). Thinking holistically, per
request: the problem is not just the data source — it cascades through task, scoring, prompts,
baseline interpretation, decision rule, plan, and the cloud cost/metric story.

## The root insight (3 independent demonstrations)

**Real micro-fault datasets do not encode their faults recoverably in logs.** The signal lives in
metrics / trace timing / span status, not in distinctive log text.
1. OTel Demo: faults recorded on spans (`span.SetStatus`), ~half the services emit no OTLP logs.
2. Nezha culprit labels: inject service emits *any* error in 12/38 windows, is noisiest in 8/38 (21%);
   faults name *other* services ("No instances available for ts-basic-service").
3. Nezha error distribution (new): **fault windows median 0 error-traces; normal windows median 5**
   — errors are sparse AND anti-correlated with faults (the inject pod tends to go silent/down).

So any task whose label = "where the injected fault is" is **not log-recoverable** on real data, and
even raw error-retrieval has sparse, fault-divorced signal.

## What stays (validated, unaffected)

- **Token-cost thesis** — RLM 0.16–0.41× in-context tokens; trace-aware cheapest; envelope tax 2.19×.
- The whole pipeline: `nezha.py` windowizer, 3 condition variants, methods (drain/in-context/rlm),
  scoring, cloud client. **Reusable as-is.**
- Gate 1 (windows ≫ context; ~84–446× compression handle). The cost axis is solid.

## What breaks (the cascade — the full patch inventory)

| # | Component | What must change |
|---|---|---|
| 1 | **Task definition** | Drop "name the injected culprit from logs" — not recoverable. Need a task with a log-recoverable, distributed, navigation-favoring label. |
| 2 | **Labels (`nezha.py`)** | Add a label source that is recoverable by construction (see recommendation). |
| 3 | **Scoring** | Keep binary (trace-set P/R/F1) + multiclass (origin) scorers; add set-exact-match. Mostly reusable. |
| 4 | **Method prompts** (`llm_incontext.py`, `rlm.py`) | Re-target from "culprit service" to the new task; the injected signature makes it well-posed. |
| 5 | **Drain baseline** | Re-run on the new label; the 0.51 was topology-fingerprinting and must be re-reported. |
| 6 | **Decision rule** (`BENCHMARK_PLAN_v3` §7) | Primary confirmatory cell → the new recoverable task; document methodology + validity caveats. |
| 7 | **Plan** (Phases 2/5/6/7/8) | Reflect the new task + data approach; build the runner (Phase 7, does not exist yet). |
| 8 | **Cloud cost/metric story** | `gpu_seconds` is **null on cloud** → metric = tokens + `total_duration`. Document. Bound the sweep: in-context reads 327–576k-token windows, so a full sweep on `qwen3-coder:480b` is expensive — pick a cheaper sweep model and/or cap windows; add a token budget. |
| 9 | **Tests** | Update for the new task definitions. |

## Recommended path: controlled fault injection on real Nezha traces (the "hybrid")

The only approach that yields a **recoverable + distributed + navigation-favoring + non-trivial**
accuracy axis without days of infra, reusing everything:

- **Substrate:** Nezha's real multi-trace windows (real logs, real trace structure, real error noise).
- **Inject:** a controlled, realistic fault into K chosen traces per window — a distinctive exception
  cascade originating at a chosen service and propagating along the trace's call path.
- **Labels (recoverable BY CONSTRUCTION):** the injected trace set (trace-anomaly) + the origin
  service (root-cause). No dependence on real faults being log-visible.
- **Why it's non-trivial:** the real Nezha errors are background noise the method must distinguish the
  injected cascade from — so it is not a toy "grep ERROR".
- **Why it tests the thesis:** trace-aware RLM greps the injected signature → jumps to the affected
  traces; in-context must read the whole window; plain can't group by trace_id. Direct cost test.

This gives the clean narrative:
> Structure cuts analysis tokens ~6× on real data (validated). When the fault is log-recoverable
> (shown via controlled injection), trace-aware navigation preserves accuracy at a fraction of the
> tokens. And real micro-fault datasets frequently are NOT log-recoverable — a caution for log-based
> AIOps benchmarks.

Two genuine contributions (cost win + recoverability caution) plus a controlled accuracy demonstration.

### Alternatives considered
- **Patch OTel Demo** (force `logger.Error` at each fault origin): more "real" faults, but days of
  stand-up + capture, and we must still author the log line (equally "controlled"). Higher effort,
  similar validity. Keep as a stretch / external-validity appendix.
- **Custom app:** maximal control, weakest credibility, most effort. Not worth it given the hybrid.
- **Real-error retrieval on Nezha (no injection):** recoverable but signal-sparse (median 0–5 error
  traces) and fault-divorced — weak. Keep only as a secondary realistic check.

## Honest caveat
The hybrid's faults are synthetic overlays. Mitigations: make the cascade realistic (propagates along
real call paths, with real background noise), vary difficulty (K, signature subtlety), pre-register the
injection procedure, and frame it as a *controlled study of token cost under a known-recoverable
signal* — not a claim about real-incident detection (which the recoverability finding shows logs can't
support anyway).
