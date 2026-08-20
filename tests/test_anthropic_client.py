"""Offline tests for the Anthropic wire-format adapter (no API key, no network)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from tokentax.methods.anthropic_client import (
    from_anthropic_response,
    to_anthropic_messages,
    to_anthropic_tools,
)
from tokentax.methods.repl import tool_schemas


def test_tool_schema_translation():
    ant = to_anthropic_tools(tool_schemas(condition="structured"))
    names = {t["name"] for t in ant}
    assert "errors_by_service" in names and "lines_for_trace" in names
    for t in ant:
        assert "input_schema" in t and "function" not in t
        assert t["input_schema"]["type"] == "object"


def test_system_is_hoisted_out_of_messages():
    system, msgs = to_anthropic_messages([
        {"role": "system", "content": "be terse"},
        {"role": "user", "content": "hi"},
    ])
    assert system == "be terse"
    assert [m["role"] for m in msgs] == ["user"]
    assert msgs[0]["content"][0]["text"] == "hi"


def test_tool_calls_and_results_pair_up():
    """RLMMethod emits one assistant message with N tool_calls then N `tool` messages in order."""
    _, msgs = to_anthropic_messages([
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "find it"},
        {"role": "assistant", "content": "", "tool_calls": [
            {"function": {"name": "overview", "arguments": {}}},
            {"function": {"name": "grep", "arguments": {"pattern": "err"}}},
        ]},
        {"role": "tool", "tool_name": "overview", "content": "12 lines"},
        {"role": "tool", "tool_name": "grep", "content": "3 matches"},
    ])
    assert [m["role"] for m in msgs] == ["user", "assistant", "user"]

    uses = [b for b in msgs[1]["content"] if b["type"] == "tool_use"]
    assert [u["name"] for u in uses] == ["overview", "grep"]
    assert uses[1]["input"] == {"pattern": "err"}

    # both results land in ONE user message, keyed to the ids they answer, in order
    results = msgs[2]["content"]
    assert [r["type"] for r in results] == ["tool_result", "tool_result"]
    assert [r["tool_use_id"] for r in results] == [u["id"] for u in uses]
    assert results[0]["content"] == "12 lines"


def test_stringified_arguments_are_parsed():
    _, msgs = to_anthropic_messages([
        {"role": "user", "content": "x"},
        {"role": "assistant", "content": "", "tool_calls": [
            {"function": {"name": "grep", "arguments": '{"pattern": "boom"}'}}]},
    ])
    use = [b for b in msgs[1]["content"] if b["type"] == "tool_use"][0]
    assert use["input"] == {"pattern": "boom"}


# --- response translation ---

@dataclass
class _Block:
    type: str
    text: str = ""
    name: str = ""
    id: str = ""
    input: dict = field(default_factory=dict)


@dataclass
class _Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_input_tokens: int = 0
    cache_creation_input_tokens: int = 0


@dataclass
class _Resp:
    content: list[Any]
    usage: _Usage
    stop_reason: str = "end_turn"
    model: str = "claude-sonnet-5"


def test_response_tokens_include_cache_and_tools_are_reshaped():
    r = from_anthropic_response(_Resp(
        content=[_Block("text", text="looking"),
                 _Block("tool_use", name="errors_by_service", id="tu_1_0", input={})],
        usage=_Usage(input_tokens=100, output_tokens=20,
                     cache_read_input_tokens=5, cache_creation_input_tokens=3),
    ))
    assert r.content == "looking"
    # cache reads/creations are billed input and must not be dropped from the accounting
    assert r.prompt_eval_count == 108
    assert r.eval_count == 20
    assert r.total_tokens == 128
    # re-emitted in the Ollama shape so LogREPL.call() dispatch is unchanged
    assert r.tool_calls == [{"function": {"name": "errors_by_service", "arguments": {}}}]


def test_response_without_tool_calls_has_none():
    r = from_anthropic_response(_Resp(
        content=[_Block("text", text='{"culprit_service": "cart"}')], usage=_Usage(1, 2)))
    assert r.tool_calls is None
    assert "cart" in r.content
