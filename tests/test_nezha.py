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


def _leaky(msg):
    return LogRecord(1, "n", "p", "c", "T1", "S1", msg, "INFO", False)


def test_body_scrubs_both_emitter_formats():
    # Nezha / Train Ticket logback
    tt = _leaky("16:42:22.382 INFO  t.s.TravelServiceImpl#532 TraceID: "
                "ffc8ca7e4c8f06c75142c880d5595d96 SpanID: 439bc949a9eeb0cc [getRoute][ok]")
    assert "ffc8ca7e" not in tt.to_plain() and "439bc949" not in tt.to_plain()
    assert "[getRoute][ok]" in tt.to_plain()

    # OTel logging instrumentation — the form the original Nezha-only pattern missed
    otel = _leaky("Receive ListRecommendations otelSpanID=d530295384d63311 "
                  "otelTraceID=e1ae042c9f5f4e74ae682da79430a10c otelTraceSampled=true "
                  "otelServiceName=recommendationservice")
    p = otel.to_plain()
    assert "d530295384d63311" not in p and "e1ae042c9f5f4e74ae682da79430a10c" not in p
    assert "otelTraceSampled" not in p
    assert "Receive ListRecommendations" in p


def test_plain_arm_never_sees_service_identity():
    """`plain` has no service field by construction; otelServiceName in the body would restore it,
    which is exactly the variable plain -> structured_no_trace isolates."""
    r = _leaky("failed to retrieve ads otelServiceName=frontend")
    assert "frontend" not in r.to_plain()
    assert "failed to retrieve ads" in r.to_plain()
    # opt-out still exposes the raw leak, so the confound stays measurable
    assert "frontend" in r.body(scrub_ids=False, scrub_service=False)


def test_otlp_body_is_scrubbed_in_every_condition():
    r = _leaky("boom otelTraceID=e1ae042c9f5f4e74ae682da79430a10c otelServiceName=cart")
    for with_trace in (True, False):
        body = r.to_otlp(with_trace=with_trace)["body"]["stringValue"]
        assert "e1ae042c" not in body and "cart" not in body
    # the id still reaches the structured arm through the FIELD, which is the point
    assert r.to_otlp(with_trace=True)["traceId"] == "T1"
    assert "traceId" not in r.to_otlp(with_trace=False)
