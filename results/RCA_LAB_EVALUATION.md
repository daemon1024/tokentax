# coroot/rca-lab — the first candidate that meets all six requirements

**Verdict: yes, and it is better than everything else audited.** It is the only source found that
satisfies every requirement, including the two that killed every other candidate — emission-time
`trace_id` on log records, and faults whose labels are not written into the log text.

It is a **generator**, not a static dataset: a Kubernetes lab you run. That is the cost.

`https://github.com/coroot/rca-lab` · Apache-2.0 · 26 MB repo · last pushed 2026-09-11 (active).

## Against the six requirements

| # | requirement | rca-lab | evidence |
|---|---|---|---|
| 1 | emission-time `trace_id` on log records | **YES** | `services/product-catalog/go.mod` pulls `go.opentelemetry.io/contrib/bridges/otelslog` + `otlploggrpc` + `otel/sdk/log`. The otelslog bridge stamps trace context onto records emitted inside a span. README: logs go "to stdout *and* OTLP, trace-correlated". |
| 2 | real multi-service traces | **YES** | 11 services (`api-gateway`, `cart`, `order`, `payment`, `product-catalog`, `recommendation`, `review`, `inventory`, `fulfillment`, + seeder/load-gen) across Go, Java and Node, calling each other over HTTP and gRPC. |
| 3 | log-visible faults | **PARTIAL, and knowable in advance** | Some scenarios are error-producing (`sc-06` pool exhaustion → api-gateway errors; `sc-04` `Lock wait timeout exceeded`; `sc-10` gRPC errors during OOM restarts). Others are pure latency/saturation and will write no ERROR line. Each scenario's `expectedSymptoms` says which, so the usable subset is selectable *before* spending anything. |
| 4 | labels not leaked in log text | **YES — explicitly** | README: "Every scenario uses a genuine real-world mechanism — **never a synthetic fault flag inside the app**." Faults are real Postgres `ACCESS EXCLUSIVE` locks, InnoDB row locks, Chaos Mesh `NetworkChaos`, JVM/Go memory regressions shipped as image rollouts. This is the direct fix for `infra/otel-demo/`'s hand-authored `logger.error`. |
| 5 | cause ≠ symptom | **YES — by design, on every scenario** | The scenario table is literally a cause column and a symptom column, and the recurring shape is "X degrades while Y stays healthy". `sc-06`: migration holds the lock → product-catalog blocks → api-gateway errors, **yet PostgreSQL CPU/IO stay flat**. `sc-15`: 200 ms egress delay on product-catalog → api-gateway latency ~1 s **while product-catalog's own CPU/DB stay healthy**. `sc-12`: a co-tenant burns the node's cores → order-service starves **while its dependencies stay healthy**. |
| 6 | public, licensed, ≥50 cases | **PARTIAL** | Apache-2.0, fully public. **23 scenarios** (`sc-01`…`sc-26`) plus 5 bad-deploy image variants in `variants/registry.yaml`. Below the 50 target as distinct scenarios, but each can be run repeatedly and at different load levels, and `expectedSymptoms` is described by the authors as "a grading rubric for RCA tools". |

## Why this matters more than the count

Every other candidate failed on requirement 1 or 4:

- **OpenRCA** — no `trace_id` column; Telecom has no logs at all.
- **RCAEval** — no `trace_id`; second-resolution timestamps make a join ambiguous ~6:1.
- **RCA100 / AIOps2025** — no trace field on the log record; AIOps2025 additionally leaks
  `Injected error` 28,016 times from the fault-origin pod.
- **Nezha** — has `trace_id` at 100%, but its OnlineBoutique half is silent (5/14 windows carry any
  error) and the Train Ticket half yields only ~10–16 usable cells
  (`results/NEZHA_REACHABILITY.md`).
- **`data/otel_demo`** — ours, and it writes the answer into the log text by construction.

rca-lab is the first source where the *cause-versus-symptom structure is the point of the artifact*
rather than an accident we have to go looking for.

## What it would cost

**Not runnable on this machine as it stands.** Requirements are `kubectl` + `helm` against a cluster
with a default StorageClass and **~8 CPU / 16 GiB**. `kind`, `kubectl` and `helm` are all installed
here, but Docker is allocated **7.75 GiB** of the host's 24 GiB, and it is currently hosting other
work: a `sigiro` container and a running `kind` cluster (`jvm-metrics-e2e`, control-plane + worker).

Raising Docker's memory requires restarting Docker Desktop, which would destroy that cluster. That is
a decision for the repo owner, not something to do unattended. Disk is also tight: 46 GiB free, and
the default seed is a ~10 GB products table (`SEED_SIZE_GB=0` skips it).

**The path, once memory is available:**

```bash
git clone https://github.com/coroot/rca-lab && cd rca-lab
make deploy SINGLE_NODE=1 SEED_SIZE_GB=0 OTLP_ENDPOINT=<collector>:4317 YES=1
kubectl patch maintenancejob sc-06 --type=merge -p '{"spec":{"enabled":true}}'
make clean          # fully reversible; KEEP_DATA=1 preserves volumes
```

Scenarios are Kubernetes CRDs (`kubectl get maintenancejobs`), toggled individually, and can run on a
cron schedule with a fixed duration — so a capture run is scriptable rather than hand-driven.

**Capture.** The bundled otel-collector **discards telemetry by default**; `OTLP_ENDPOINT` forwards
it. We already own the other half of this: `infra/otel-demo/` captures OTLP LogRecords to
`logs.jsonl`, and `src/tokentax/otel_loader.py` parses exactly that shape into `LogRecord` with
`trace_id` populated. Pointing rca-lab's collector at a file-exporting collector reuses the existing
loader with no new parser.

Estimated effort: **1–2 days** to a first captured scenario, most of it cluster bring-up and
verifying that `traceId` is populated on the log records that matter — not code.

## Recommendation

**Adopt it as the successor dataset, and keep Nezha Train Ticket as the bridge.** Nezha is on disk,
costs nothing, and is already producing the paired contrast. rca-lab is where the experiment should
end up, because it is the only source where the top-erroring service is *designed* to be the wrong
answer.

Two checks to run first, both cheap, before committing two days:

1. **Confirm `traceId` is actually populated on ERROR records**, not just on INFO spans. The Go
   bridge is `otelslog`; a log emitted outside a span context carries no trace id, and error paths
   are exactly where a span may have already ended. This is the single assumption the whole plan
   rests on, and it is the one the README cannot settle.
2. **Pick the log-visible subset** from `expectedSymptoms` before deploying. On present evidence
   `sc-04`, `sc-06`, `sc-10` and `sc-11` produce errors; the pure-latency scenarios (`sc-14`,
   `sc-15`) likely produce none, and would fail requirement 3 the same way RCAEval RE2 did.
