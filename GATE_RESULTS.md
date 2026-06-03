# Gate Validation — Real Train Ticket Data (GPU-free)

Measured on cloned Nezha data (`data/raw/Nezha`, Train Ticket = 2023-01-29/30, 135 per-minute
windows) via `scripts/measure_gates.py` (windowizer `src/tokentax/nezha.py`). Tokens via
tiktoken `cl100k_base` as a **proxy** for Qwen (order-of-magnitude gate; Qwen cross-check is a
later step, REVIEW MEASURE-2).

## Gate 1 — RLM context-crossover → **PASS (strong)**

| quantity | value (median) |
|---|---|
| records / per-minute window | 2,033 (max 5,381) |
| distinct traces / window | 52 (max 137) |
| **multi-pod traces / window** | **51** (100% trace_id coverage) |
| tokens / window — plain (body only) | **327,095** |
| tokens / window — structured (+ids) | 575,889 |
| tokens / single trace (plain) | 3,905 |
| **windows exceeding 8,192 chunk cap** | **135 / 135 (100%)** |
| windows exceeding 16,384 (2¹⁴) | 135 / 135 (100%) |
| envelope tax (structured / plain) | **1.76×** |
| **RLM compression handle (window / single trace)** | **~84×** |

The in-context method must chunk every window ~40× (327k/8k). A trace-aware RLM that greps
the relevant trace_id reads ~4k tokens instead of ~327k. The token win the thesis predicts is
**real and large** — and measurable without a GPU. The envelope tax (1.76×) confirms REVIEW
THESIS-1: structured costs *more* per line, so the win comes from selectivity, not smaller logs.

## Gate 2 — ≥50 windows/class → **FAIL (hard)**

Fault episodes are sparse and the catalog is small:

| system / date | total | exception | return | cpu_* | network_delay |
|---|---|---|---|---|---|
| TrainTicket 2023-01-29 | 28 | 13 | 11 | 4 | 0 |
| TrainTicket 2023-01-30 | 17 | 0 | 0 | 3 | 14 |
| OnlineBoutique 2022-08-22 | 24 | 3 | 3 | 11 | 7 |
| OnlineBoutique 2022-08-23 | 32 | 4 | 4 | 15 | 9 |
| **ALL Nezha** | **101** | **20** | **18** | 33 | 30 |

- **Log-visible (exception+return) episodes: 24 on Train Ticket, 38 across ALL Nezha.**
- `≥50/class` is **impossible** on Nezha — 38 is the ceiling, ~19/class even using both systems.

## New finding (verified) — window-level binary anomaly is ill-posed here

ERROR logs are pervasive at baseline, so error *volume* does NOT signal the fault:

| window type | ERROR lines / window (median) |
|---|---|
| exception/return (fault) | 11 |
| metric-only (cpu/network) | 9 |
| **normal (no fault)** | **11** (mean 14, one normal window had 44) |

Verified against raw `grep`: normal window `12_01` = 44 ERROR lines, *more* than the
exception-inject window (25). So:
- the "≥1 ERROR in window" capture gate and any-ERROR-regex baseline (REVIEW OTEL-1/LEAK-4)
  are **useless discriminators** on Train Ticket — everything has errors;
- distinguishing an injected fault from the noisy baseline *is itself* a correlation/localization
  problem → the task naturally collapses toward **root-cause localization**, not volume anomaly.

## Implications for the design

1. **Drop the `≥50/class` target** — incompatible with Nezha (max 38 log-visible cases). Pre-register
   the real n (≈24 TT-only / ≈38 both-systems log-visible; ≈101 incl. metric faults as a harder tier)
   with bootstrap CIs; frame the accuracy axis as **pilot-scale**.
2. **Make root-cause / culprit-service localization the PRIMARY task** (clean `inject_pod` labels,
   fits trace-navigation, is what Nezha is built for). Demote window-binary-anomaly (ill-posed here).
3. **The token headline is solid GPU-free**: ~84× compression handle, 1.76× envelope tax — lead with
   tokens-to-conclusion; the small-n F1 is the supporting axis.
4. **Scope question reopened by the data**: Train-Ticket-only = 24 cases; both Nezha systems = 38 +
   Online Boutique's higher trace concurrency. Since "single app" was about *no cross-method data
   confound* (all 3 methods on identical data), "Nezha (both systems), one pipeline" still satisfies
   that goal — worth relaxing to nearly double n.
