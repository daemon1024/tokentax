# A crashed culprit is unreachable by trace correlation — in logs *and* in spans

**Measured on rca-lab sc-10**, a real OOMKill fault, no modification to the lab, no hand-authored log
lines. This is the cleanest cause-versus-symptom data this project has ever had, and it produces a
null for trace context by a mechanism no dataset choice can fix.

Capture: kind `rca-lab`, sc-10 enabled via the scenario operator (`recommendation-service:1.1.0`,
unbounded personalization cache → RSS climbs → OOMKill → restart), 3 restarts observed, ~4 minutes of
fault window, logs and spans forwarded to a host collector and parsed with `otel_loader`.

## The log side is perfect, and useless

| | baseline | under sc-10 |
|---|---|---|
| ERROR log records | 6 | **464** |
| ERROR records carrying `trace_id` | 2 (33%) | **464 (100%)** |
| culprit's own ERROR lines | — | **0** |
| `argmax(errors_by_service)` | — | `product-catalog` — **wrong** |

Ground truth is `recommendation-service`. Every error line comes from `product-catalog`, one hop
upstream: `recommendations rpc failed exception.message=rpc error: code = Unavailable ...`.

So this dataset has, simultaneously: real faults, no label leakage, a culprit that is silent, a
symptom service that is loud, and `trace_id` populated on **100%** of the error lines. Every
requirement this project has spent its life looking for.

And the pre-registered gate (`scripts/check_request_ambiguity.py`) still says **STOP**:

```
W(s)  usable  med concurrent  med services  single-svc
2.00     760            38.0           1.0         100%
VERDICT: STOP — median 1.0 services per erroring trace < 2.0
```

**100% of erroring traces touch exactly one service in the logs.** Following `trace_id` off a
`product-catalog` error returns `product-catalog`'s own line and nothing else. The join key is
present, free, and lands on an empty set.

## The span side does not rescue it

The obvious answer is that logs are the wrong signal and the span tree holds the chain. Measured over
83,596 spans / 17,268 traces in the same window:

| | |
|---|---|
| error-bearing traces | 3,224 |
| services per error-bearing trace | median **2.0**, max **2** |
| error traces reaching `recommendation-service` | **0 / 3,224 (0%)** |

Error spans come from `load-generator` (3,176), `product-catalog` (1,342) and `cart-service` (454).
**The culprit appears in none of them.**

## Why — and why it generalises

When `recommendation-service` is OOMKilled, the gRPC dial fails with `Unavailable`. The callee never
receives the request, so it never starts a span and never writes a log. **A dead process emits no
telemetry.** Trace context propagates to processes that are alive to receive it; the one thing it
cannot do is carry evidence out of a process that has just been killed.

This is not a property of rca-lab, or of OpenTelemetry, or of this capture. It holds for every
crash-class fault — OOMKill, panic, segfault, pod eviction, node loss. For that whole family:

- the culprit is absent from logs **and** from spans,
- the only evidence is an upstream error whose *message text* names the dependency
  (`recommendations rpc failed`), plus the *absence* of the callee,
- so localisation runs on **semantics and topology**, not on trace structure.

Trace context is a join over telemetry that exists. Crash faults are defined by telemetry that does
not.

## What this settles, and what it opens

**Settles:** the failure of `trace_id` to help is not a dataset artifact and not a model failure. On
the best data this project has assembled, with the key present on 100% of the relevant lines, the
join reaches nothing — because there is nothing to reach. `NEZHA_REACHABILITY.md` measured
reachability at 58% on Nezha Train Ticket; here it is **0%**, and for a reason that is visible in the
mechanism rather than the statistics.

**Opens:** crash faults are one family. The interesting complement is a culprit that stays **alive and
degraded**, because then it *does* emit spans and logs, and the trace genuinely spans both services:

| scenario | mechanism | culprit alive? |
|---|---|---|
| `sc-06` | Postgres `ACCESS EXCLUSIVE` lock held by a stalled migration | yes — queries block |
| `sc-11` | `review-service` event-loop blocked by a sync CPU loop | yes — slow, not dead |
| `sc-15` | Chaos Mesh 200 ms egress delay on `product-catalog` | yes — slow, not dead |
| `sc-04` | InnoDB row locks held by a stalled transaction | yes — `Lock wait timeout` |

Those are where trace correlation has a mechanical chance, and the pre-check will say so before a
single model token is spent: run `check_request_ambiguity.py` per scenario and only proceed where
`median_trace_services >= 2`.

**The honest headline available today** is stronger than the one the project set out to prove:
*trace context cannot localise a fault whose culprit stopped running, and a large and important class
of production incidents is exactly that.* That is a real finding about the limits of distributed
tracing for RCA, it is measured rather than argued, and it is the kind of claim an OpenTelemetry
audience would take seriously.
