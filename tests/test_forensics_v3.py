"""Offline tests for the V3 arms Tt (trace printed, no index) and Th (T + one hint sentence). No network."""

from __future__ import annotations

import asyncio
import json

import pytest
from test_forensics_v2 import A, _case, _Recorder, _records, _script

from tokentax import forensics as F
from tokentax import forensics_v3 as V3


# ---------------------------------------------------------------- Tt's data surface
def test_tt_lines_are_byte_identical_to_T():
    recs = _records()
    assert V3.make_repl(recs, V3.TRACE_TEXT).lines == F.ForensicsREPL(recs, "structured").lines


def test_tt_has_no_trace_index_and_S_overview():
    recs = _records()
    tt, s = V3.make_repl(recs, V3.TRACE_TEXT), F.ForensicsREPL(recs, "structured_no_trace")
    assert tt.overview() == s.overview()
    for name, args in [("lines_for_trace", {"trace_id": A}), ("extract_trace_ids", {}),
                       ("errors_by_service", {"trace_id": A}), ("errors_by_cluster", {"trace_id": A})]:
        assert tt.call(name, args).startswith(F.NOT_AVAILABLE), name
        assert tt.call(name, args) == s.call(name, args)
    assert tt.call("errors_by_service", {}) == s.call("errors_by_service", {})


def test_tt_grep_finds_the_printed_id():
    tt = V3.make_repl(_records(), V3.TRACE_TEXT)
    got = tt.grep("trace=" + A[:8])
    assert all(f"[{i}]" in got for i in (0, 2, 4, 5)) and "[1]" not in got


def test_seeds_and_system():
    r = _records()[5]
    for cond in (V3.TRACE_TEXT, V3.HINTED):
        assert V3.render_seed(r, cond) == F.render_seed(r, "structured")
    for cond in ("plain", "structured_no_trace", "structured"):
        assert V3.render_seed(r, cond) == F.render_seed(r, cond)
    recs = _records()
    base = F.SYSTEM.format(roster=F.roster_text(recs))
    for cond in ("plain", "structured_no_trace", "structured", V3.TRACE_TEXT):
        assert V3.system_text(recs, cond) == base
    hinted = V3.system_text(recs, V3.HINTED)
    assert hinted.replace(V3.HINT, "") == base and hinted.count(V3.HINT) == 1


def test_th_repl_is_T():
    recs = _records()
    th, t = V3.make_repl(recs, V3.HINTED), F.ForensicsREPL(recs, "structured")
    assert th.lines == t.lines and th.overview() == t.overview()
    assert th.lines_for_trace(A[:8]) == t.lines_for_trace(A[:8])


def test_arms():
    assert V3.ARM_ORDER == ("P", "S", "T", "Tt", "Th")
    assert {k: V3.ARMS_V3[k] for k in F.ARMS} == F.ARMS


# ---------------------------------------------------------------- the loop is V1's loop
@pytest.mark.parametrize("cond", ["plain", "structured_no_trace", "structured"])
def test_v3_loop_sends_exactly_what_the_v1_loop_sends(cond):
    recs = _records()
    case = _case(recs)
    c1, c3 = _Recorder(_script()), _Recorder(_script())
    m1, m3 = F.Meter(), F.Meter()
    o1 = asyncio.run(F.run_agent(c1, recs, cond, case, m1, 6, 10_000, 4096))
    o3 = asyncio.run(V3.run_agent_v3(c3, recs, cond, case, m3, 6, 10_000, 4096))
    assert c1.sent == c3.sent
    assert o1 == o3 and m1.total == m3.total and m1.tools == m3.tools and m1.trace == m3.trace


def test_th_differs_from_T_only_in_the_system_sentence():
    recs = _records()
    case = _case(recs)
    ct, ch = _Recorder(_script()), _Recorder(_script())
    asyncio.run(F.run_agent(ct, recs, "structured", case, F.Meter(), 6, 10_000, 4096))
    asyncio.run(V3.run_agent_v3(ch, recs, V3.HINTED, case, F.Meter(), 6, 10_000, 4096))
    assert len(ct.sent) == len(ch.sent)
    for (mt, tt, *_), (mh, th, *_) in zip(ct.sent, ch.sent, strict=True):
        assert tt == th == json.dumps(F.forensics_tool_schemas())
        assert mh[0]["content"].replace(V3.HINT, "") == mt[0]["content"]
        assert mh[1:] == mt[1:]


def test_tt_loop_lookup_replies_not_available():
    recs = _records()
    case = _case(recs)
    c = _Recorder(_script())
    m = F.Meter()
    asyncio.run(V3.run_agent_v3(c, recs, V3.TRACE_TEXT, case, m, 6, 10_000, 4096))
    assert "trace=" + A in c.sent[0][0][1]["content"]                 # seed carries the full id, as T
    assert m.not_available == 1                                       # the lines_for_trace call
    assert c.sent[2][0][-1]["content"].startswith(F.NOT_AVAILABLE)


# ---------------------------------------------------------------- the secondary metric
def test_used_trace_id():
    ev = [{"round": 1, "tool": "grep", "args": {"pattern": "trace=" + A[:8]}},
          {"round": 2, "tool": "lines_for_trace", "args": {"trace_id": A}}]
    assert V3.used_trace_id(ev, A) == {"grep_trace": True, "lookup_trace": True}
    assert V3.used_trace_id([{"tool": "grep", "args": {"pattern": "failed"}}], A) == \
        {"grep_trace": False, "lookup_trace": False}
    assert V3.used_trace_id([{"tool": "grep", "args": {"pattern": "b" * 8}}], A)["grep_trace"] is False
    assert V3.used_trace_id([{"tool": "grep", "args": {"pattern": A[3:11].upper()}}], A)["grep_trace"]
    assert V3.used_trace_id([{"final": "{}"}], A) == {"grep_trace": False, "lookup_trace": False}
