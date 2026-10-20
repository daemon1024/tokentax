"""rca-lab captures: spans, windows, and the model-free reachability measures the gate is built on.

Inputs are the two files the host collector writes (`infra/rcalab-capture-collector.yaml`): OTLP-JSON
`resourceLogs` (read by `otel_loader.parse_otlp_jsonl`) and OTLP-JSON `resourceSpans` (read here).

Every function in this module is pure and model-free. It answers the questions that decide whether a
model run on a scenario could possibly test anything, before any token is spent:

  * is there a fault signal in the LOGS at all (ERROR records above the baseline rate)?
  * does `argmax(errors_by_service)` already name the culprit (then a digest answers it without a join)?
  * can the culprit be reached by `trace_id` from an erroring log line, in LOGS and in SPANS?

Definitions are the ones `results/SC10_CRASH_FAULT.md` and `talk/NUMBERS.md` claim 9 used, so a
number computed here on the sc-10 files reproduces the published one.
"""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

from tokentax.nezha import LogRecord, _service_of

STATUS_ERROR = 2   # OTLP Status.code: 0 unset, 1 ok, 2 error


@dataclass(frozen=True)
class Span:
    trace_id: str
    span_id: str
    parent_id: str
    service: str
    name: str
    start_ns: int
    end_ns: int
    status_code: int
    kind: int

    @property
    def is_error(self) -> bool:
        return self.status_code == STATUS_ERROR

    @property
    def duration_ms(self) -> float:
        return (self.end_ns - self.start_ns) / 1e6


def _res_service(resource: dict) -> str:
    for a in resource.get("attributes", []) or []:
        if a.get("key") == "service.name":
            return str((a.get("value") or {}).get("stringValue", "") or "")
    return ""


def open_text(path: str | Path):
    """Open a capture file as text whether it is plain, `.gz` or `.zst` (the dataset stores both)."""
    p = str(path)
    if p.endswith(".zst"):
        from compression import zstd  # stdlib since Python 3.14
        return zstd.open(p, "rt", encoding="utf-8", errors="replace")
    if p.endswith(".gz"):
        import gzip
        return gzip.open(p, "rt", encoding="utf-8", errors="replace")
    return open(p, encoding="utf-8", errors="replace")


def iter_spans(path: str | Path, start_ns: int | None = None, end_ns: int | None = None):
    """Stream spans from a collector file-exporter trace file. Unparseable lines (a byte-cut tail) are
    skipped. `start_ns`/`end_ns` keep only spans whose START lies in [start_ns, end_ns], so the trace
    file can be windowed by the same clock the log windows use."""
    with open_text(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                doc = json.loads(line)
            except json.JSONDecodeError:
                continue
            for rs in doc.get("resourceSpans", []) or []:
                svc = _res_service(rs.get("resource", {}) or {})
                for ss in rs.get("scopeSpans", []) or []:
                    for s in ss.get("spans", []) or []:
                        try:
                            st = int(s.get("startTimeUnixNano") or 0)
                            en = int(s.get("endTimeUnixNano") or 0)
                        except (TypeError, ValueError):
                            continue
                        if start_ns is not None and st < start_ns:
                            continue
                        if end_ns is not None and st > end_ns:
                            continue
                        yield Span(
                            trace_id=str(s.get("traceId", "") or ""),
                            span_id=str(s.get("spanId", "") or ""),
                            parent_id=str(s.get("parentSpanId", "") or ""),
                            service=svc, name=str(s.get("name", "") or ""),
                            start_ns=st, end_ns=en,
                            status_code=int((s.get("status") or {}).get("code", 0) or 0),
                            kind=int(s.get("kind", 0) or 0))


def parse_spans(path: str | Path, start_ns: int | None = None, end_ns: int | None = None) -> list[Span]:
    """`iter_spans` as a list."""
    return list(iter_spans(path, start_ns, end_ns))


def window(records: list[LogRecord], start_ns: int, end_ns: int) -> list[LogRecord]:
    """Records with start_ns <= time <= end_ns, time-sorted (ForensicsREPL requires sorted input)."""
    return sorted((r for r in records if start_ns <= r.time_unix_nano <= end_ns),
                  key=lambda r: r.time_unix_nano)


def errors_by_service(records: list[LogRecord]) -> Counter:
    return Counter(_service_of(r.pod) for r in records if r.is_error)


def argmax_service(counts: Counter) -> tuple[str | None, bool]:
    """(top service, tied). A tie at the top is reported, never silently broken by insertion order.

    `talk/NUMBERS.md` claim 6 found one Nezha "correct" argmax that was a tie won by dict order.
    """
    if not counts:
        return None, False
    ranked = counts.most_common()
    top_n = ranked[0][1]
    tied = sum(1 for _, n in ranked if n == top_n) > 1
    return ranked[0][0], tied


def argmax_correct(counts: Counter, culprit: str) -> bool:
    """Strict: correct only if the culprit is the UNIQUE top service."""
    top, tied = argmax_service(counts)
    return top == culprit and not tied


def _stem(service: str) -> str:
    """'recommendation-service' -> 'recommendation'; used to ask whether error TEXT names a service."""
    return re.sub(r"[-_ ]?(service|svc)$", "", service.lower())


def culprit_named_in_errors(records: list[LogRecord], culprit: str) -> int:
    """ERROR records NOT emitted by the culprit whose body mentions the culprit's name stem.

    This is the semantic route sc-10 left open ('recommendations rpc failed' names the dead callee).
    """
    stem = _stem(culprit)
    return sum(1 for r in records
               if r.is_error and _service_of(r.pod) != culprit and stem and stem in r.to_plain().lower())


def log_reach(records: list[LogRecord], culprit: str) -> dict:
    """Can trace_id carry an erroring LOG line to a log line of the culprit?

    erroring trace := a trace_id carried by >= 1 ERROR record.
    foreign-erroring trace := an erroring trace with an ERROR record from a service other than the culprit.
    reach := a foreign-erroring trace that ALSO has a log record (any severity) from the culprit. This is
    the only case where following trace_id from a symptom line lands on the cause; when the culprit is the
    only erroring service, the digest already names it and no join is needed.
    """
    by_trace: dict[str, list[LogRecord]] = defaultdict(list)
    for r in records:
        if r.trace_id:
            by_trace[r.trace_id].append(r)
    erroring = {t: rs for t, rs in by_trace.items() if any(r.is_error for r in rs)}
    foreign = {t: rs for t, rs in erroring.items()
               if any(r.is_error and _service_of(r.pod) != culprit for r in rs)}
    reach = [t for t, rs in foreign.items() if any(_service_of(r.pod) == culprit for r in rs)]
    nsvc = [len({_service_of(r.pod) for r in rs}) for rs in erroring.values()]
    errs = [r for r in records if r.is_error]
    return {
        "error_records": len(errs),
        "error_records_with_trace": sum(1 for r in errs if r.trace_id),
        "erroring_traces": len(erroring),
        "foreign_erroring_traces": len(foreign),
        "reach_traces": len(reach),
        "reach_frac_of_foreign": (len(reach) / len(foreign)) if foreign else 0.0,
        "multi_service_erroring_traces": sum(1 for n in nsvc if n >= 2),
        "median_services_per_erroring_trace": (sorted(nsvc)[len(nsvc) // 2] if nsvc else 0),
        "culprit_log_records": sum(1 for r in records if _service_of(r.pod) == culprit),
        "culprit_error_records": sum(1 for r in errs if _service_of(r.pod) == culprit),
    }


def span_reach(spans: list[Span], culprit: str, slow_ms: float | None = None) -> dict:
    """Same question in SPANS: do error-bearing (or slow) traces include a span from the culprit?

    `slow_ms`: a trace counts as slow if any span with no parent in the trace (a root) lasts longer.
    Degradation faults may raise latency without setting error status, so both views are reported.
    """
    by_trace: dict[str, list[Span]] = defaultdict(list)
    for s in spans:
        if s.trace_id:
            by_trace[s.trace_id].append(s)
    err_tr = {t: ss for t, ss in by_trace.items() if any(s.is_error for s in ss)}
    out = {
        "spans": len(spans),
        "traces": len(by_trace),
        "error_spans_by_service": dict(Counter(s.service for s in spans if s.is_error).most_common()),
        "error_traces": len(err_tr),
        "error_traces_reaching_culprit": sum(1 for ss in err_tr.values()
                                             if any(s.service == culprit for s in ss)),
        "culprit_spans": sum(1 for s in spans if s.service == culprit),
        "culprit_error_spans": sum(1 for s in spans if s.service == culprit and s.is_error),
        "median_services_per_error_trace": (
            sorted(len({s.service for s in ss}) for ss in err_tr.values())[len(err_tr) // 2]
            if err_tr else 0),
    }
    if slow_ms is not None:
        slow = {}
        for t, ss in by_trace.items():
            ids = {s.span_id for s in ss}
            roots = [s for s in ss if not s.parent_id or s.parent_id not in ids]
            if roots and max(r.duration_ms for r in roots) > slow_ms:
                slow[t] = ss
        out["slow_ms"] = slow_ms
        out["slow_traces"] = len(slow)
        out["slow_traces_reaching_culprit"] = sum(1 for ss in slow.values()
                                                  if any(s.service == culprit for s in ss))
    return out


def root_duration_quantile(spans: list[Span], q: float) -> float | None:
    """q-quantile of per-trace root-span duration (ms); used to set `slow_ms` from the BASELINE."""
    by_trace: dict[str, list[Span]] = defaultdict(list)
    for s in spans:
        if s.trace_id:
            by_trace[s.trace_id].append(s)
    durs = []
    for ss in by_trace.values():
        ids = {s.span_id for s in ss}
        roots = [s for s in ss if not s.parent_id or s.parent_id not in ids]
        if roots:
            durs.append(max(r.duration_ms for r in roots))
    if not durs:
        return None
    durs.sort()
    return durs[min(len(durs) - 1, int(q * len(durs)))]
