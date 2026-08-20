"""Recursive Language Model method — root model navigates a large window via REPL tools.

The root never receives the full window — only `overview()` metadata — and must call tools to
investigate. Token cost = Σ(prompt_eval_count + eval_count) over EVERY round, which correctly
includes the growing re-sent transcript and every tool result fed back (REVIEW RLM-2). This is the
method whose token cost the thesis claims structure (trace ids) makes small.
"""

from __future__ import annotations

import json
import re
import time

from tokentax.methods.base import Result
from tokentax.methods.ollama_client import OllamaClient
from tokentax.methods.repl import LogREPL, tool_schemas
from tokentax.nezha import LogRecord

_SYS = (
    "You are an SRE diagnosing whether a microservice log window (too large to read in full) "
    "contains a fault. AT MOST one service is failing. Use the tools to navigate efficiently. "
    "IMPORTANT: healthy services also emit some ERROR lines during normal operation, so look for a "
    "service ORIGINATING a distinctive failure (e.g. a backend-unavailable error). "
    "{nav} "
    "When confident, reply with ONLY JSON {{\"culprit_service\": \"<service-name or none>\"}} "
    "(use 'none' if no service is failing) and DO NOT call a tool in that final turn."
)
# Navigation hints are PARALLEL across conditions by design. The 2026-06 prompts told the structured
# arm to call its digest first and "answer from the digest if it is clear", and told the plain arm only
# to grep -- prompt-level steering stacked on top of the tool-level advantage. See WITHDRAWAL.md.
_NAV_COMMON = ("Call {digest}() FIRST for a compact ranked ERROR digest, and answer from it if it is "
               "clear. Use grep/peek to read around specific lines when it is not.")
_NAV_EXTRA = {
    "plain": "",
    "structured_no_trace": "",
    "structured": " You also have extract_trace_ids/lines_for_trace to group lines by request.",
}
_DIGEST = {
    "plain": "errors_by_cluster",
    "structured_no_trace": "errors_by_service",
    "structured": "errors_by_service",
}


def _nav_for(condition: str) -> str:
    return _NAV_COMMON.format(digest=_DIGEST[condition]) + _NAV_EXTRA[condition]


def _parse_final(content: str) -> str | None:
    m = re.search(r"\{[^{}]*culprit_service[^{}]*\}", content, flags=re.DOTALL)
    if not m:
        return None
    try:
        return str(json.loads(m.group(0)).get("culprit_service", "")).strip() or None
    except json.JSONDecodeError:
        return None


class RLMMethod:
    name = "rlm"

    def __init__(self, client: OllamaClient, max_rounds: int = 20,
                 max_total_tokens: int = 250_000, num_ctx: int = 32_768):
        self.client = client
        self.max_rounds = max_rounds
        self.max_total_tokens = max_total_tokens
        self.num_ctx = num_ctx

    async def apredict(self, records: list[LogRecord], condition: str, task: str) -> Result:
        repl = LogREPL(records, condition=condition)
        tools = tool_schemas(condition=condition)
        system = _SYS.format(nav=_nav_for(condition))
        messages: list[dict] = [
            {"role": "system", "content": system},
            {"role": "user", "content": "Here is the window overview:\n" + repl.overview()
             + "\n\nFind the single culprit service."},
        ]

        in_tok = out_tok = rounds = 0
        gpu_s = 0.0
        trace: list[dict] = []
        prediction, aborted, reason = "unknown", False, ""
        t0 = time.perf_counter()
        for rounds in range(1, self.max_rounds + 1):
            resp = await self.client.chat(messages, tools=tools, think=False, num_ctx=self.num_ctx)
            in_tok += resp.prompt_eval_count
            out_tok += resp.eval_count
            gpu_s += resp.gpu_seconds  # 0.0 on cloud (durations come back null); real on local

            if resp.tool_calls:
                messages.append({"role": "assistant", "content": resp.content or "",
                                 "tool_calls": resp.tool_calls})
                for tc in resp.tool_calls:
                    fn = tc.get("function", {})
                    name = fn.get("name", "")
                    args = fn.get("arguments", {}) or {}
                    if isinstance(args, str):
                        try:
                            args = json.loads(args)
                        except json.JSONDecodeError:
                            args = {}
                    result = repl.call(name, args)
                    trace.append({"round": rounds, "tool": name, "args": args,
                                  "result_preview": result[:200]})
                    messages.append({"role": "tool", "tool_name": name, "content": result})
                if in_tok + out_tok > self.max_total_tokens:
                    aborted, reason = True, "token_ceiling"
                    break
                continue

            # no tool call -> expect a final answer
            final = _parse_final(resp.content)
            trace.append({"round": rounds, "final": resp.content[:200]})
            if final:
                prediction = final
                break
            # nudge once for a decision
            messages.append({"role": "assistant", "content": resp.content or ""})
            messages.append({"role": "user",
                             "content": "Give your final answer as JSON {\"culprit_service\": ...}."})
        else:
            aborted, reason = True, "max_rounds"

        return Result(
            prediction=prediction,
            input_tokens=in_tok,
            output_tokens=out_tok,
            latency_ms=(time.perf_counter() - t0) * 1000,
            gpu_seconds=gpu_s,
            rlm_rounds=rounds,
            aborted=aborted,
            abort_reason=reason,
            raw_trace=trace,
        )
