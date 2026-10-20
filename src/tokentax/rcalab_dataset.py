"""The rca-lab capture DATASET: recorded telemetry that benchmarks replay instead of a live cluster.

Layout (one directory per capture, `data/rcalab/<name>/`, gitignored; index in the repo):

    logs.jsonl.zst     full OTLP-JSON resourceLogs from the host collector (sc-06: traces .gz, logs plain)
    traces.jsonl.zst   full OTLP-JSON resourceSpans
    meta.json          scenario CR, ground truth, window bounds (unix ns), cluster config, counts
    cluster/           raw kubectl/docker snapshots the meta was built from
    SHA256SUMS         every file above

    results/datasets/rcalab_manifest.json   one entry per capture (path, windows, culprit, counts, sha256)
    results/datasets/RCALAB_DATASET.md      what the dataset is and is not

Benchmarks should load through this module:

    from tokentax import rcalab_dataset as D
    for cap in D.captures():                       # verified captures only, unless asked otherwise
        w = cap.window("fault")                    # Window: .records (LogRecord list), .truth, .key
        b = cap.window("baseline")                 # truth culprit_service is None ("no fault")
    for w in D.iter_windows("fault", length_s=60): # fixed-length sub-windows, ground truth attached

Log parsing is `otel_loader.parse_otlp_jsonl` itself (a compressed file is decompressed to a temporary
file first), so a record loaded here is byte-for-byte the record every earlier harness saw.
"""

from __future__ import annotations

import hashlib
import json
import statistics as st
import tempfile
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from tokentax.nezha import LogRecord, _service_of
from tokentax.otel_loader import parse_otlp_jsonl
from tokentax.rcalab import Span, iter_spans, open_text

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MANIFEST = ROOT / "results/datasets/rcalab_manifest.json"
WINDOW_KINDS = ("baseline", "fault", "recovery")

# ---------------------------------------------------------------------------------------------------
# Ground truth, written from each scenario's CR text (description + expectedSymptoms) BEFORE its capture.
#
#   culprit_service    the application service a responder should name: the service whose own code or
#                      own dependency carries the fault and through which it becomes user-visible.
#                      None when no single application service is at fault (DNS for everyone, a
#                      DB-internal latent risk, a conflict between two batch jobs).
#   culprit_component  the actual cause, which is often NOT an application service (a database session,
#                      a co-tenant workload, a network path).
#   culprit_is_app_service  False when culprit_component is outside the application services.
#   fault_class        crash | degradation | db-lock | db-resource | db-availability | db-internal |
#                      network | infra-contention | load | none
#   topology_caveat    why the mechanism may not reproduce on this lab (SEED_SIZE_GB=0, SINGLE_NODE=1).
# ---------------------------------------------------------------------------------------------------
_SEED = ("SEED_SIZE_GB=0: tables/collections are not at the size the CR assumes; "
         "the effect may be weak or absent.")
_ONE = ("SINGLE_NODE=1: the database runs as ONE member; "
        "the multi-member mechanism the CR describes cannot occur.")


def _gt(svc, comp, cls, app, affected=(), caveat=""):
    return {"culprit_service": svc, "culprit_component": comp, "fault_class": cls,
            "culprit_is_app_service": app, "affected_services": list(affected), "topology_caveat": caveat}


GROUND_TRUTH: dict[str, dict] = {
    "sc-01": _gt("review-service", "mongodb: unindexed COLLSCAN queries from a batch workload",
                 "db-resource", False, ["review-service", "api-gateway"], _SEED),
    "sc-02": _gt("review-service", "mongodb: repeated forced primary step-down", "db-availability", False,
                 ["review-service"], _ONE),
    "sc-03": _gt("order-service", "mysql: 'analytics-reporting' batch queries saturating PXC CPU",
                 "db-resource", False, ["order-service", "cart-service"], _SEED),
    "sc-04": _gt("order-service", "mysql: stalled transaction holding InnoDB row locks on orders",
                 "db-lock", False, ["order-service", "cart-service", "fulfillment-service"]),
    "sc-05": _gt("product-catalog", "postgres: 'analytics-reporting' batch queries on products",
                 "db-resource", False, ["product-catalog", "inventory-service"], _SEED),
    "sc-06": _gt("product-catalog", "postgres: stalled migration holding ACCESS EXCLUSIVE on products",
                 "db-lock", False, ["product-catalog", "api-gateway"]),
    "sc-07": _gt("order-service", "order-service 1.3.0 bad deploy: allocation regression / GC pressure",
                 "degradation", True, ["order-service"]),
    "sc-08": _gt("order-service", "order-service 1.4.0 bad deploy: slow leak of small objects",
                 "degradation", True, ["order-service"]),
    "sc-09": _gt("product-catalog", "product-catalog 1.1.0 bad deploy: GC (allocation) pressure",
                 "degradation", True, ["product-catalog", "api-gateway"]),
    "sc-10": _gt("recommendation-service", "recommendation-service 1.1.0 memory leak -> repeated OOMKill",
                 "crash", True, ["recommendation-service", "product-catalog", "api-gateway"]),
    "sc-11": _gt("review-service", "review-service 1.2.0 bad deploy: synchronous CPU loop blocks event loop",
                 "degradation", True, ["review-service", "api-gateway"]),
    "sc-12": _gt("order-service", "co-located 'video-transcoder' batch workload starving node CPU",
                 "infra-contention", False, ["order-service"],
                 "SINGLE_NODE=1: the noisy neighbour shares the node with EVERY service, "
                 "not only order-service."),
    "sc-13": _gt("load-generator", "traffic spike: load-generator scaled to 5 replicas", "load", True,
                 ["api-gateway"]),
    "sc-14": _gt(None, "network path to cluster DNS: +500ms per lookup for all app services", "network",
                 False, ["api-gateway", "product-catalog", "order-service", "cart-service"]),
    "sc-15": _gt("product-catalog", "network: +200ms (+-50ms) on packets arriving at product-catalog",
                 "network", False, ["product-catalog", "api-gateway"]),
    "sc-19": _gt(None, "mysql (Galera): two batch writers conflicting on one row across nodes",
                 "db-internal", False, [], _ONE),
    "sc-20": _gt(None, "mysql (Galera): one PXC node partitioned off the cluster", "db-availability",
                 False, ["order-service", "payment-service"], _ONE),
    "sc-21": _gt(None, "postgres: requested checkpoints under a write-heavy batch", "db-internal", False,
                 [], _SEED),
    "sc-22": _gt(None, "postgres: standby replication lag under +800ms network delay", "db-internal", False,
                 [], _ONE),
    "sc-23": _gt("product-catalog", "postgres: stale planner statistics after a large data change",
                 "db-resource", False, ["product-catalog"], _SEED),
    "sc-24": _gt(None, "postgres: table bloat (autovacuum disabled + churn), latent", "db-internal", False,
                 [], _SEED),
    "sc-25": _gt(None, "postgres: vacuum held back by a long-running transaction, latent", "db-internal",
                 False, [], _SEED),
    "sc-26": _gt("order-service", "mysql: dropped idx_orders_user_created (full scans per request)",
                 "db-resource", False, ["order-service", "api-gateway"], _SEED),
    "sc-27": _gt(None, "postgres: transaction-id wraparound risk (freezing blocked), latent", "db-internal",
                 False, [], _SEED),
    "sc-28": _gt(None, "postgres: checkpoints stalled on a fenced standby", "db-internal", False, [], _ONE),
    "healthy": _gt(None, "none: no scenario enabled", "none", False, []),
}

NO_FAULT = {"culprit_service": None, "culprit_component": "none (window outside the fault)",
            "fault_class": "none", "culprit_is_app_service": False, "affected_services": [],
            "topology_caveat": ""}


def truth_for(scenario: str, kind: str) -> dict:
    """Ground truth for a window. Baseline and recovery windows are 'no fault' by construction."""
    if kind != "fault":
        return dict(NO_FAULT)
    return dict(GROUND_TRUTH.get(scenario, {"culprit_service": "unknown", "culprit_component": "unknown",
                                            "fault_class": "unknown", "culprit_is_app_service": "unknown",
                                            "affected_services": [], "topology_caveat": ""}))


# ---------------------------------------------------------------------------------------------------
# files
# ---------------------------------------------------------------------------------------------------
def sha256_file(path: str | Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def find_file(d: Path, stem: str) -> Path | None:
    """`logs` -> logs.jsonl.zst | logs.jsonl.gz | logs.jsonl, whichever exists (in that order)."""
    for suffix in (".jsonl.zst", ".jsonl.gz", ".jsonl"):
        p = d / f"{stem}{suffix}"
        if p.exists():
            return p
    return None


def parse_logs(path: str | Path) -> list[LogRecord]:
    """`otel_loader.parse_otlp_jsonl` on a plain, .gz or .zst file, time-sorted."""
    p = Path(path)
    if p.suffix == ".jsonl":
        recs = parse_otlp_jsonl(p)
    else:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td) / "logs.jsonl"
            with open_text(p) as src, open(tmp, "w", encoding="utf-8") as dst:
                for line in src:
                    dst.write(line)
            recs = parse_otlp_jsonl(tmp)
    recs.sort(key=lambda r: r.time_unix_nano)
    return recs


# ---------------------------------------------------------------------------------------------------
# captures and windows
# ---------------------------------------------------------------------------------------------------
@dataclass
class Window:
    """One labelled interval of one capture. Shaped like `otel_loader.LabeledWindow` (records / key /
    fault / label), so `forensics.eligible_cases` and the RLM methods accept it unchanged."""
    capture: str
    scenario: str
    kind: str                      # baseline | fault | recovery
    start_ns: int
    end_ns: int
    records: list[LogRecord]
    truth: dict

    @property
    def fault(self) -> str | None:
        return self.scenario if self.kind == "fault" and self.scenario != "healthy" else None

    @property
    def label(self) -> str:
        return "anomalous" if self.fault else "normal"

    @property
    def key(self) -> str:
        return f"{self.capture}:{self.kind}@{self.start_ns}"


@dataclass
class Capture:
    name: str
    path: Path
    entry: dict
    meta: dict = field(default_factory=dict)
    _records: list[LogRecord] | None = None

    @property
    def scenario(self) -> str:
        return self.entry.get("scenario", self.name)

    @property
    def verified(self) -> bool:
        return bool(self.entry.get("effect_verified")) or self.scenario == "healthy"

    def bounds(self, kind: str) -> tuple[int, int] | None:
        b = (self.entry.get("windows") or {}).get(kind)
        if not b or b[0] in (None, "unknown") or b[1] in (None, "unknown"):
            return None
        return int(b[0]), int(b[1])

    def _named(self, key: str) -> Path | None:
        f = (self.entry.get("files") or {}).get(key)
        return (self.path / f) if f and (self.path / f).exists() else None

    def logs_path(self) -> Path:
        p = self._named("logs") or find_file(self.path, "logs")
        if p is None:
            raise FileNotFoundError(f"no logs file in {self.path}")
        return p

    def traces_path(self) -> Path | None:
        return self._named("traces") or find_file(self.path, "traces")

    def records(self) -> list[LogRecord]:
        if self._records is None:
            self._records = parse_logs(self.logs_path())
        return self._records

    def window(self, kind: str) -> Window:
        b = self.bounds(kind)
        if b is None:
            raise ValueError(f"{self.name}: no {kind} window recorded")
        recs = [r for r in self.records() if b[0] <= r.time_unix_nano <= b[1]]
        return Window(self.name, self.scenario, kind, b[0], b[1], recs, truth_for(self.scenario, kind))

    def spans(self, kind: str) -> list[Span]:
        b = self.bounds(kind)
        tp = self.traces_path()
        if b is None or tp is None:
            return []
        return list(iter_spans(tp, b[0], b[1]))


def load_manifest(path: str | Path = DEFAULT_MANIFEST) -> dict:
    return json.loads(Path(path).read_text())


def captures(manifest: str | Path | dict = DEFAULT_MANIFEST, data_root: str | Path | None = None,
             include_unverified: bool = False, scenario: str | None = None) -> list[Capture]:
    """Captures listed in the manifest whose files are on disk.

    By default only captures whose fault effect was VERIFIED live are returned: results/RCA_LAB_CAPTURE.md
    was retracted because a capture with no scenario running was analysed as a fault.
    """
    m = manifest if isinstance(manifest, dict) else load_manifest(manifest)
    root = Path(data_root) if data_root else ROOT
    out = []
    for e in m.get("captures", []):
        if e.get("status", "ok") != "ok":
            continue
        if scenario and e.get("scenario") != scenario:
            continue
        p = root / e["path"]
        if not p.exists():
            continue
        c = Capture(e["name"], p, e)
        if (p / "meta.json").exists():
            c.meta = json.loads((p / "meta.json").read_text())
        if c.verified or include_unverified:
            out.append(c)
    return out


def subwindows(w: Window, length_s: float) -> list[Window]:
    """Non-overlapping fixed-length slices of a window; a trailing partial slice is dropped."""
    step = int(length_s * 1e9)
    out, t = [], w.start_ns
    while t + step <= w.end_ns + 1:
        recs = [r for r in w.records if t <= r.time_unix_nano < t + step]
        out.append(Window(w.capture, w.scenario, w.kind, t, t + step, recs, dict(w.truth)))
        t += step
    return out


def iter_windows(kind: str = "fault", length_s: float | None = None, **kw):
    for c in captures(**kw):
        if c.bounds(kind) is None:
            continue
        w = c.window(kind)
        yield from (subwindows(w, length_s) if length_s else [w])


# ---------------------------------------------------------------------------------------------------
# counts for meta.json (streaming: the full sc-10 capture is ~19 GB of span JSON)
# ---------------------------------------------------------------------------------------------------
def _which(t: int, bounds: dict[str, tuple[int, int] | None]) -> str | None:
    for k, b in bounds.items():
        if b and b[0] <= t <= b[1]:
            return k
    return None


def count_logs(path: str | Path, bounds: dict[str, tuple[int, int] | None]) -> dict:
    recs = parse_logs(path)
    groups: dict[str, list[LogRecord]] = {"all": recs}
    for k, b in bounds.items():
        if b:
            groups[k] = [r for r in recs if b[0] <= r.time_unix_nano <= b[1]]
    out = {}
    for k, rs in groups.items():
        out[k] = {
            "log_records": len(rs),
            "error_records": sum(1 for r in rs if r.is_error),
            "records_with_trace_id": sum(1 for r in rs if r.trace_id),
            "error_records_with_trace_id": sum(1 for r in rs if r.is_error and r.trace_id),
            "records_by_service": dict(Counter(_service_of(r.pod) for r in rs).most_common()),
            "errors_by_service": dict(Counter(_service_of(r.pod) for r in rs if r.is_error).most_common()),
            "first_ns": rs[0].time_unix_nano if rs else None,
            "last_ns": rs[-1].time_unix_nano if rs else None,
        }
    return out


class _DistinctIds:
    """Distinct trace ids. Exact `set` by default; `compact` keeps the first 64 bits of each id in a
    uint64 array (with a small recent-id filter) and deduplicates with numpy at the end, so a
    multi-day file fits in memory. The compact count is EXACT over 64-bit prefixes; two distinct
    random 128-bit OTel trace ids share a 64-bit prefix with probability ~n^2 / 2^65."""

    def __init__(self, compact: bool):
        self.compact = compact
        if compact:
            from array import array
            self.buf, self.recent = array("Q"), set()
        else:
            self.ids: set = set()

    def add(self, tid: str) -> None:
        if not self.compact:
            self.ids.add(tid)
            return
        try:
            v = int(tid[:16], 16)
        except ValueError:
            v = 0
        if v not in self.recent:
            self.recent.add(v)
            self.buf.append(v)
            if len(self.recent) > 200_000:
                self.recent.clear()

    def __len__(self) -> int:
        if not self.compact:
            return len(self.ids)
        import numpy as np
        return int(np.unique(np.frombuffer(self.buf, dtype=np.uint64)).size) if len(self.buf) else 0


def count_spans(path: str | Path, bounds: dict[str, tuple[int, int] | None], latency: bool = True,
                compact: bool = False) -> dict:
    """Spans / traces / error-bearing traces per window (by span START time) and over the whole file.

    `latency` adds p50/p99 of root-span duration per window -- the data-visible effect of a latency
    fault (one float per root span). `compact` switches distinct-trace counting to 64-bit prefixes
    (see `_DistinctIds`) for multi-day files.
    """
    keys = ["all"] + [k for k, b in bounds.items() if b]
    spans = Counter()
    traces = {k: _DistinctIds(compact) for k in keys}
    err_traces = {k: _DistinctIds(compact) for k in keys}
    err_by_svc: dict[str, Counter] = {k: Counter() for k in keys}
    roots: dict[str, list[float]] = defaultdict(list)
    first = last = None
    for s in iter_spans(path):
        w = _which(s.start_ns, bounds)
        first = s.start_ns if first is None else min(first, s.start_ns)
        last = s.start_ns if last is None else max(last, s.start_ns)
        for k in ("all", w) if w else ("all",):
            spans[k] += 1
            traces[k].add(s.trace_id)
            if s.is_error:
                err_traces[k].add(s.trace_id)
                err_by_svc[k][s.service] += 1
        if latency and w and not s.parent_id:
            roots[w].append(s.duration_ms)
    out = {}
    for k in keys:
        out[k] = {"spans": spans[k], "traces": len(traces[k]), "error_bearing_traces": len(err_traces[k]),
                  "error_spans_by_service": dict(err_by_svc[k].most_common())}
        if compact:
            out[k]["trace_count_method"] = "distinct 64-bit trace-id prefixes"
        if latency and k in roots and roots[k]:
            v = sorted(roots[k])
            out[k]["root_span_ms_p50"] = round(st.median(v), 2)
            out[k]["root_span_ms_p99"] = round(v[min(len(v) - 1, int(0.99 * len(v)))], 2)
    out["all"]["first_start_ns"], out["all"]["last_start_ns"] = first, last
    return out
