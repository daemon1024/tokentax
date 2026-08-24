"""Unit tests for the RLM REPL navigation helpers (offline, no LLM)."""

from __future__ import annotations

from tokentax.methods.repl import LogREPL, tool_schemas
from tokentax.nezha import LogRecord


def _rec(pod, trace, msg, level="INFO"):
    return LogRecord(1, "n", pod, "server", trace, "s", msg, level, False)


def _records():
    return [
        _rec("ts-travel-service-aa-bb", "T1", "starting getTickets"),
        _rec("ts-basic-service-cc-dd", "T1", "NullPointerException in calc", "ERROR"),
        _rec("ts-order-service-ee-ff", "T2", "order ok"),
        _rec("ts-basic-service-cc-dd", "T2", "minor warn", "WARN"),
    ]


def test_overview_and_grep():
    repl = LogREPL(_records(), trace_aware=True)
    ov = repl.overview()
    assert "4 log lines" in ov and "ts-travel-service" in ov
    g = repl.grep("exception")
    assert "NullPointerException" in g and "1 matches" in g


def test_trace_aware_navigation():
    repl = LogREPL(_records(), trace_aware=True)
    tids = repl.extract_trace_ids(only_with_errors=True)
    assert "T1" in tids and "errors=1" in tids
    body = repl.lines_for_trace("T1")
    assert "NullPointerException" in body and "getTickets" in body


def test_trace_blind_hides_trace_tools():
    repl = LogREPL(_records(), trace_aware=False)
    assert "not available" in repl.extract_trace_ids()
    assert "not available" in repl.lines_for_trace("T1")
    names = {t["function"]["name"] for t in tool_schemas(False)}
    assert "extract_trace_ids" not in names and "grep" in names
    assert "extract_trace_ids" in {t["function"]["name"] for t in tool_schemas(True)}


def test_dispatch():
    repl = LogREPL(_records(), trace_aware=True)
    assert "matches" in repl.call("grep", {"pattern": "ok"})
    assert "unknown tool" in repl.call("nope", {})


def test_digests_scope_to_a_trace():
    repl = LogREPL(_records(), trace_aware=True)
    assert "ts-basic-service-cc-dd=1" in repl.errors_by_service()
    scoped = repl.errors_by_service(trace_id="T1")
    assert "within trace T1" in scoped and "ts-basic-service-cc-dd=1" in scoped
    # T2's only non-INFO line is a WARN, so a scoped digest must report zero errors,
    # never silently fall back to the whole window.
    assert "no errors" in repl.errors_by_service(trace_id="T2")
    assert "no errors" in repl.errors_by_cluster(trace_id="T2")
    assert "NullPointerException" in repl.errors_by_cluster(trace_id="T1")


def test_scope_errors_are_explicit_not_silent():
    repl = LogREPL(_records(), trace_aware=True)
    assert "no lines for trace" in repl.errors_by_service(trace_id="NOPE")
    assert "no lines for trace" in repl.errors_by_cluster(trace_id="NOPE")
    blind = LogREPL(_records(), condition="structured_no_trace")
    assert "not available in this condition" in blind.errors_by_service(trace_id="T1")
    # ... but an unscoped call in that arm still works.
    assert "ts-basic-service-cc-dd=1" in blind.errors_by_service()


def test_unscoped_cluster_cache_survives_a_scoped_call():
    repl = LogREPL(_records(), trace_aware=True)
    full = repl.errors_by_cluster()
    repl.errors_by_cluster(trace_id="T1")
    assert repl.errors_by_cluster() == full


def test_scope_param_declared_only_where_trace_ids_exist():
    def props(schemas, name):
        return next(t["function"]["parameters"]["properties"]
                    for t in schemas if t["function"]["name"] == name)
    assert "trace_id" in props(tool_schemas(condition="structured"), "errors_by_service")
    assert "trace_id" in props(tool_schemas(condition="structured"), "errors_by_cluster")
    assert "trace_id" not in props(tool_schemas(condition="structured_no_trace"), "errors_by_service")
    assert "trace_id" not in props(tool_schemas(condition="plain"), "errors_by_cluster")
    # matched_schemas forces every arm onto the identical (structured) tool set
    assert (tool_schemas(condition="plain", matched_schemas=True)
            == tool_schemas(condition="structured", matched_schemas=True))


def test_dispatch_passes_the_scope_through():
    repl = LogREPL(_records(), trace_aware=True)
    assert "within trace T1" in repl.call("errors_by_service", {"trace_id": "T1"})
    assert "within trace T1" in repl.call("errors_by_cluster", {"traceId": "T1"})
    assert "within trace" not in repl.call("errors_by_service", {})
