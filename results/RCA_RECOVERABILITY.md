# Finding: Nezha fault labels are not zero-shot log-recoverable

> [!NOTE]
> **Independently reproduced 2026-09-11** from the raw CSVs by `scripts/check_nezha_trace_reach.py`:
> 12/38 and 8/38 match exactly; "named in failure text" measures 3/38 here vs 2/38 below, a
> substring-matching difference, not a discrepancy. A claim that these figures were undercounted by a
> severity parser that missed Train Ticket's logback level token is false — one code path reads both
> formats. What this document does NOT establish, and what `results/NEZHA_REACHABILITY.md` now adds,
> is whether the culprit is *reachable* by following `trace_id` from an erroring service: 16/38 (42%).


Discovered offline (no cloud cost) while investigating why all methods missed the culprit on window
`2023-01-29/10_20`. This reshapes the accuracy axis of the benchmark.

## Evidence

**1. The culprit service rarely owns the error signal.** Across 38 log-visible (exception/return)
fault windows:
- inject service emits ≥1 ERROR itself: **12/38 (32%)**
- inject service is the *noisiest* service: **8/38 (21%)**
- inject service named in the failure text ("No instances available for X"): **2/38 (5%)**

The fault propagates: e.g. an `exception` injected in `ts-travel-service` surfaces as
`IllegalStateException: No instances available for ts-basic-service` in `ts-travel-service` AND the
near-duplicate `ts-travel2-service` (which has *more* errors). The logs name `ts-basic-service`; the
label says `ts-travel-service`. The methods that answered `ts-basic-service` **read the logs
correctly** — the label just isn't in there.

**2. The trace-anomaly label is uncorrelated with log signals.** Within fault windows,
anomalous traces (touch inject_pod) vs normal traces:
- mean errors/trace: **0.06 vs 0.06**
- % with ≥1 error: **4% vs 6%** (normal slightly higher)

So "touches inject_pod" leaves no log fingerprint. Drain's F1 0.51 on this task was largely learning
the *topology* (which traces pass through commonly-injected services), not detecting an anomaly.

## Implication

The original accuracy tasks (culprit-service localization; trace-anomaly by topology) are **ill-posed
for zero-shot log analysis on Nezha** — the ground truth isn't recoverable from log content. This is
the third data-reality check to bite (OTel Demo faults on spans → Nezha labels not in logs), and it
reflects a real truth: injected micro-faults manifest in metrics/traces/timing, not in distinctive
log text.

What is NOT affected: **the token-cost thesis is still validated** — RLM reaches an answer in 0.16–0.41×
the tokens of reading the whole window; trace-aware is cheapest; in-context pays a 2.19× envelope tax.
The cost axis stands; the *accuracy* axis needs a task whose answer is actually in the logs.

## Options (decision needed)

- **(A) Reframe to a log-recoverable task.** Keep the injected-fault windows as realistic large
  contexts, but ask a question whose answer IS in the logs and requires scanning the window — e.g.
  "list the trace_ids that contain an error" or "which service is most error-impacted." Accuracy
  becomes meaningful; trace-aware navigation directly helps; the token-cost comparison is unchanged.
  *(Recommended — preserves the validated thesis with a clean, recoverable y-axis.)*
- **(B) Token-cost-only contribution + this recoverability caution.** Drop the accuracy headline;
  contribution = "trace context cuts analysis tokens ~6×" plus "log-based RCA labels are often not
  log-recoverable — a benchmark caution."
- **(C) Reconsider the data source again** for one with log-visible, log-recoverable faults
  (higher effort; the prior search suggests these are rare).
