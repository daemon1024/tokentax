"""Anthropic client presenting the SAME interface as `OllamaClient`, so `RLMMethod` runs unchanged.

Why an adapter rather than the `claude -p` path in `claude_cli.py`: to put Claude in the corrected
3-arm matrix it must navigate with **the same LogREPL tools** as every other model. The subscription
CLI brings its own harness (~30k tokens of system prompt + its native Grep/Read/Bash), which is both a
large constant token offset and a *different tool surface* — exactly the matched-capability violation
that invalidated the 2026-06 runs (see WITHDRAWAL.md). Cells produced through that path are not
comparable to the Ollama cells and must not share a table with them.

Wire-format differences this adapter absorbs:
  * system prompt is a top-level `system` param, not a message
  * tools are `{name, description, input_schema}`, not `{type, function:{...}}`
  * tool results are `tool_result` blocks in a USER message, keyed by the `tool_use.id` they answer
  * consecutive Ollama `role: "tool"` messages collapse into one user message

Model notes (Claude Sonnet 5, `claude-sonnet-5`):
  * `temperature`/`top_p`/`top_k` are REMOVED — sending any returns 400. The project's
    `temperature=0` determinism convention therefore cannot be applied here; that is a real and
    unavoidable difference from the Ollama arms, and it is recorded in the results, not hidden.
  * `budget_tokens` is removed; thinking is `{"type": "adaptive"}` or `{"type": "disabled"}`.
    Default here is DISABLED, to match the Ollama runs' `think=False`.
  * 1M context, so `num_ctx` is accepted and ignored.
"""

from __future__ import annotations

import asyncio
import os
from typing import Any

from tokentax.methods.ollama_client import LLMResponse

DEFAULT_MODEL = "claude-sonnet-5"


def to_anthropic_tools(tools: list[dict] | None) -> list[dict]:
    """Ollama `{type, function:{name, description, parameters}}` -> Anthropic `{name, ..., input_schema}`."""
    out = []
    for t in tools or []:
        fn = t.get("function", t)
        out.append({
            "name": fn["name"],
            "description": fn.get("description", ""),
            "input_schema": fn.get("parameters") or {"type": "object", "properties": {}},
        })
    return out


def to_anthropic_messages(messages: list[dict]) -> tuple[str, list[dict]]:
    """Translate the Ollama-shaped history into (system, anthropic_messages).

    Tool-call ids are synthesised positionally (`tu_<msg>_<n>`) and the matching `tool_result` blocks
    reuse them in order, which is exactly how `RLMMethod` emits them: one assistant message carrying
    N tool_calls, immediately followed by N `role: "tool"` messages in the same order.
    """
    system_parts: list[str] = []
    out: list[dict] = []
    pending: list[str] = []          # tool_use ids awaiting results
    results: list[dict] = []         # tool_result blocks being accumulated

    def flush_results():
        nonlocal results
        if results:
            out.append({"role": "user", "content": results})
            results = []

    for i, m in enumerate(messages):
        role = m.get("role")
        if role == "system":
            flush_results()
            system_parts.append(m.get("content") or "")
            continue

        if role == "tool":
            tid = pending.pop(0) if pending else f"tu_{i}_orphan"
            results.append({
                "type": "tool_result",
                "tool_use_id": tid,
                "content": str(m.get("content") or ""),
            })
            continue

        flush_results()

        if role == "assistant":
            blocks: list[dict] = []
            if m.get("content"):
                blocks.append({"type": "text", "text": m["content"]})
            pending = []
            for j, tc in enumerate(m.get("tool_calls") or []):
                fn = tc.get("function", {})
                tid = f"tu_{i}_{j}"
                pending.append(tid)
                args = fn.get("arguments") or {}
                if isinstance(args, str):
                    import json as _json
                    try:
                        args = _json.loads(args)
                    except _json.JSONDecodeError:
                        args = {}
                blocks.append({"type": "tool_use", "id": tid, "name": fn.get("name", ""),
                               "input": args})
            if not blocks:
                blocks = [{"type": "text", "text": ""}]
            out.append({"role": "assistant", "content": blocks})
            continue

        # user
        out.append({"role": "user", "content": [{"type": "text", "text": m.get("content") or ""}]})

    flush_results()
    return ("\n\n".join(p for p in system_parts if p), out)


def from_anthropic_response(resp: Any) -> LLMResponse:
    """Anthropic response -> the LLMResponse shape RLMMethod already consumes."""
    text_parts, tool_calls = [], []
    for block in resp.content:
        btype = getattr(block, "type", None)
        if btype == "text":
            text_parts.append(block.text)
        elif btype == "tool_use":
            # re-emit in the Ollama shape so LogREPL.call() dispatch is unchanged
            tool_calls.append({"function": {"name": block.name, "arguments": block.input or {}}})
    u = resp.usage
    return LLMResponse(
        content="".join(text_parts),
        # cache reads/creations are billed input too; count everything the model processed
        prompt_eval_count=(int(getattr(u, "input_tokens", 0) or 0)
                           + int(getattr(u, "cache_read_input_tokens", 0) or 0)
                           + int(getattr(u, "cache_creation_input_tokens", 0) or 0)),
        eval_count=int(getattr(u, "output_tokens", 0) or 0),
        tool_calls=tool_calls or None,
        raw={"stop_reason": getattr(resp, "stop_reason", None), "model": getattr(resp, "model", None)},
    )


class AnthropicClient:
    """Drop-in for OllamaClient. Credentials from the environment ONLY."""

    def __init__(self, model: str | None = None, timeout: float = 300.0,
                 max_retries: int = 3, max_tokens: int = 8000, thinking: bool = False) -> None:
        try:
            import anthropic
        except ModuleNotFoundError as e:  # pragma: no cover - env dependent
            raise RuntimeError("pip install anthropic  (into .venv) to use the Claude arm") from e
        self.model = model or os.environ.get("ANTHROPIC_MODEL", DEFAULT_MODEL)
        self.max_tokens = max_tokens
        self.thinking = thinking
        self._client = anthropic.AsyncAnthropic(timeout=timeout, max_retries=max_retries)

    @property
    def is_cloud(self) -> bool:
        return True

    async def chat(self, messages: list[dict], tools: list[dict] | None = None,
                   think: bool = False, num_ctx: int | None = None) -> LLMResponse:
        """`think` and `num_ctx` are accepted for interface parity.

        num_ctx is meaningless here (1M context). NOTE: no `temperature` is sent — Sonnet 5 rejects
        sampling parameters, so the determinism pin used on the Ollama arms cannot be applied.
        """
        system, msgs = to_anthropic_messages(messages)
        kwargs: dict[str, Any] = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "messages": msgs,
            "thinking": {"type": "adaptive"} if (self.thinking or think) else {"type": "disabled"},
        }
        if system:
            kwargs["system"] = system
        if tools:
            kwargs["tools"] = to_anthropic_tools(tools)
        resp = await self._client.messages.create(**kwargs)
        return from_anthropic_response(resp)

    async def aclose(self) -> None:
        await self._client.close()


async def _smoke() -> None:  # pragma: no cover - manual
    c = AnthropicClient()
    r = await c.chat([{"role": "user", "content": "Reply with the single word: ok"}])
    print(r.content, r.total_tokens)
    await c.aclose()


if __name__ == "__main__":  # pragma: no cover
    asyncio.run(_smoke())
