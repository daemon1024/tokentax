"""Nezha (Train Ticket) loader + windowizer for the tokentax benchmark.

The Nezha RCA dataset (Yu et al., FSE 2023, MIT) ships per-minute CSVs whose log
rows already carry real OpenTelemetry-style ``TraceID``/``SpanID`` columns. This
module turns those CSVs into windows of ``LogRecord`` dicts and produces the three
benchmark variants (plain / structured / structured-no-trace) from a single source,
so Drain, in-context, and RLM all run on the SAME app (Train Ticket).

Log CSV schema:  Timestamp,TimeUnixNano,Node,PodName,Container,TraceID,SpanID,Log
The ``Log`` field is itself a JSON envelope: {"log": "<message>", "stream": ..., "time": ...}
and the message text *also* embeds "TraceID: <hex> SpanID: <hex>" — which leaks the
id into the body, so we scrub it so trace context lives ONLY in the structured field.
"""

from __future__ import annotations

import csv
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

csv.field_size_limit(sys.maxsize)  # log bodies can be large (stack traces)

# OTLP severity numbers (https://opentelemetry.io/docs/specs/otel/logs/data-model/)
_SEV = {"TRACE": 1, "DEBUG": 5, "INFO": 9, "WARN": 13, "WARNING": 13, "ERROR": 17, "FATAL": 21}
_LEVEL_RE = re.compile(r"\b(ERROR|WARN(?:ING)?|INFO|DEBUG|TRACE|FATAL)\b")

# Trace context that instrumentation writes into the MESSAGE TEXT, where dropping the trace_id
# FIELD cannot remove it. Two emitters produce it, and missing either one silently leaks the
# independent variable into the arm that is supposed to lack it:
#   Nezha / Train Ticket logback:  "... TraceID: <32hex> SpanID: <16hex> msg"
#   OTel logging instrumentation:  "... otelTraceID=<32hex> otelSpanID=<16hex> otelTraceSampled=true"
# Measured on data/otel_demo (64,356 records): the otel* form appears on 15.3% of records and was
# NOT matched by the original Nezha-only pattern.
_IDS_RE = re.compile(
    r"\s*(?:"
    r"TraceID:\s*[0-9a-fA-F]{16,32}\s*SpanID:\s*[0-9a-fA-F]{8,16}"
    r"|otelTraceID=[0-9a-fA-F]*"
    r"|otelSpanID=[0-9a-fA-F]*"
    r"|otelTraceSampled=\S*"
    r")\s*"
)

# Service identity written into the message text by the same instrumentation. This is a SEPARATE
# leak and a worse one: `plain` has no service field by construction, so `otelServiceName=` in the
# body hands it the exact variable the plain -> structured_no_trace contrast isolates.
_SVC_RE = re.compile(r"\s*otelServiceName=\S*\s*")

# Fault types whose injection produces ERROR logs (vs metrics/trace-only).
LOG_VISIBLE_TYPES = {"exception", "return"}
METRIC_ONLY_TYPES = {"cpu_contention", "cpu_consumed", "network_delay", "network_loss"}


@dataclass
class LogRecord:
    time_unix_nano: int
    node: str
    pod: str
    container: str
    trace_id: str
    span_id: str
    message: str          # the real log message (Log envelope unwrapped), ids NOT yet scrubbed
    level: str            # parsed severity text (e.g. ERROR), or "" if unknown
    parse_fail: bool      # True if the Log JSON envelope failed to parse

    @property
    def severity_number(self) -> int:
        return _SEV.get(self.level, 0)

    @property
    def is_error(self) -> bool:
        return self.level in ("ERROR", "FATAL")

    def body(self, scrub_ids: bool = True, scrub_service: bool = True) -> str:
        """The message text with emitted identity removed.

        Both defaults are True and should stay that way: the arms must differ ONLY by the fields
        `LogREPL` prefixes, never by what instrumentation happened to write into the text. Pass
        False only to inspect the raw leak (see `tests/test_nezha.py`).
        """
        out = self.message
        if scrub_ids:
            out = _IDS_RE.sub(" ", out)
        if scrub_service:
            out = _SVC_RE.sub(" ", out)
        return out.strip() if (scrub_ids or scrub_service) else out

    # --- the three benchmark variants, all from this single record ---
    def to_plain(self) -> str:
        """Plain: the message body only, with trace ids and service identity scrubbed out."""
        return self.body()

    def to_otlp(self, with_trace: bool = True) -> dict:
        """Structured OTLP LogRecord. with_trace=False => 'structured-no-trace'."""
        rec: dict = {
            "timeUnixNano": self.time_unix_nano,
            "severityText": self.level,
            "severityNumber": self.severity_number,
            "body": {"stringValue": self.body()},
            "attributes": [
                {"key": "pod", "value": {"stringValue": self.pod}},
                {"key": "container", "value": {"stringValue": self.container}},
                {"key": "node", "value": {"stringValue": self.node}},
            ],
        }
        if with_trace:
            rec["traceId"] = self.trace_id
            rec["spanId"] = self.span_id
        return rec


def _norm_level(s: str) -> str:
    s = s.strip().upper()
    return {"WARNING": "WARN", "ERR": "ERROR"}.get(s, s)


def _parse_log_field(raw: str) -> tuple[str, str, bool]:
    """Unwrap the Nezha ``Log`` envelope -> (message, level, parse_fail).

    Two shapes occur:
      Train Ticket: {"log": "19:50:59 INFO  ... TraceID: .. msg", ...}   (inner is plain text)
      Online Boutique: {"log": "{\\"message\\":\\"..\\",\\"severity\\":\\"info\\"}", ...}
    """
    raw = raw.strip()
    try:
        outer = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return raw, "", True
    inner = outer.get("log", raw) if isinstance(outer, dict) else raw
    inner = str(inner).rstrip("\n")
    # Online Boutique: inner is itself JSON with message + severity.
    try:
        j2 = json.loads(inner)
        if isinstance(j2, dict) and "message" in j2:
            return str(j2["message"]), _norm_level(str(j2.get("severity", ""))), False
    except (json.JSONDecodeError, ValueError):
        pass
    # Train Ticket: plain text; level is parsed by regex by the caller.
    return inner, "", False


def parse_log_csv(path: str | Path) -> list[LogRecord]:
    out: list[LogRecord] = []
    with open(path, newline="", encoding="utf-8", errors="replace") as f:
        for row in csv.DictReader(f):
            msg, level, pf = _parse_log_field(row.get("Log", "") or "")
            if not level:  # Train Ticket path: parse level token from the text
                m = _LEVEL_RE.search(msg)
                level = _norm_level(m.group(1)) if m else ""
            try:
                tun = int(row.get("TimeUnixNano") or 0)
            except ValueError:
                tun = 0
            out.append(LogRecord(
                time_unix_nano=tun,
                node=row.get("Node", "") or "",
                pod=row.get("PodName", "") or "",
                container=row.get("Container", "") or "",
                trace_id=(row.get("TraceID", "") or "").strip(),
                span_id=(row.get("SpanID", "") or "").strip(),
                message=msg,
                level=level,
                parse_fail=pf,
            ))
    return out


@dataclass
class Window:
    date: str            # "2023-01-30"
    minute: str          # "11_51"
    records: list[LogRecord]

    @property
    def key(self) -> str:
        return f"{self.date}/{self.minute}"

    @property
    def hour(self) -> str:
        return self.minute.split("_")[0]

    def trace_ids(self) -> set[str]:
        return {r.trace_id for r in self.records if r.trace_id}

    def multi_pod_trace_ids(self) -> set[str]:
        pods: dict[str, set[str]] = {}
        for r in self.records:
            if r.trace_id:
                pods.setdefault(r.trace_id, set()).add(r.pod)
        return {t for t, ps in pods.items() if len(ps) > 1}

    def n_errors(self) -> int:
        return sum(1 for r in self.records if r.is_error)


def load_windows(date_dir: str | Path) -> list[Window]:
    """Load all per-minute log windows under rca_data/<DATE>/log/."""
    date_dir = Path(date_dir)
    date = date_dir.name
    windows: list[Window] = []
    for csv_path in sorted((date_dir / "log").glob("*_log.csv")):
        minute = csv_path.name.replace("_log.csv", "")  # "11_51"
        windows.append(Window(date=date, minute=minute, records=parse_log_csv(csv_path)))
    return windows


def load_fault_episodes(date_dir: str | Path) -> list[dict]:
    """Flatten <DATE>-fault_list.json (keyed by hour) into a list of episodes."""
    date_dir = Path(date_dir)
    date = date_dir.name
    fl = json.load(open(date_dir / f"{date}-fault_list.json"))
    episodes: list[dict] = []
    for _hour, items in fl.items():
        for it in items:
            episodes.append({
                "date": date,
                "inject_time": it["inject_time"],          # "2023-01-30 11:51:46"
                "inject_minute": _to_minute(it["inject_time"]),  # "11_51"
                "inject_pod": it["inject_pod"],
                "service": _service_of(it["inject_pod"]),   # collapse replica suffix
                "inject_type": it["inject_type"],
            })
    return episodes


def _to_minute(inject_time: str) -> str:
    # "2023-01-30 11:51:46" -> "11_51"
    hms = inject_time.split(" ")[1]
    h, m, _s = hms.split(":")
    return f"{h}_{m}"


def _service_of(pod: str) -> str:
    # "ts-travel-service-64469b5b48-5rjvb" -> "ts-travel-service"
    return re.sub(r"-[0-9a-f]{6,10}-[0-9a-z]{5}$", "", pod)


# --- both Nezha systems, one harness ---
DATES = ["2022-08-22", "2022-08-23", "2023-01-29", "2023-01-30"]


def system_of(date: str) -> str:
    return "OnlineBoutique" if date.startswith("2022") else "TrainTicket"


def load_all_windows(raw_root: str | Path) -> list[Window]:
    """All per-minute windows across both systems (raw_root = .../Nezha/rca_data)."""
    raw_root = Path(raw_root)
    out: list[Window] = []
    for d in DATES:
        if (raw_root / d / "log").is_dir():
            out += load_windows(raw_root / d)
    return out


def episodes_by_window(raw_root: str | Path) -> dict[str, list[dict]]:
    """Map window key 'YYYY-MM-DD/HH_MM' -> list of fault episodes injected that minute."""
    raw_root = Path(raw_root)
    out: dict[str, list[dict]] = {}
    for d in DATES:
        if (raw_root / d / f"{d}-fault_list.json").exists():
            for ep in load_fault_episodes(raw_root / d):
                out.setdefault(f"{ep['date']}/{ep['inject_minute']}", []).append(ep)
    return out


def label_traces(window: Window, episodes: list[dict]) -> dict[str, bool]:
    """Derived trace-level anomaly labels for a fault window.

    A trace is anomalous iff it has >=1 log record on a pod that was fault-injected
    during this window (topology-based; does NOT use error text, so no label leak).
    Returns {} if the window has no injected fault (i.e. a normal window).
    """
    inject_pods = {ep["inject_pod"] for ep in episodes}
    inject_services = {ep["service"] for ep in episodes}
    if not inject_pods:
        return {}
    pods_by_trace: dict[str, set[str]] = {}
    for r in window.records:
        if r.trace_id:
            pods_by_trace.setdefault(r.trace_id, set()).add(r.pod)
    labels: dict[str, bool] = {}
    for tid, pods in pods_by_trace.items():
        hit = bool(pods & inject_pods) or bool({_service_of(p) for p in pods} & inject_services)
        labels[tid] = hit
    return labels


# --- benchmark dataset builders ---------------------------------------------------

def format_window(records: list[LogRecord], condition: str) -> str:
    """Render a window in one of the three conditions, for the in-context method.

    condition: 'plain' | 'structured' | 'structured_no_trace'
    """
    if condition == "plain":
        return "\n".join(r.to_plain() for r in records)
    if condition not in ("structured", "structured_no_trace"):
        raise ValueError(f"unknown condition: {condition}")
    with_trace = condition == "structured"
    return "\n".join(
        json.dumps(r.to_otlp(with_trace=with_trace), separators=(",", ":"), ensure_ascii=False)
        for r in records
    )


@dataclass
class TraceExample:
    """One (window, trace) example for the trace-anomaly-localization task."""
    system: str
    window_key: str       # 'YYYY-MM-DD/HH_MM' — also the group key for splitting
    trace_id: str
    records: list[LogRecord]
    label: int            # 1 anomalous (touches inject_pod), 0 normal
    n_pods: int

    def text(self, condition: str = "plain") -> str:
        return format_window(self.records, condition)

    @property
    def has_error(self) -> bool:
        return any(r.is_error for r in self.records)


def build_trace_anomaly_examples(
    raw_root: str | Path, exclude_degenerate: bool = True, degenerate_thresh: float = 0.9
) -> list[TraceExample]:
    """All (window, trace) examples from fault windows, with derived anomaly labels.

    Anomalous = the trace touches the injected pod (topology label, no error-text leak). Entry-point
    -degenerate fault windows (>thresh anomalous, e.g. OB frontend) are excluded by default.
    """
    windows = load_all_windows(raw_root)
    epw = episodes_by_window(raw_root)
    out: list[TraceExample] = []
    for w in windows:
        eps = epw.get(w.key, [])
        labels = label_traces(w, eps)
        if not labels:
            continue
        if exclude_degenerate and (sum(labels.values()) / len(labels)) > degenerate_thresh:
            continue
        recs_by_trace: dict[str, list[LogRecord]] = {}
        pods_by_trace: dict[str, set[str]] = {}
        for r in w.records:
            if r.trace_id in labels:
                recs_by_trace.setdefault(r.trace_id, []).append(r)
                pods_by_trace.setdefault(r.trace_id, set()).add(r.pod)
        for tid, lab in labels.items():
            out.append(TraceExample(
                system=system_of(w.date), window_key=w.key, trace_id=tid,
                records=recs_by_trace.get(tid, []), label=int(lab),
                n_pods=len(pods_by_trace.get(tid, set())),
            ))
    return out


@dataclass
class RootCauseExample:
    """One fault window for culprit-service localization (multi-class)."""
    system: str
    window_key: str
    records: list[LogRecord]
    culprit_service: str
    fault_type: str
    log_visible: bool


def build_root_cause_examples(raw_root: str | Path) -> list[RootCauseExample]:
    windows = load_all_windows(raw_root)
    epw = episodes_by_window(raw_root)
    wmap = {w.key: w for w in windows}
    out: list[RootCauseExample] = []
    for key, eps in epw.items():
        w = wmap.get(key)
        if w is None:
            continue
        for ep in eps:
            out.append(RootCauseExample(
                system=system_of(ep["date"]), window_key=key, records=w.records,
                culprit_service=ep["service"], fault_type=ep["inject_type"],
                log_visible=ep["inject_type"] in LOG_VISIBLE_TYPES,
            ))
    return out


def group_split(groups: list[str], test_frac: float = 0.3, seed: int = 0) -> set[str]:
    """Episode/window-keyed split: return the set of group keys assigned to TEST.

    Group-aware so no episode spans train+test (REVIEW LEAK-5). Deterministic given seed.
    """
    import random
    uniq = sorted(set(groups))
    rng = random.Random(seed)
    rng.shuffle(uniq)
    n_test = max(1, int(round(len(uniq) * test_frac)))
    return set(uniq[:n_test])
