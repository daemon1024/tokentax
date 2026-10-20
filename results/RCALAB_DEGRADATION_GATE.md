# rca-lab degradation faults: the model-free gate says STOP

**Measured 2026-10-20 on a fresh rca-lab deployment, no model called.** Question: on faults where the
culprit stays alive (it keeps emitting spans and logs), can a log-reading model's stage comparison
(Stages 0-3, and the per-request task) be tested at all? Answer: **not on rca-lab's logs.** In every capture
the trace-correlated log evidence is single-service. Where a fault produces any new log lines at all, they
come either from the culprit itself (so a per-service ERROR count already names it) or from a caller of a
dead culprit (crash). Trace correlation over logs reaches the culprit from a foreign error in **0 traces
in every capture**. The faults are real and plainly visible in the spans. So **no rca-lab model run was
made**, and the cloud quota went to the per-request run on the OTel Demo (`results/REQUEST_FORENSICS_V2.md`).

## Phase A: the bench

- The existing `kind` cluster (containers `kind-control-plane` / `kind-worker`, created 2026-10-09) was
  **not rca-lab**. It was a half-initialised empty cluster: etcd, apiserver, controller-manager and
  scheduler only; no CoreDNS, no kube-proxy, no CRDs, no `maintenancejobs`, nothing in `default`, and
  kubeadm's admin RBAC binding was never created. It was inspected read-only and **re-paused exactly as
  found**.
- A fresh `kind create cluster --name rca-lab` (one node, kindest/node v1.35.0) was created after checking
  headroom (Docker 11.67 GiB; ~2 GiB in use by the other containers, none of which were touched).
- The 13 cached arm64 rca-lab images were side-loaded. Built for arm64, all on the first or third attempt:
  `order-service:1.0.1` (first attempt; the OTel Java agent downloaded fine this time, so **no scenario
  had to be excluded**), and the bad-deploy variants `review-service:1.2.0`, `order-service:1.3.0`,
  `order-service:1.4.0` and `product-catalog:1.1.0` (the last from a copied service dir with the amd64 pins
  removed and `variants/gc-pressure/src/main.go` applied). Chaos Mesh images and slow database images were
  pulled on the host and side-loaded.
- `make deploy SINGLE_NODE=1 SEED_SIZE_GB=0 YES=1` first timed out waiting for the databases (slow
  in-node pulls). After side-loading, a re-run completed every step, including the scenario operator and
  library (25 `MaintenanceJob`s). App deployments were scaled to 1 replica (requests had been at 95% CPU /
  86% memory). The Chaos Mesh daemon was re-pointed at kind's containerd socket (the lab's values file
  targets k3s).
- Capture: host collector `otelcol-contrib 0.158.0` with `infra/rcalab-capture-collector.yaml` on the `kind`
  network (IP read back with `docker inspect`: 172.18.0.5), `make otel OTLP_ENDPOINT=172.18.0.5:4317
  OTLP_SIGNALS=traces,logs`, plus a size watchdog (`infra/rcalab_capture_watchdog.sh`).

**Every capture is kept as a replayable dataset**: `results/datasets/RCALAB_DATASET.md`, manifest
`results/datasets/rcalab_manifest.json`, loader `src/tokentax/rcalab_dataset.py`.

## Method (no model)

For each scenario: a baseline with nothing enabled; enable; the fault window starts when the controller logs
`"starting run"` for that scenario; the effect is then checked live from the CR's own actions
(`infra/rcalab_effect_check.py`: workload job running, image rolled out, chaos object injected, lock
held...); bounded fault; disable; recovery. The **retraction lesson of `RCA_LAB_CAPTURE.md` was enforced
mechanically**: the first sc-06 attempt saw "starting run" but never saw its lock (a bug in my own check, a
wrong pod label), so it aborted and recorded nothing.

`scripts/rcalab_gate.py`, criteria fixed before the first degradation capture was looked at:

- **WS** (Stages 0-2 have a signal): fault-window ERROR records >= 10 AND >= 2x the baseline ERROR rate.
- **S3** (trace_id can pay on the culprit-service task): WS, AND `argmax(errors_by_service)` is NOT strictly
  correct, AND the culprit is reached by trace_id from a foreign ERROR log line in >= 5 traces and >= 10%
  of foreign-erroring traces.
- **PR** (per-request task): `check_request_ambiguity` PROCEED at W = 2 s over all services (median
  concurrent >= 5 AND median services per erroring trace >= 2, >= 30 usable). This is the criterion and
  fallback `REQUEST_FORENSICS_PREREG.md` used.

`tokentax.rcalab` reproduces the published sc-10 numbers exactly on the old files (760 ERROR, 100%
trace_id, 3,617 error traces, 0 reaching the culprit), so the definitions match `SC10_CRASH_FAULT.md`.

## Results

27 captures of the 25 scenarios the lab deploys (sc-01 to sc-15, sc-19 to sc-28; sc-16 to sc-18, the Mongo
long-transaction, replica-fencing and replication-lag files, exist in `rca-lab/scenarios/reliability/` but
are not in `scenarios/kustomization.yaml`, so they were never deployed), sc-04 and sc-06 recorded twice, plus a 30-minute healthy window. The fault effect was
seen live in 24 of 27; **sc-20, sc-22 and sc-28 never showed their effect within 180 s** and are kept but
flagged (`D.captures()` excludes them by default). Table generated by `scripts/rcalab_gate_summary.py`
from `results/runs/rcalab_gate/*.json`:

| capture | culprit (truth) | ERROR/min baseline | ERROR/min fault | ERROR in fault | records with trace_id | argmax(errors_by_service) | culprit's own log records | culprit reached from foreign error traces, LOGS | error traces reaching culprit, SPANS | W=2s median concurrent / services | fault-window tokens (plain lines) | baseline p99 root ms -> slow traces base vs fault | WS | S3 | PR |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| sc-01 | review-service | 39.19 | 33.91 | 341 | 4631/4691 | fulfillment-service ✗ | 0 | 0/341 | 5334/12620 | 37 / 1 | 445,124 | 8,904 -> slow traces 566 vs 8554 | fail | fail | fail |
| sc-02 | review-service | 38.19 | 37.43 | 190 | 2527/2558 | fulfillment-service ✗ | 0 | 0/190 | 3950/7475 | 36 / 1 | 238,338 | 10,002 -> slow traces 499 vs 958 | fail | fail | fail |
| sc-03 | order-service | 39.39 | 39.2 | 395 | 6718/6778 | fulfillment-service ✗ | 7 | 0/395 | 7/6378 | 45 / 1 | 653,091 | 8,112 -> slow traces 580 vs 1206 | fail | fail | fail |
| sc-04 | order-service | 38.95 | 379.88 | 1900 | 2784/2864 | order-service ✓ | 2636 | 0/198 | 1021/5011 | 37 / 1 | 1,423,375 | 2,025 -> slow traces 426 vs 2356 | PASS | fail | fail |
| sc-04_r2 | order-service | 39.39 | 375.13 | 3772 | 5513/5712 | order-service ✓ | 5249 | 0/395 | 1924/10156 | 31 / 1 | 2,873,398 | 6,913 -> slow traces 600 vs 6400 | PASS | fail | fail |
| sc-05 | product-catalog | 39.39 | 39.38 | 396 | 429/489 | fulfillment-service ✗ | 0 | 0/396 | 3625/6330 | 3 / 1 | 19,863 | 8,263 -> slow traces 575 vs 1150 | fail | fail | fail |
| sc-06 | product-catalog | 39.31 | 39.79 | 199 | 199/229 | fulfillment-service ✗ | 0 | 0/199 | 471/3803 | 3 / 1 | 9,339 | 75 -> slow traces 431 vs 3593 | fail | fail | fail |
| sc-06_r2 | product-catalog | 39.39 | 39.42 | 397 | 417/479 | fulfillment-service ✗ | 2 | 0/397 | 696/7718 | 3 / 1 | 19,375 | 7,388 -> slow traces 595 vs 7008 | fail | fail | fail |
| sc-07 | order-service | 39.19 | 45.0 | 678 | 1066/1398 | fulfillment-service ✗ | 436 | 0/560 | 386/11602 | 3 / 1 | 96,146 | 5,458 -> slow traces 640 vs 8613 | fail | fail | fail |
| sc-08 | order-service | 38.79 | 41.59 | 627 | 1101/1285 | fulfillment-service ✗ | 209 | 0/564 | 363/10205 | 3 / 1 | 124,826 | 6,317 -> slow traces 621 vs 5277 | fail | fail | fail |
| sc-09 | product-catalog | 37.99 | 37.71 | 380 | 406/468 | fulfillment-service ✗ | 2 | 0/380 | 3556/6313 | 3 / 1 | 20,390 | 6,040 -> slow traces 636 vs 1660 | fail | fail | fail |
| sc-10 | recommendation-service | 38.78 | 362.25 | 5445 | 5660/5757 | product-catalog ✗ | 7 | 0/5445 | 1/19170 | 42 / 1 | 294,276 | 6,400 -> slow traces 618 vs 1956 | PASS | fail | fail |
| sc-11 | review-service | 39.57 | 39.71 | 400 | 402/472 | fulfillment-service ✗ | 10 | 0/400 | 3073/12327 | 3 / 1 | 18,823 | 130 -> slow traces 721 vs 19914 | fail | fail | fail |
| sc-12 | order-service | 38.19 | 23.29 | 234 | 1095/1159 | fulfillment-service ✗ | 0 | 0/234 | 0/6029 | 4 / 1 | 97,152 | 7,180 -> slow traces 593 vs 786 | fail | fail | fail |
| sc-13 | load-generator | 38.99 | 38.68 | 387 | 4356/4688 | fulfillment-service ✗ | 332 | 0/387 | 91013/91403 | 41 / 1 | 415,126 | 7,048 -> slow traces 595 vs 83703 | fail | fail | fail |
| sc-14 | (none) | 39.39 | 38.08 | 383 | 391/451 | fulfillment-service ✗ | 0 | 0/383 | 0/6272 | 3 / 1 | 18,224 | 6,826 -> slow traces 606 vs 1492 | fail | fail | fail |
| sc-15 | product-catalog | 38.99 | 39.41 | 396 | 417/477 | fulfillment-service ✗ | 0 | 0/396 | 3641/6398 | 3 / 1 | 20,555 | 4,730 -> slow traces 689 vs 880 | fail | fail | fail |
| sc-19 | (none) | 39.19 | 38.88 | 389 | 5755/5815 | fulfillment-service ✗ | 0 | 0/389 | 0/7923 | 39 / 1 | 553,882 | 10,000 -> slow traces 521 vs 1987 | fail | fail | fail |
| sc-20 | (none) | 37.98 | 38.79 | 388 | 5194/5254 | fulfillment-service ✗ | 0 | 0/388 | 0/9236 | 35 / 1 | 496,978 | 10,002 -> slow traces 499 vs 728 | fail | fail | fail |
| sc-21 | (none) | 38.99 | 39.02 | 588 | 4455/4545 | fulfillment-service ✗ | 0 | 0/588 | 0/9848 | 8 / 1 | 411,863 | 9,133 -> slow traces 558 vs 1508 | fail | fail | fail |
| sc-22 | (none) | 38.39 | 38.77 | 388 | 5324/5384 | fulfillment-service ✗ | 0 | 0/388 | 0/8854 | 36 / 1 | 512,067 | 10,001 -> slow traces 494 vs 895 | fail | fail | fail |
| sc-23 | product-catalog | 38.99 | 39.09 | 392 | 6705/6765 | fulfillment-service ✗ | 0 | 0/392 | 3554/6634 | 45 / 1 | 651,495 | 9,460 -> slow traces 548 vs 943 | fail | fail | fail |
| sc-24 | (none) | 39.19 | 38.94 | 586 | 9910/10001 | fulfillment-service ✗ | 0 | 0/586 | 0/9912 | 44 / 1 | 962,591 | 9,251 -> slow traces 537 vs 1795 | fail | fail | fail |
| sc-25 | (none) | 38.79 | 38.96 | 587 | 9540/9630 | fulfillment-service ✗ | 0 | 0/587 | 0/10418 | 42 / 1 | 924,924 | 10,000 -> slow traces 527 vs 1073 | fail | fail | fail |
| sc-26 | order-service | 38.79 | 38.77 | 390 | 6221/6281 | fulfillment-service ✗ | 9 | 0/390 | 9/6556 | 42 / 1 | 603,156 | 8,773 -> slow traces 568 vs 1243 | fail | fail | fail |
| sc-27 | (none) | 37.19 | 38.49 | 579 | 8520/8610 | fulfillment-service ✗ | 0 | 0/579 | 0/13031 | 38 / 1 | 824,230 | 10,001 -> slow traces 512 vs 1980 | fail | fail | fail |
| sc-28 | (none) | 38.99 | 37.14 | 372 | 4811/4871 | fulfillment-service ✗ | 0 | 0/372 | 0/11964 | 33 / 1 | 438,108 | 10,002 -> slow traces 490 vs 2171 | fail | fail | fail |

- **WS passes in 3 of 27** (sc-04, sc-04_r2, sc-10). In 20 of the other 24 the fault-window ERROR rate is
  within 2.5/min of baseline: the fault adds no error lines at all. (sc-07 and sc-08 add a few, about
  +6 and +3/min, below the 2x bar; sc-01 and sc-12 drop by 5 and 15/min.)
- **S3 passes in 0 of 27. PR passes in 0 of 27.** In every capture the median erroring trace touches **one**
  service in the logs, and following trace_id off a foreign ERROR line reaches the culprit in **0** traces.
- Where WS passes, trace_id is not what is missing. In sc-04 / sc-04_r2 the culprit is the loudest
  service itself (`argmax` correct, 2,636 and 5,249 of its own records). In sc-10 the culprit is dead and
  its caller logs the failure (`SC10_CRASH_FAULT.md`).
- **The spans tell a different story.** Error traces reach the culprit in thousands of traces for the
  degradations: sc-01 5,334 / 12,620, sc-02 3,950 / 7,475, sc-05 3,625 / 6,330, sc-09 3,556 / 6,313,
  sc-11 3,073 / 12,327, sc-15 3,641 / 6,398, sc-23 3,554 / 6,634, sc-04 1,021 / 5,011. Latency moves
  too: traces slower than the baseline p99 go 721 -> 19,914 in sc-11 and 431 -> 3,593 in sc-06.

**Baseline noise, a property of this deployment.** fulfillment-service logs about 39 ERROR lines a minute
in every window, healthy included (1,186 of 1,186 ERROR records in the 30-minute healthy capture):
`Inventory reservation failed ... inventory service returned status 404: {"error":"Product not found"}`.
It comes from deploying with `SEED_SIZE_GB=0` (an empty catalogue), and it is why `argmax` names
fulfillment-service in 24 of 27 captures. It does not change the S3 or PR results: those count traces,
and no trace from any erroring service reaches the culprit in the logs.

## What it means

On rca-lab the alive-and-degraded faults are real and visible, but **only in the spans**. The services do
not log about the slowness or the failed calls they experience, so the log stream holds no cross-service
evidence for trace_id to join. When a fault does produce error logs, they come from the culprit itself
(a per-service count already finds it) or from the caller of a crashed culprit (nothing to join to). The
stage comparison and the per-request task cannot be tested on these logs, and no model was run. The
per-request result in `REQUEST_FORENSICS_V2.md` (OTel Demo) is the measurement of trace-correlated logs;
this gate says rca-lab cannot add a second one without changing what the services log.

What would test trace context on rca-lab is a **span** task (the error spans do reach the culprit). That
is a different experiment and would need its own pre-registration; nothing here measures it.

Caveats: one run per scenario (two for sc-04 and sc-06); a single-node kind cluster with app replicas
scaled to 1 and an empty seed catalogue, not the lab's default sizing; 10 to 15 minute fault windows.
