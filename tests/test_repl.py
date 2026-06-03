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
