"""Offline tests for the rca-lab dataset loader (synthetic compressed captures, temporary manifest)."""

from __future__ import annotations

import gzip
import json

import pytest
from compression import zstd

from tokentax import forensics as F
from tokentax import rcalab_dataset as D
from tokentax.otel_loader import parse_otlp_jsonl

T0 = 1_792_480_000_000_000_000
S = 1_000_000_000


def _log(t_s, svc, trace="", sev=9, body="x"):
    return {"resourceLogs": [{
        "resource": {"attributes": [{"key": "service.name", "value": {"stringValue": svc}}]},
        "scopeLogs": [{"logRecords": [{"timeUnixNano": str(T0 + int(t_s * S)), "severityNumber": sev,
                                       "body": {"stringValue": body}, "traceId": trace,
                                       "spanId": "0011223344556677"}]}]}]}


def _span(t_s, svc, trace, sid, parent="", dur_ms=10, code=0):
    st = T0 + int(t_s * S)
    return {"resourceSpans": [{
        "resource": {"attributes": [{"key": "service.name", "value": {"stringValue": svc}}]},
        "scopeSpans": [{"spans": [{"traceId": trace, "spanId": sid, "parentSpanId": parent, "name": "op",
                                   "startTimeUnixNano": str(st), "endTimeUnixNano": str(st + dur_ms * 1_000_000),
                                   "status": {"code": code} if code else {}}]}]}]}


LOGS = [_log(10, "fulfillment-service", "t0", 17, "ambient 404"),            # baseline: ambient noise
        _log(70, "order-service", "t1", 17, "Lock wait timeout exceeded"),   # fault
        _log(71, "cart-service", "t1", 9, "checkout"),
        _log(72, "order-service", "", 13, "pool warning"),
        _log(130, "load-generator", "", 9, "Stats")]                         # recovery
SPANS = [_span(10, "api-gateway", "t0", "a"), _span(70, "api-gateway", "t1", "b", dur_ms=900, code=2),
         _span(70.1, "order-service", "t1", "c", parent="b", dur_ms=800, code=2),
         _span(131, "api-gateway", "t2", "d")]


def _write(path, docs, how):
    text = "\n".join(json.dumps(d) for d in docs) + "\n"
    if how == "zst":
        with zstd.open(path, "wt", encoding="utf-8") as f:
            f.write(text)
    elif how == "gz":
        with gzip.open(path, "wt", encoding="utf-8") as f:
            f.write(text)
    else:
        path.write_text(text)


def _capture(tmp_path, name="sc-04", scenario="sc-04", how="zst", verified=True):
    d = tmp_path / "data/rcalab" / name
    d.mkdir(parents=True)
    ext = {"zst": ".jsonl.zst", "gz": ".jsonl.gz", "plain": ".jsonl"}[how]
    _write(d / f"logs{ext}", LOGS, how)
    _write(d / f"traces{ext}", SPANS, how)
    entry = {"name": name, "scenario": scenario, "path": f"data/rcalab/{name}", "status": "ok",
             "effect_verified": verified,
             "windows": {"baseline": [T0, T0 + 60 * S], "fault": [T0 + 60 * S, T0 + 120 * S],
                         "recovery": [T0 + 120 * S, T0 + 180 * S]}}
    return {"dataset": "rcalab", "captures": [entry]}


@pytest.mark.parametrize("how", ["zst", "gz", "plain"])
def test_windows_and_truth_from_every_compression(tmp_path, how):
    m = _capture(tmp_path, how=how)
    [cap] = D.captures(m, data_root=tmp_path)
    f, b, r = cap.window("fault"), cap.window("baseline"), cap.window("recovery")
    assert [x.pod for x in f.records] == ["order-service", "cart-service", "order-service"]
    assert len(b.records) == 1 and len(r.records) == 1
    assert f.truth["culprit_service"] == "order-service" and f.fault == "sc-04" and f.label == "anomalous"
    assert b.truth["culprit_service"] is None and b.fault is None and b.label == "normal"
    assert [s.service for s in cap.spans("fault")] == ["api-gateway", "order-service"]


def test_records_are_exactly_what_otel_loader_parses(tmp_path):
    m = _capture(tmp_path, how="zst")
    [cap] = D.captures(m, data_root=tmp_path)
    plain = tmp_path / "plain.jsonl"
    _write(plain, LOGS, "plain")
    assert cap.records() == sorted(parse_otlp_jsonl(plain), key=lambda r: r.time_unix_nano)


def test_unverified_captures_are_skipped_unless_asked(tmp_path):
    m = _capture(tmp_path, verified=False)
    assert D.captures(m, data_root=tmp_path) == []
    assert len(D.captures(m, data_root=tmp_path, include_unverified=True)) == 1


def test_skipped_and_missing_entries_are_not_returned(tmp_path):
    m = _capture(tmp_path)
    m["captures"].append({"name": "sc-99", "scenario": "sc-99", "path": "data/rcalab/sc-99",
                          "status": "skipped", "reason": "x"})
    m["captures"].append({"name": "gone", "scenario": "sc-11", "path": "data/rcalab/gone", "status": "ok",
                          "effect_verified": True, "windows": {}})
    assert [c.name for c in D.captures(m, data_root=tmp_path)] == ["sc-04"]


def test_unknown_bounds_raise_rather_than_guess(tmp_path):
    m = _capture(tmp_path)
    m["captures"][0]["windows"]["recovery"] = None
    [cap] = D.captures(m, data_root=tmp_path)
    assert cap.bounds("recovery") is None
    with pytest.raises(ValueError):
        cap.window("recovery")


def test_subwindows_and_forensics_compatibility(tmp_path):
    m = _capture(tmp_path)
    [cap] = D.captures(m, data_root=tmp_path)
    subs = D.subwindows(cap.window("fault"), 30)
    assert len(subs) == 2 and len(subs[0].records) == 3 and len(subs[1].records) == 0
    assert all(s.truth["culprit_service"] == "order-service" for s in subs)
    cases = F.eligible_cases([cap.window("fault")], min_other_lines=1, min_services=2)
    assert len(cases) == 1 and cases[0].seed_service == "order-service"


def test_counts_per_window(tmp_path):
    m = _capture(tmp_path)
    [cap] = D.captures(m, data_root=tmp_path)
    b = {k: cap.bounds(k) for k in D.WINDOW_KINDS}
    lc = D.count_logs(cap.logs_path(), b)
    sc = D.count_spans(cap.traces_path(), b)
    assert lc["all"]["log_records"] == 5 and lc["fault"]["error_records"] == 1
    assert lc["fault"]["records_with_trace_id"] == 2 and lc["baseline"]["errors_by_service"] == {
        "fulfillment-service": 1}
    assert sc["all"]["spans"] == 4 and sc["all"]["traces"] == 3
    assert sc["fault"]["error_bearing_traces"] == 1 and sc["fault"]["root_span_ms_p99"] == 900.0
    assert sc["recovery"]["spans"] == 1


def test_ground_truth_table_covers_every_deployed_scenario():
    deployed = {f"sc-{n:02d}" for n in [*range(1, 16), *range(19, 29)]}
    assert deployed <= set(D.GROUND_TRUTH)
    for k, v in D.GROUND_TRUTH.items():
        assert set(v) == {"culprit_service", "culprit_component", "fault_class", "culprit_is_app_service",
                          "affected_services", "topology_caveat"}, k
    assert D.truth_for("sc-99", "fault")["culprit_service"] == "unknown"     # never guessed
