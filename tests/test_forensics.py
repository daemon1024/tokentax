"""Offline tests for the per-request forensics harness (no LLM, no network)."""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass

import pytest

from tokentax import forensics as F
from tokentax.nezha import LogRecord
from tokentax.otel_loader import LabeledWindow

T0 = 1_780_511_000_000_000_000   # ns, in the band the gate checks
MS = 1_000_000


def _rec(i, pod, trace, msg, level="INFO", dt_ms=None):
    t = T0 + (dt_ms if dt_ms is not None else i * 10) * MS
    return LogRecord(t, "n", pod, pod, trace, f"s{i}", msg, level, False)


def _records():
    # request A (trace aaaa...): edge -> catalog (ERROR) -> recs, interleaved with request B
    A = "a" * 32
    B = "b" * 32
    return [
        _rec(0, "frontend-proxy", A, "GET /api/products 500"),
        _rec(1, "frontend-proxy", B, "GET /api/cart 200"),
        _rec(2, "product-catalog", A, "lookup product OLJCESPC7Z"),
        _rec(3, "cart", B, "GetCart user=u1"),
        _rec(4, "recommendation", A, "Receive ListRecommendations"),
        _rec(5, "product-catalog", A, "failed to retrieve product", "ERROR"),
        _rec(6, "cart", "", "untraced housekeeping"),
        _rec(7, "cart", B, "cart ok"),
    ]


def _window(recs=None, fault="productCatalogFailure"):
    recs = recs or _records()
    return LabeledWindow("anomalous", fault, recs, recs[0].time_unix_nano, recs[-1].time_unix_nano)


# ---------------------------------------------------------------- time
def test_parse_timestamp_iso_and_numbers_agree():
    ns = F.parse_timestamp("2026-06-03T18:35:22.288Z")
    assert F.iso(ns) == "2026-06-03T18:35:22.288Z"
    assert F.parse_timestamp("2026-06-03T18:35:22.288+00:00") == ns
    assert F.parse_timestamp("2026-06-03T18:35:22.288") == ns          # naive means UTC
    assert F.parse_timestamp(ns / 1e9) == pytest.approx(ns, abs=1e4)   # seconds
    assert F.parse_timestamp(ns // 1_000_000) == ns                    # milliseconds
    assert F.parse_timestamp(str(ns)) == ns                            # nanoseconds as text


def test_parse_timestamp_rejects_garbage():
    for bad in ("", "yesterday", True):
        with pytest.raises(ValueError):
            F.parse_timestamp(bad)


# ---------------------------------------------------------------- tools
def test_schema_is_identical_in_every_arm_and_has_lines_near():
    s = F.forensics_tool_schemas()
    names = {t["function"]["name"] for t in s}
    assert {"overview", "grep", "peek", "errors_by_cluster", "errors_by_service",
            "extract_trace_ids", "lines_for_trace", "lines_near"} <= names
    # one function, no condition argument: byte-identical by construction
    assert json.dumps(F.forensics_tool_schemas()) == json.dumps(s)


def test_lines_near_window_cap_and_arm_formats():
    recs = _records()
    centre = F.iso(recs[3].time_unix_nano)
    for arm, cond in F.ARMS.items():
        repl = F.ForensicsREPL(recs, cond)
        out = repl.lines_near(centre, 0.02)       # +/-20 ms around index 3 -> indices 1..5
        assert out.startswith("5 lines within +/-0.02s")
        assert "[1]" in out and "[5]" in out and "[0]" not in out and "[6]" not in out
        if arm == "P":
            assert "svc=" not in out and "trace=" not in out
        if arm == "S":
            assert "svc=cart sev=INFO" in out and "trace=" not in out
        if arm == "T":
            assert "trace=aaaaaaaa" in out
    repl = F.ForensicsREPL(recs, "plain")
    capped = repl.lines_near(centre, 1.0, max_lines=3)
    assert capped.startswith("8 lines within") and "5 further lines in range not shown" in capped
    shown = re.findall(r"^\[(\d+)\]", capped, flags=re.M)
    assert shown == sorted(shown, key=int) and len(shown) == 3 and "3" in shown   # closest kept


def test_lines_near_errors_are_explicit():
    repl = F.ForensicsREPL(_records(), "plain")
    assert "bad timestamp" in repl.lines_near("nonsense", 1)
    assert "bad seconds" in repl.lines_near("2026-06-03T18:35:22Z", "x")
    assert "between 0 and" in repl.lines_near("2026-06-03T18:35:22Z", 9999)
    far = repl.lines_near("2020-01-01T00:00:00Z", 1)
    assert far.startswith("no lines within") and "window spans" in far
    assert "timestamp is required" in repl.call("lines_near", {})
    # model-style aliases are accepted
    ok = repl.call("lines_near", {"time": F.iso(_records()[0].time_unix_nano), "radius": 0.001})
    assert ok.startswith("1 lines within")


def test_unsorted_records_are_refused():
    recs = _records()
    recs[0], recs[1] = recs[1], recs[0]
    recs[0] = _rec(9, "x", "", "late", dt_ms=10_000)
    with pytest.raises(ValueError, match="time-sorted"):
        F.ForensicsREPL(recs, "plain")


def test_absent_fields_return_explicit_not_available():
    recs = _records()
    plain = F.ForensicsREPL(recs, "plain")
    assert "not available" in plain.errors_by_service()
    assert "not available" in plain.lines_for_trace("a" * 32)
    assert "not available" in plain.extract_trace_ids()
    s = F.ForensicsREPL(recs, "structured_no_trace")
    assert "ERROR counts by service" in s.errors_by_service()
    assert "not available" in s.lines_for_trace("a" * 32)
    t = F.ForensicsREPL(recs, "structured")
    assert t.lines_for_trace("a" * 32).count("\n") == 3          # 4 lines of request A


def test_trace_prefix_from_line_display_resolves_when_unique():
    t = F.ForensicsREPL(_records(), "structured")
    assert t.lines_for_trace("aaaaaaaa") == t.lines_for_trace("a" * 32)
    assert "no lines for trace" in t.lines_for_trace("cccccccc")
    assert "no lines for trace" in t.lines_for_trace("aaaa")          # too short to be a prefix
    assert "within trace aaaaaaaa" in t.errors_by_service(trace_id="aaaaaaaa")


def test_overview_has_no_arm_specific_steering_text():
    recs = _records()
    ov = {a: F.ForensicsREPL(recs, c).overview() for a, c in F.ARMS.items()}
    for text in ov.values():
        assert "use extract_trace_ids" not in text and "no service field" not in text
    assert "services:" not in ov["P"] and "services:" in ov["S"]
    assert "distinct trace_ids" in ov["T"] and "distinct trace_ids" not in ov["S"]
    # P is a strict prefix-subset of S, which is a strict subset of T: the arms differ by fields only
    assert set(ov["P"].splitlines()) < set(ov["S"].splitlines()) < set(ov["T"].splitlines())


def test_seed_rendering_differs_only_by_fields():
    r = _records()[5]
    p = F.render_seed(r, "plain")
    s = F.render_seed(r, "structured_no_trace")
    t = F.render_seed(r, "structured")
    assert p == "failed to retrieve product"
    assert s == "svc=product-catalog sev=ERROR failed to retrieve product"
    assert t == f"svc=product-catalog sev=ERROR trace={'a' * 32} failed to retrieve product"
    with pytest.raises(ValueError):
        F.render_seed(r, "nope")


def test_user_message_never_leaks_trace_id_outside_the_T_arm():
    recs = _records()
    for arm, cond in F.ARMS.items():
        repl = F.ForensicsREPL(recs, cond)
        msg = F.user_message(repl, recs[5], cond)
        assert ("a" * 32 in msg) == (arm == "T")
        assert "trace" not in msg.lower() or arm == "T"


# ---------------------------------------------------------------- cases
def test_eligible_cases_truth_and_root():
    w = _window()
    cs = F.eligible_cases([w])
    assert len(cs) == 1                       # B has no error; the untraced line is nobody's
    c = cs[0]
    assert c.seed_idx == 5 and c.trace_id == "a" * 32
    assert c.truth == (0, 2, 4)               # the other lines of A; the seed is NOT in its own truth
    assert c.root_service == "product-catalog" and c.n_services == 3
    assert c.key.endswith("#5")


def test_seed_is_the_last_error_and_root_the_first():
    recs = _records()
    recs[2] = _rec(2, "recommendation", "a" * 32, "upstream blew up first", "ERROR")
    c = F.eligible_cases([_window(recs)])[0]
    assert c.seed_idx == 5 and c.root_service == "recommendation"


def test_trivial_traces_are_not_eligible():
    recs = [_rec(0, "cart", "t1", "x", "ERROR"), _rec(1, "cart", "t1", "y"),
            _rec(2, "cart", "t1", "z"),                                   # 1 service
            _rec(3, "cart", "t2", "x", "ERROR"), _rec(4, "ad", "t2", "y")]  # only 1 other line
    assert F.eligible_cases([_window(recs)]) == []
    assert F.eligible_cases([_window(recs)], min_other_lines=1, min_services=2)[0].trace_id == "t2"


def _many_windows():
    ws = []
    for fi, fault in enumerate(("productCatalogFailure", "adFailure")):
        recs = []
        for k in range(12):
            tid = f"{fi}{k:02d}" + "0" * 29
            base = k * 100
            recs += [_rec(0, "frontend-proxy", tid, "GET", dt_ms=base),
                     _rec(0, "ad", tid, "ad err", "ERROR", dt_ms=base + 1),
                     _rec(0, "cart", tid, "cart", dt_ms=base + 2)]
        ws.append(_window(recs, fault))
    return ws


def test_sampling_is_deterministic_stratified_and_pilot_disjoint():
    el = F.eligible_cases(_many_windows())
    assert len(el) == 24
    a = F.sample_cases(el, {"productCatalogFailure": 5, "adFailure": 4}, {"adFailure": 2}, seed=7)
    b = F.sample_cases(el, {"productCatalogFailure": 5, "adFailure": 4}, {"adFailure": 2}, seed=7)
    assert a == b
    main, pilot = a
    assert len(main) == 9 and len(pilot) == 2
    assert {c.key for c in main}.isdisjoint({c.key for c in pilot})
    assert sum(c.fault == "adFailure" for c in main) == 4
    other, _ = F.sample_cases(el, {"productCatalogFailure": 5, "adFailure": 4}, {"adFailure": 2}, seed=8)
    assert {c.key for c in other} != {c.key for c in main}


# ---------------------------------------------------------------- parsing and scoring
def test_parse_final_variants():
    assert F.parse_final('{"line_indices": [3, 1, 3], "root_service": "cart"}') == ([1, 3], "cart")
    assert F.parse_final('Here: {"line_indices": ["4", "[7]", 2.0], "root_service": "ad"} done') \
        == ([2, 4, 7], "ad")
    assert F.parse_final('{"lines": [], "root": "x"}') == ([], "x")       # an empty list IS an answer
    assert F.parse_final('{"line_indices": [true, null, "a"]}') == ([], "")
    assert F.parse_final("I think it is cart") is None
    assert F.parse_final('{"culprit_service": "cart"}') is None
    assert F.parse_final("") is None and F.parse_final(None) is None


def _case(truth=(1, 2, 3, 4), seed=9):
    return F.Case(0, "w", "f", seed, "t", "cart", "cart", 2, tuple(truth))


def test_score_lines_drops_the_seed_from_both_sides():
    c = _case()
    perfect = F.score_lines([1, 2, 3, 4, 9], c)
    assert perfect["f1"] == 1.0 and perfect["n_pred"] == 4
    assert F.score_lines([], c)["f1"] == 0.0
    half = F.score_lines([1, 2, 7, 8], c)
    assert half["precision"] == 0.5 and half["recall"] == 0.5 and half["f1"] == 0.5
    # one miss, no extras on a 4-line truth: F1 = 6/7 = 0.857 -> correct at the 0.8 threshold
    assert F.score_lines([1, 2, 3], c)["f1"] >= F.CORRECT_F1
    assert F.score_lines([1, 2], c)["f1"] < F.CORRECT_F1
    # out-of-range indices are false positives, not errors
    assert F.score_lines([1, 2, 3, 4, 999], c)["precision"] == 0.8


def test_root_correct_never_credits_a_giveup():
    assert F.root_correct("product-catalog", "product-catalog")
    assert F.root_correct("Product_Catalog", "product-catalog")
    assert not F.root_correct("unknown", "unknown")
    assert not F.root_correct("", "cart")
    assert not F.root_correct("none", "none")
    assert not F.root_correct("cart-service", "cart")       # no substring credit


# ---------------------------------------------------------------- the loop, with a scripted client
@dataclass
class _Resp:
    content: str = ""
    tool_calls: list | None = None
    prompt_eval_count: int = 100
    eval_count: int = 10
    gpu_seconds: float = 0.0


class _Scripted:
    def __init__(self, script, delay=0.0):
        self.script, self.delay, self.calls = list(script), delay, 0
        self.seen_tools = []

    async def chat(self, messages, tools=None, think=None, **opts):
        self.calls += 1
        self.seen_tools.append(json.dumps(tools))
        if self.delay:
            await asyncio.sleep(self.delay)
        return self.script.pop(0)


def _tc(name, **args):
    return [{"function": {"name": name, "arguments": args}}]


def _run(client, cond="structured", **kw):
    recs = _records()
    case = F.eligible_cases([_window(recs)])[0]
    meter = F.Meter()
    out = asyncio.run(F.run_agent(client, recs, cond, case, meter,
                                  kw.get("max_rounds", 5), kw.get("ceiling", 10_000), 4096))
    return out, meter, case


def test_agent_loop_answers_and_counts_every_round():
    client = _Scripted([_Resp(tool_calls=_tc("lines_for_trace", trace_id="aaaaaaaa")),
                        _Resp(content='{"line_indices": [0, 2, 4], "root_service": "product-catalog"}')])
    out, meter, case = _run(client)
    assert out.indices == [0, 2, 4] and not out.aborted
    assert meter.rounds == 2 and meter.in_tok == 200 and meter.out_tok == 20
    assert meter.tools == ["lines_for_trace"] and meter.not_available == 0
    assert F.score_lines(out.indices, case)["f1"] == 1.0


def test_unavailable_tool_calls_are_counted_in_the_plain_arm():
    client = _Scripted([_Resp(tool_calls=_tc("lines_for_trace", trace_id="x")
                              + _tc("errors_by_service")),
                        _Resp(content='{"line_indices": [], "root_service": "cart"}')])
    out, meter, _ = _run(client, cond="plain")
    assert meter.not_available == 2 and out.indices == []


def test_every_arm_is_sent_the_same_tool_schema():
    seen = set()
    for cond in F.ARMS.values():
        client = _Scripted([_Resp(content='{"line_indices": [], "root_service": "cart"}')])
        _run(client, cond=cond)
        seen.add(client.seen_tools[0])
    assert len(seen) == 1


def test_nudge_then_ceiling_and_round_cap_are_failures_with_tokens_kept():
    client = _Scripted([_Resp(content="hmm"), _Resp(content="still thinking"),
                        _Resp(content="no json"), ])
    out, meter, _ = _run(client, max_rounds=3)
    assert out.indices is None and out.aborted and out.abort_reason == "max_rounds"
    assert meter.total == 330                       # tokens kept, not zeroed

    client = _Scripted([_Resp(tool_calls=_tc("overview"), prompt_eval_count=9000)] * 3)
    out, meter, _ = _run(client, ceiling=5000)
    assert out.abort_reason == "token_ceiling" and meter.total == 9010


def test_wall_clock_timeout_keeps_the_tokens_spent_so_far():
    """The reason `Meter` exists: wait_for cancels the loop, and the old design lost the counters."""
    client = _Scripted([_Resp(tool_calls=_tc("overview")),
                        _Resp(content="never delivered")], delay=0.3)
    recs = _records()
    case = F.eligible_cases([_window(recs)])[0]
    meter = F.Meter()

    async def go():
        await asyncio.wait_for(F.run_agent(client, recs, "plain", case, meter, 5, 10_000, 4096),
                               timeout=0.45)

    with pytest.raises(TimeoutError):
        asyncio.run(go())
    assert meter.rounds == 1 and meter.total == 110       # round 1 completed; round 2 was in flight


def test_plain_lines_carry_no_identity_after_scrubbing():
    """CLAUDE.md hard rule: a hex-token scan over rendered plain lines must return zero."""
    leaky = _rec(0, "cart", "t" * 32, "GetCart otelTraceID=" + "ab" * 16 + " otelSpanID=" + "cd" * 8
                 + " otelServiceName=cart user=u1")
    repl = F.ForensicsREPL([leaky], "plain")
    assert not re.search(r"[0-9a-fA-F]{16,}", repl.lines[0])
    assert "otel" not in repl.lines[0].replace("otelcol", "")
    assert repl.lines[0] == "[0] GetCart user=u1"
