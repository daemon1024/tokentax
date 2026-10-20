"""Unit tests for tokentax.rcalab (synthetic OTLP fixtures; no cluster, no capture)."""

from __future__ import annotations

import json
from collections import Counter

from tokentax import rcalab as R
from tokentax.nezha import LogRecord

T0 = 1_760_000_000_000_000_000


def rec(t_s, svc, trace="", level="INFO", msg="x"):
    return LogRecord(time_unix_nano=T0 + int(t_s * 1e9), node="", pod=svc, container=svc,
                     trace_id=trace, span_id="", message=msg, level=level, parse_fail=False)


def _span(trace, sid, parent, start_s, dur_ms, code=0, name="op"):
    return {"traceId": trace, "spanId": sid, "parentSpanId": parent, "name": name, "kind": 2,
            "startTimeUnixNano": str(T0 + int(start_s * 1e9)),
            "endTimeUnixNano": str(T0 + int(start_s * 1e9) + int(dur_ms * 1e6)),
            "status": {"code": code} if code else {}}


def _rs(service, spans):
    return {"resourceSpans": [{
        "resource": {"attributes": [{"key": "service.name", "value": {"stringValue": service}}]},
        "scopeSpans": [{"spans": spans}]}]}


def test_parse_spans_window_and_truncated_tail(tmp_path):
    p = tmp_path / "traces.jsonl"
    lines = [json.dumps(_rs("api-gateway", [_span("t1", "a", "", 0, 900, code=2)])),
             json.dumps(_rs("product-catalog", [_span("t1", "b", "a", 0.1, 800)])),
             json.dumps(_rs("api-gateway", [_span("t2", "c", "", 100, 10)]))]
    p.write_text("\n".join(lines) + "\n" + lines[0][:40])          # byte-cut last line
    sp = R.parse_spans(p)
    assert len(sp) == 3                                               # cut line skipped, not fatal
    assert sp[0].is_error and sp[0].service == "api-gateway" and abs(sp[0].duration_ms - 900) < 1e-6
    assert len(R.parse_spans(p, T0, T0 + int(50e9))) == 2            # windowed by start time


def test_argmax_reports_ties_and_strict_correctness():
    assert R.argmax_service(Counter()) == (None, False)
    c = Counter({"a": 3, "b": 3, "c": 1})
    top, tied = R.argmax_service(c)
    assert tied and top in ("a", "b")
    assert not R.argmax_correct(c, "a")                               # a tie is never "correct"
    assert R.argmax_correct(Counter({"a": 4, "b": 3}), "a")
    assert not R.argmax_correct(Counter({"a": 4, "b": 3}), "b")


def test_log_reach_counts_only_foreign_errors_that_share_a_trace_with_the_culprit():
    recs = [
        rec(0, "api-gateway", "t1", "ERROR"), rec(0.1, "product-catalog", "t1"),   # reach
        rec(1, "api-gateway", "t2", "ERROR"), rec(1.1, "cart", "t2"),              # foreign, no reach
        rec(2, "product-catalog", "t3", "ERROR"),                                  # culprit's own error
        rec(3, "api-gateway", "", "ERROR"),                                        # untraced error
    ]
    r = R.log_reach(recs, "product-catalog")
    assert r["error_records"] == 4 and r["error_records_with_trace"] == 3
    assert r["erroring_traces"] == 3 and r["foreign_erroring_traces"] == 2
    assert r["reach_traces"] == 1 and r["reach_frac_of_foreign"] == 0.5
    assert r["culprit_log_records"] == 2 and r["culprit_error_records"] == 1
    assert r["multi_service_erroring_traces"] == 2


def test_culprit_named_in_errors_uses_name_stem_and_skips_culprits_own_lines():
    recs = [rec(0, "product-catalog", "t", "ERROR", "recommendations rpc failed"),
            rec(1, "recommendation-service", "t", "ERROR", "recommendation boom"),
            rec(2, "product-catalog", "t", "INFO", "recommendation ok")]
    assert R.culprit_named_in_errors(recs, "recommendation-service") == 1


def test_span_reach_error_and_slow_views():
    def S(trace, sid, parent, svc, dur, code=0):
        return R.Span(trace, sid, parent, svc, "op", T0, T0 + int(dur * 1e6), code, 2)
    spans = [S("t1", "a", "", "api-gateway", 1200, 2), S("t1", "b", "a", "review-service", 1100),
             S("t2", "c", "", "api-gateway", 50, 2),
             S("t3", "d", "", "api-gateway", 1500), S("t3", "e", "d", "review-service", 1400)]
    r = R.span_reach(spans, "review-service", slow_ms=1000)
    assert r["error_traces"] == 2 and r["error_traces_reaching_culprit"] == 1
    assert r["slow_traces"] == 2 and r["slow_traces_reaching_culprit"] == 2
    assert r["culprit_spans"] == 2 and r["culprit_error_spans"] == 0
    assert R.root_duration_quantile(spans, 0.5) == 1200


def test_window_is_inclusive_and_sorted():
    recs = [rec(2, "a"), rec(0, "b"), rec(1, "c"), rec(5, "d")]
    w = R.window(recs, T0, T0 + int(2e9))
    assert [r.pod for r in w] == ["b", "c", "a"]
