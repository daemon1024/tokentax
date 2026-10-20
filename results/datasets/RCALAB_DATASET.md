# rca-lab capture dataset

Recorded OpenTelemetry **logs and traces** from coroot/rca-lab with real faults injected by the lab's own
scenario operator, kept so that benchmarks **replay recorded telemetry instead of running a cluster**.

- **Index (in git):** `results/datasets/rcalab_manifest.json`: one entry per capture with path, window
  bounds, ground truth, counts, sha256 of every data file, and the backup location.
- **Data (gitignored, one machine):** `data/rcalab/<name>/`. **Backup:** `~/tokentax-backup/rcalab/<name>/`,
  checksum-verified at copy time. Both copies are on the SAME disk, so this is not an off-machine backup.
- **Loader:** `src/tokentax/rcalab_dataset.py` (offline tests: `tests/test_rcalab_dataset.py`).
- **Recording code:** `infra/rcalab_capture_dataset.sh` (one capture), `infra/rcalab_campaign.sh` +
  `infra/rcalab_campaign_plan.txt` (the campaign), `infra/rcalab_effect_check.py` (is the fault really on?),
  `infra/rcalab_capture_watchdog.sh` (size caps), `scripts/rcalab_dataset_meta.py` (meta, checksums, backup,
  manifest), `scripts/rcalab_gate.py` (the model-free gate).

## Loading

```python
from tokentax import rcalab_dataset as D

for cap in D.captures():                    # verified captures only (effect observed live)
    fault = cap.window("fault")             # .records: list[LogRecord], time-sorted
    print(cap.name, fault.truth["culprit_service"], len(fault.records))
    base = cap.window("baseline")           # truth: no fault
    spans = cap.spans("fault")              # list[rcalab.Span], streamed from the trace file

for w in D.iter_windows("fault", length_s=60):   # fixed 60 s sub-windows, ground truth attached
    ...
```

Records are parsed by `otel_loader.parse_otlp_jsonl` itself (a compressed file is decompressed to a
temporary file first), so they are exactly what every other harness in this repo sees. A `Window` has the
`records / key / fault / label` shape of `otel_loader.LabeledWindow`, so `forensics.eligible_cases` and
the RLM methods take it unchanged. `D.captures(include_unverified=True)` also returns captures whose fault
effect was never observed. They are kept for completeness and excluded by default, because
`results/RCA_LAB_CAPTURE.md` was retracted for analysing a capture in which no scenario was running.

## What a capture contains

| file | content |
|---|---|
| `logs.jsonl.zst` | every OTLP-JSON `resourceLogs` batch the host collector received, one per line |
| `traces.jsonl.zst` | every OTLP-JSON `resourceSpans` batch (FULL output, not a sample) |
| `meta.json` | scenario CR spec, ground truth, window bounds, effect evidence, cluster config, collector, load generator, counts |
| `meta_raw.json` | what the driver wrote at capture time (host-clock bounds), unmodified |
| `cluster/` | raw `kubectl`/`docker` JSON snapshots the meta was built from (baseline end, mid-fault, recovery end) |
| `SHA256SUMS` | sha256 of every file above (`shasum -a 256 -c SHA256SUMS`) |

Compression is `zstd -T8 -6`. **Exception: `sc-06`** keeps its traces as `gzip -6` and its logs uncompressed,
as first written. The loader opens `.zst`, `.gz` and plain files transparently.

**Windows** (unix ns, host wall clock; the records carry the cluster's `timeUnixNano`, the same Docker-VM
clock):

- `baseline`: no scenario enabled (≈5 min);
- `fault`: from the moment the controller's `"starting run"` line for the scenario was seen, to the
  disable (or the CR's own duration ending, whichever came first);
- `recovery`: from the disable for ≈5 min;
- `healthy`: a capture with no scenario, its whole span stored as `baseline`.

**Ground truth** (`rcalab_dataset.GROUND_TRUTH`, written from each CR's description and `expectedSymptoms`
before the capture):

- `culprit_service` is the application service a responder should name: the one whose own code or own
  dependency carries the fault. It is `None` when no single service is at fault (DNS for every service, a
  DB-internal latent risk).
- `culprit_component` is the actual cause, which is often not an application service (a database session,
  a co-tenant workload, a network path).
- `fault_class` is a coarse family, and `topology_caveat` says why the mechanism may not reproduce on this
  lab.

## The lab these captures come from

kind cluster `rca-lab`, one node (Kubernetes v1.35.0), on Docker Desktop with 11.67 GiB / 8 CPUs, Apple
Silicon. rca-lab @ `585c45a`, deployed with `make deploy SINGLE_NODE=1 SEED_SIZE_GB=0 YES=1`; then every
application deployment was scaled to 1 replica (the node was at 95% CPU / 86% memory requests at 2).
rca-lab publishes linux/amd64 images only, so **every rca-lab image, including the bad-deploy variants,
was built locally for arm64** and side-loaded. Chaos Mesh's daemon was pointed at kind's containerd socket
(the lab's values file targets k3s). Telemetry path: app SDKs → in-cluster `otel-collector` (memory_limiter
400 MiB, batch) → host collector `otelcol-contrib 0.158.0` (`infra/rcalab-capture-collector.yaml`) → file
exporter. Per-capture image tags and digests, replica counts and collector config hashes are in `meta.json`.

## Known properties of the data (read before using it)

1. **The logs are thin, and that is the lab, not a capture fault.** `api-gateway` (Python, uvicorn
   `--workers 4`) exports traces but **no log records**. `product-catalog`, `review-service`,
   `cart-service` and `recommendation-service` do not log request-path errors (source-verified in
   `results/RCA_LAB_CAPTURE.md`). Many faults are therefore visible in spans and invisible in logs.
2. **Ambient error noise.** With `SEED_SIZE_GB=0` there are no seeded products, so `fulfillment-service`
   logs ≈40 `Inventory reservation failed ... Product not found` ERRORs per minute in every window,
   faulted or not. It is a realistic distractor for any count-based localiser.
3. **`SEED_SIZE_GB=0` and `SINGLE_NODE=1` change some mechanisms.** Table scans over tiny tables are cheap.
   Replica-set, Galera and standby scenarios run against one-member databases. Each entry's
   `topology_caveat` says so; whether the effect appeared is in `meta.json → effect` and in the per-window
   span counts and root-span p99.
4. **Repairs, all recorded in the entry's `legacy_note`.** `sc-06` and `sc-11` trace files began with a run
   of NUL bytes (588 MB, 1.16 GB) because the live file had been truncated from the host while the
   collector held it open. The NULs were stripped; no record was lost in sc-06, and the first batch was
   recovered in sc-11. `sc-11`'s compressed trace file was left unterminated (compressed while still
   growing) and was salvaged, losing ≈140 KB after its recovery window ended. The driver now stops the
   collector around every truncation and before compressing.
5. **`sc-04` and `sc-06` are short-format captures** (180 s baseline, 300 s fault, no recovery window),
   recorded before this dataset's spec. Their `cluster/` snapshot was taken after the capture.
6. **`sc-10_full` and `sc-10_partial` come from an earlier cluster** (2026-09-12) whose configuration was
   not recorded: those cluster fields are `unknown`. sc-10_full's fault bounds are **derived from the
   data** (first..last product-catalog `recommendations rpc failed`). Its `baseline` is a healthy stretch
   AFTER the fault. It also contains an **unexplained ≈10-min error burst** on 2026-09-14T14:09Z, recorded
   in `meta_raw.json → unlabelled_incident` and kept out of every labelled window. In `sc-10_partial` (the
   copy behind `results/SC10_CRASH_FAULT.md`) the log slice (12:32:01–12:36:03Z) and the span sample
   (12:36:11–12:38:25Z) cover **disjoint intervals**.
7. **One capture per scenario, one machine, one load level** (the lab's default load generator).

## Captures

(generated from the manifest at the end of the campaign)
