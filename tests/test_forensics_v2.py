"""Offline tests for the V2 forensics harness: the T-index arm and the usage-limit guard (no network)."""

from __future__ import annotations

import asyncio
import copy
import json
from dataclasses import dataclass

import httpx
import pytest

from tokentax import forensics as F
from tokentax import forensics_v2 as V
from tokentax.nezha import LogRecord
from tokentax.otel_loader import LabeledWindow

T0 = 1_780_511_000_000_000_000
MS = 1_000_000
A, B = "a" * 32, "b" * 32


def _rec(i, pod, trace, msg, level="INFO"):
    return LogRecord(T0 + i * 10 * MS, "n", pod, pod, trace, f"s{i}", msg, level, False)


def _records():
    return [
        _rec(0, "frontend-proxy", A, "GET /api/products 500"),
        _rec(1, "frontend-proxy", B, "GET /api/cart 200"),
        _rec(2, "product-catalog", A, "lookup product OLJCESPC7Z"),
        _rec(3, "cart", B, "GetCart user=u1"),
        _rec(4, "recommendation", A, "Receive ListRecommendations"),
        _rec(5, "product-catalog", A, "failed to retrieve product", "ERROR"),
        _rec(6, "cart", "", "untraced housekeeping"),
    ]


def _case(recs):
    w = LabeledWindow("anomalous", "productCatalogFailure", recs, recs[0].time_unix_nano, recs[-1].time_unix_nano)
    return F.eligible_cases([w])[0]


# ---------------------------------------------------------------- the TI arm's data surface
def test_ti_lines_are_byte_identical_to_S_and_carry_no_trace_text():
    recs = _records()
    ti, s = V.make_repl(recs, V.TRACE_INDEX), F.ForensicsREPL(recs, "structured_no_trace")
    assert ti.lines == s.lines
    assert not any(A[:8] in ln or "trace=" in ln for ln in ti.lines)
    assert "no matches" in ti.grep(A[:8])                       # the id cannot be grepped out of the lines


def test_ti_keeps_the_trace_index_live():
    recs = _records()
    ti, t = V.make_repl(recs, V.TRACE_INDEX), F.ForensicsREPL(recs, "structured")
    got = ti.lines_for_trace(A[:8])                            # unique 8-char prefix resolves, as in T
    assert [ln.split("]")[0] for ln in got.splitlines()] == ["[0", "[2", "[4", "[5"]
    assert "trace=" not in got and "trace=" in t.lines_for_trace(A[:8])
    assert ti.extract_trace_ids().splitlines()[1:] == t.extract_trace_ids().splitlines()[1:]
    assert ti.errors_by_service(A) == t.errors_by_service(A)
    assert "not available" not in ti.call("lines_for_trace", {"trace_id": A})
    assert ti.overview() == t.overview()                       # same data-only overview as T


def test_ti_seed_shows_the_full_trace_id_exactly_as_T():
    r = _records()[5]
    assert V.render_seed(r, V.TRACE_INDEX) == F.render_seed(r, "structured")
    assert A in V.render_seed(r, V.TRACE_INDEX)
    for cond in ("plain", "structured_no_trace", "structured"):
        assert V.render_seed(r, cond) == F.render_seed(r, cond)


def test_user_message_matches_v1_for_the_v1_arms():
    recs = _records()
    for cond in ("plain", "structured_no_trace", "structured"):
        repl = F.ForensicsREPL(recs, cond)
        assert V.user_message(repl, recs[5], cond) == F.user_message(repl, recs[5], cond)


def test_arms_map_and_order():
    assert V.ARM_ORDER == ("P", "S", "T", "TI")
    assert {k: V.ARMS_V2[k] for k in F.ARMS} == F.ARMS        # V1 arms unchanged


# ---------------------------------------------------------------- the loop is V1's loop
@dataclass
class _Resp:
    content: str = ""
    tool_calls: list | None = None
    prompt_eval_count: int = 100
    eval_count: int = 10
    gpu_seconds: float = 0.0


class _Recorder:
    """Scripted client that records every message list and tool schema it is sent."""

    def __init__(self, script):
        self.script, self.sent = list(script), []

    async def chat(self, messages, tools=None, think=None, **opts):
        self.sent.append((copy.deepcopy(messages), json.dumps(tools), think, opts.get("num_ctx")))
        return self.script.pop(0)


def _script():
    tc = lambda name, **a: [{"function": {"name": name, "arguments": a}}]
    return [_Resp(tool_calls=tc("grep", pattern="product")),
            _Resp(tool_calls=tc("lines_for_trace", trace_id=A[:8])),
            _Resp(content="thinking"),                                    # no JSON -> nudge
            _Resp(content='{"line_indices": [0, 2, 4], "root_service": "product-catalog"}')]


@pytest.mark.parametrize("cond", ["plain", "structured_no_trace", "structured"])
def test_v2_loop_sends_exactly_what_the_v1_loop_sends(cond):
    recs = _records()
    case = _case(recs)
    c1, c2 = _Recorder(_script()), _Recorder(_script())
    m1, m2 = F.Meter(), F.Meter()
    o1 = asyncio.run(F.run_agent(c1, recs, cond, case, m1, 6, 10_000, 4096))
    o2 = asyncio.run(V.run_agent_v2(c2, recs, cond, case, m2, 6, 10_000, 4096))
    assert c1.sent == c2.sent
    assert o1 == o2 and m1.total == m2.total and m1.tools == m2.tools and m1.trace == m2.trace


def test_run_cell_agent_routes_ti_through_v2_and_scores():
    recs = _records()
    case = _case(recs)
    c = _Recorder(_script())
    meter = F.Meter()
    out = asyncio.run(V.run_cell_agent(c, recs, V.TRACE_INDEX, case, meter, 6, 10_000, 4096))
    assert out.indices == [0, 2, 4] and meter.rounds == 4
    first_user = c.sent[0][0][1]["content"]
    assert A in first_user and "trace=" + A in first_user            # seed carries the full id
    assert json.loads(c.sent[0][1]) == F.forensics_tool_schemas()    # same schema as every arm
    lft = c.sent[2][0][-1]["content"]                                 # tool result of lines_for_trace
    assert "[2] svc=product-catalog" in lft and "trace=" not in lft


# ---------------------------------------------------------------- the usage-limit guard
def _patch_transport(monkeypatch, handler):
    real = httpx.AsyncClient
    calls = {"n": 0}

    def counting(request):
        calls["n"] += 1
        return handler(request)

    monkeypatch.setattr(V.httpx, "AsyncClient",
                        lambda **kw: real(transport=httpx.MockTransport(counting), **kw))

    async def no_sleep(_s):
        return None
    monkeypatch.setattr(V.asyncio, "sleep", no_sleep)
    return calls


def test_usage_limit_429_stops_at_once(monkeypatch):
    calls = _patch_transport(monkeypatch, lambda r: httpx.Response(
        429, text='{"error":"you (x) have reached your weekly usage limit, upgrade for higher limits"}'))
    c = V.GuardedOllamaClient(host="https://ollama.example/api", model="m", max_retries=3)
    with pytest.raises(V.UsageLimitReached):
        asyncio.run(c.chat([{"role": "user", "content": "hi"}]))
    assert calls["n"] == 1


def test_rate_limit_429_is_retried_then_reported_as_transport(monkeypatch):
    calls = _patch_transport(monkeypatch, lambda r: httpx.Response(429, text="too many requests"))
    c = V.GuardedOllamaClient(host="https://ollama.example/api", model="m", max_retries=3)
    with pytest.raises(RuntimeError) as e:
        asyncio.run(c.chat([{"role": "user", "content": "hi"}]))
    assert calls["n"] == 3 and "429" in str(e.value) and not isinstance(e.value, V.UsageLimitReached)


def test_guarded_client_returns_the_same_response_shape(monkeypatch):
    body = {"message": {"content": "", "tool_calls": [{"function": {"name": "overview", "arguments": {}}}]},
            "prompt_eval_count": 50, "eval_count": 5}
    _patch_transport(monkeypatch, lambda r: httpx.Response(200, json=body))
    c = V.GuardedOllamaClient(host="https://ollama.example/api", model="m")
    resp = asyncio.run(c.chat([{"role": "user", "content": "hi"}], tools=F.forensics_tool_schemas()))
    assert resp.tool_calls[0]["function"]["name"] == "overview" and resp.total_tokens == 55


def test_is_usage_limit():
    assert V.is_usage_limit(429, "Weekly USAGE LIMIT reached")
    assert not V.is_usage_limit(429, "rate limited")
    assert not V.is_usage_limit(402, "usage limit")
