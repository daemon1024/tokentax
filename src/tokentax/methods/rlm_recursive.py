"""Recursive Language Model (faithful) — root orchestrates SUB-LM calls over an offloaded context.

This is the actual RLM mechanism from arXiv:2512.24601 (vs our grep-style navigator in rlm.py):
the full window lives in an environment (the REPL / Python), NEVER in the root model's context. The
root examines metadata + can `llm_query(question, start, end)` to dispatch an INDEPENDENT sub-LM call
on a slice; only the sub-LM's short answer returns to the root. The slice's tokens are spent by the
sub-LM, so the ROOT's context stays tiny even for a million-token window. Token cost = root calls +
all sub calls. We track the max single root-prompt size to show the root never holds the whole input.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field

from tokentax.methods.ollama_client import OllamaClient
from tokentax.methods.repl import LogREPL
from tokentax.nezha import LogRecord, format_window

_SYS = (
    "You are the ROOT orchestrator of a Recursive Language Model. A large microservice log window "
    "(thousands of lines) lives in an ENVIRONMENT — it is NOT in your context and you must never try "
    "to read it all yourself. AT MOST one service is failing; find the single culprit service.\n"
    "Tools:\n"
    "- overview(): metadata (line count, services, severity counts).\n"
    "- grep(pattern): search line text; returns up to a few matching lines (cheap examine).\n"
    "- plan_chunks(chunk_lines): returns the [start,end) ranges to cover the whole window.\n"
    "- llm_query(question, start, end): dispatch a SUB-MODEL to read lines[start:end] and answer your "
    "question; ONLY its short answer returns to you (the lines never enter your context).\n"
    "Strategy: localize with grep; if the relevant region is small you may grep+conclude, otherwise "
    "decompose with plan_chunks and llm_query each chunk ('which service, if any, is failing here?'), "
    "then aggregate the sub-answers. When sure, reply ONLY JSON {\"culprit_service\":\"<name or none>\"} "
    "with no tool call."
)
_SUB_SYS = ("You are a sub-model. Read the log slice and answer the question in ONE short line. "
            "If asked which service is failing, name the single service emitting an error, or 'none'.")


def _parse_final(content: str) -> str | None:
    m = re.search(r"\{[^{}]*culprit_service[^{}]*\}", content, re.DOTALL)
    if not m:
        return None
    try:
        return str(json.loads(m.group(0)).get("culprit_service", "")).strip() or None
    except json.JSONDecodeError:
        return None


def _tools(trace_aware: bool) -> list[dict]:
    def fn(name, desc, props, req):
        return {"type": "function", "function": {
            "name": name, "description": desc,
            "parameters": {"type": "object", "properties": props, "required": req}}}
    tools = [
        fn("overview", "Window metadata: line count, services, severity counts.", {}, []),
        fn("grep", "Search line text (case-insensitive); returns matching lines.",
           {"pattern": {"type": "string"}}, ["pattern"]),
        fn("plan_chunks", "Get [start,end) ranges covering the whole window.",
           {"chunk_lines": {"type": "integer"}}, ["chunk_lines"]),
        fn("llm_query", "Dispatch a sub-model to read lines[start:end] and answer; only its answer returns.",
           {"question": {"type": "string"}, "start": {"type": "integer"}, "end": {"type": "integer"}},
           ["question", "start", "end"]),
    ]
    if trace_aware:  # structured condition exposes the trace-context shortcut
        tools += [
            fn("extract_trace_ids", "List trace_ids with error counts + services (most errors first).",
               {"only_with_errors": {"type": "boolean"}}, []),
            fn("lines_for_trace", "Return all lines of one trace_id.",
               {"trace_id": {"type": "string"}}, ["trace_id"]),
        ]
    return tools


@dataclass
class RecResult:
    prediction: str
    root_in: int = 0
    root_out: int = 0
    sub_in: int = 0
    sub_out: int = 0
    rounds: int = 0
    n_subcalls: int = 0
    max_root_prompt: int = 0   # largest single root context — proves the root never holds it all
    aborted: bool = False
    latency_ms: float = 0.0
    trace: list = field(default_factory=list)

    @property
    def total_tokens(self) -> int:
        return self.root_in + self.root_out + self.sub_in + self.sub_out


class RecursiveRLM:
    name = "rlm_recursive"

    def __init__(self, client: OllamaClient, max_rounds: int = 12, sub_num_ctx: int = 16384,
                 root_num_ctx: int = 8192, max_total_tokens: int = 2_000_000):
        self.client = client
        self.max_rounds = max_rounds
        self.sub_num_ctx = sub_num_ctx
        self.root_num_ctx = root_num_ctx
        self.max_total_tokens = max_total_tokens

    async def apredict(self, records: list[LogRecord], condition: str, task: str = "root_cause") -> RecResult:
        trace_aware = condition == "structured"
        repl = LogREPL(records, trace_aware=trace_aware)
        n = len(repl.lines)
        nav = ("This window is STRUCTURED: lines carry svc=/sev=/trace= tags and you also have "
               "extract_trace_ids(only_with_errors=true) + lines_for_trace — use them to jump to the "
               "failing service directly." if trace_aware else
               "This window is PLAIN: lines are raw message bodies only (no service/severity tags, no "
               "trace tools). You must infer the failing service from the message content.")
        res = RecResult(prediction="unknown")
        messages = [{"role": "system", "content": _SYS + "\n" + nav},
                    {"role": "user", "content": f"overview:\n{repl.overview()}\n\nFind the culprit service."}]
        t0 = time.time()
        for rnd in range(1, self.max_rounds + 1):
            res.rounds = rnd
            resp = await self.client.chat(messages, tools=_tools(trace_aware),
                                          think=False, num_ctx=self.root_num_ctx)
            res.root_in += resp.prompt_eval_count
            res.root_out += resp.eval_count
            res.max_root_prompt = max(res.max_root_prompt, resp.prompt_eval_count)
            if res.total_tokens > self.max_total_tokens:
                res.aborted = True
                break
            if not resp.tool_calls:
                final = _parse_final(resp.content)
                if final:
                    res.prediction = final
                    break
                messages.append({"role": "assistant", "content": resp.content or ""})
                messages.append({"role": "user", "content": "Final answer as JSON {\"culprit_service\":..}."})
                continue
            messages.append({"role": "assistant", "content": resp.content or "",
                             "tool_calls": resp.tool_calls})
            for tc in resp.tool_calls:
                fnc = tc.get("function", {})
                name = fnc.get("name", "")
                args = fnc.get("arguments", {}) or {}
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except json.JSONDecodeError:
                        args = {}
                if name == "llm_query":
                    start = max(0, int(args.get("start", 0)))
                    end = min(n, int(args.get("end", start)))
                    question = str(args.get("question", "which service is failing here?"))
                    chunk = format_window(records[start:end], condition)
                    sub = await self.client.chat(
                        [{"role": "system", "content": _SUB_SYS},
                         {"role": "user", "content": f"{question}\n\n--- lines {start}:{end} ---\n{chunk}"}],
                        think=False, num_ctx=self.sub_num_ctx)
                    res.sub_in += sub.prompt_eval_count
                    res.sub_out += sub.eval_count
                    res.n_subcalls += 1
                    out = (sub.content or "")[:400]
                    res.trace.append({"round": rnd, "llm_query": f"{start}:{end}", "answer": out[:80]})
                elif name == "plan_chunks":
                    size = max(20, int(args.get("chunk_lines", 150)))
                    ranges = [(i, min(i + size, n)) for i in range(0, n, size)]
                    more = " …" if len(ranges) > 12 else ""
                    out = f"{len(ranges)} chunks of {size} lines: {ranges[:12]}{more}"
                    res.trace.append({"round": rnd, "plan_chunks": out[:80]})
                else:
                    out = repl.call(name, args)
                    res.trace.append({"round": rnd, "tool": name})
                messages.append({"role": "tool", "tool_name": name, "content": out})
        else:
            res.aborted = True
        res.latency_ms = (time.time() - t0) * 1000
        return res
