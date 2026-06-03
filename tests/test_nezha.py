"""Unit tests for the Nezha windowizer + dataset builders (no large-data dependency)."""

from __future__ import annotations

from tokentax.nezha import (
    LogRecord,
    Window,
    _parse_log_field,
    format_window,
    group_split,
    label_traces,
)

TID = "2ffbc4a03bbc5600a45841d05e452454"
SID = "04ba577c01a08838"


def _rec(pod, trace, msg, level="INFO"):
    return LogRecord(
        time_unix_nano=1, node="n", pod=pod, container="server",
        trace_id=trace, span_id=SID, message=msg, level=level, parse_fail=False,
    )


def test_plain_scrubs_trace_ids():
    r = _rec("ts-x", TID, f"INFO doing work TraceID: {TID} SpanID: {SID} payload=5")
    plain = r.to_plain()
    assert TID not in plain and SID not in plain
    assert "doing work" in plain and "payload=5" in plain


def test_otlp_variants_differ_on_trace():
    r = _rec("ts-x", TID, "INFO hello", level="INFO")
    assert r.to_otlp(with_trace=True)["traceId"] == TID
    assert "traceId" not in r.to_otlp(with_trace=False)


def test_format_window_conditions():
    recs = [_rec("ts-x", TID, "ERROR boom", "ERROR"), _rec("ts-y", TID, "INFO ok", "INFO")]
    plain = format_window(recs, "plain")
    structured = format_window(recs, "structured")
    no_trace = format_window(recs, "structured_no_trace")
    assert TID not in plain                     # scrubbed from bodies
    assert TID in structured                    # present as a field
    assert TID not in no_trace                  # field dropped
    assert "boom" in plain and "boom" in structured


def test_parse_log_field_train_ticket():
    raw = '{"log":"19:50:59.971 INFO  t.s.Impl#457 TraceID: x SpanID: y getTickets\\n","stream":"stdout","time":"t"}'
    msg, level, pf = _parse_log_field(raw)
    assert not pf and "getTickets" in msg
    # level for TT is parsed by the caller's regex; the field itself is empty here
    assert level == ""


def test_parse_log_field_online_boutique():
    raw = '{"log":"{\\"message\\":\\"charge failed\\",\\"severity\\":\\"error\\",\\"timestamp\\":\\"t\\"}\\n","stream":"stdout","time":"t"}'
    msg, level, pf = _parse_log_field(raw)
    assert not pf and msg == "charge failed" and level == "ERROR"


def test_label_traces_topology():
    w = Window(date="2023-01-30", minute="11_51", records=[
        _rec("ts-basic-service-aaaaaaaaaa-bbbbb", "trace_hit", "INFO a"),
        _rec("ts-other-service-cccccccccc-ddddd", "trace_miss", "INFO b"),
    ])
    eps = [{"inject_pod": "ts-basic-service-aaaaaaaaaa-bbbbb", "service": "ts-basic-service"}]
    labels = label_traces(w, eps)
    assert labels == {"trace_hit": True, "trace_miss": False}


def test_label_traces_empty_for_normal_window():
    w = Window(date="2023-01-30", minute="12_00", records=[_rec("ts-x", "t", "INFO a")])
    assert label_traces(w, []) == {}


def test_group_split_disjoint_and_deterministic():
    groups = [f"w{i}" for i in range(10)]
    a = group_split(groups, test_frac=0.3, seed=0)
    b = group_split(groups, test_frac=0.3, seed=0)
    assert a == b and 0 < len(a) < len(set(groups))
