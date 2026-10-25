"""Per-request forensics V3: two new arms that split the V2 lookup result into its parts.

    Tt  structured_trace_text   lines AND seed rendered EXACTLY as T (`svc= sev= trace=<8 hex>` + body,
                                seed with the full trace_id), but the trace INDEX is off, exactly as in S:
                                lines_for_trace / extract_trace_ids / the trace_id= scope of both digests
                                reply "not available", and the overview is S's. `grep` still searches the
                                printed lines, so grepping the id returns the request's lines.
    Th  structured_hint         T in every respect plus ONE sentence in the system prompt (HINT).

Contrasts: S -> Tt (the id printed on every line, no lookup); Tt -> T (the lookup, holding the printed id
constant); T -> Th (telling the model what the field is for).

Everything else is V1/V2: the byte-identical tool schema (`forensics.forensics_tool_schemas()`), the agent
loop (`run_agent_v3` is `forensics.run_agent` line for line with the REPL, seed and system text injected;
tests/test_forensics_v3.py checks it sends identical messages for P / S / T), the scoring, the Meter.
"""

from __future__ import annotations

import json

from tokentax import forensics as F
from tokentax.nezha import LogRecord, _service_of

ARMS_V3 = {"P": "plain", "S": "structured_no_trace", "T": "structured",
           "Tt": "structured_trace_text", "Th": "structured_hint"}
ARM_ORDER = ("P", "S", "T", "Tt", "Th")
TRACE_TEXT = "structured_trace_text"
HINTED = "structured_hint"

# The one sentence arm Th adds. Accurate for this harness: lines print the first 8 hex characters of the
# request's trace_id, and lines_for_trace accepts that unique prefix (ForensicsREPL._resolve_trace).
HINT = ("Every log line carries trace=<id>, the id of the request it belongs to. "
        "lines_for_trace(id) returns every line of one request. ")
SYSTEM_HINT = F.SYSTEM.replace("{roster}", "{roster}" + HINT)
assert SYSTEM_HINT != F.SYSTEM and SYSTEM_HINT.count(HINT) == 1


class TraceTextREPL(F.ForensicsREPL):
    """`ForensicsREPL` in the S condition (no trace index), with every line re-rendered as T renders it."""

    def __init__(self, records: list[LogRecord]):
        super().__init__(records, condition="structured_no_trace")
        self.lines = [f"[{i}] svc={_service_of(r.pod)} sev={r.level or 'LOG'} "
                      f"trace={r.trace_id[:8]} {r.to_plain()}"
                      for i, r in enumerate(records)]
        self.condition = TRACE_TEXT


def base_condition(condition: str) -> str:
    """The V1 condition whose rendering the arm's seed uses."""
    return "structured" if condition in (TRACE_TEXT, HINTED) else condition


def make_repl(records: list[LogRecord], condition: str) -> F.ForensicsREPL:
    if condition == TRACE_TEXT:
        return TraceTextREPL(records)
    return F.ForensicsREPL(records, base_condition(condition))


def render_seed(record: LogRecord, condition: str) -> str:
    """Tt and Th show the seed exactly as T does (full trace_id)."""
    return F.render_seed(record, base_condition(condition))


def system_text(records: list[LogRecord], condition: str) -> str:
    tmpl = SYSTEM_HINT if condition == HINTED else F.SYSTEM
    return tmpl.format(roster=F.roster_text(records))


def user_message(repl: F.ForensicsREPL, record: LogRecord, condition: str) -> str:
    """`forensics.user_message` with the V3 seed renderer (identical text for P / S / T)."""
    return (f"Window overview:\n{repl.overview()}\n\n"
            f"The error line, logged at {F.iso(record.time_unix_nano)}:\n"
            f"{render_seed(record, condition)}\n\n"
            "Find the other lines of the same request and the service where the failure originated.")


async def run_agent_v3(client, records: list[LogRecord], condition: str, case: F.Case, meter: F.Meter,
                       max_rounds: int, max_total_tokens: int, num_ctx: int) -> F.Outcome:
    """`forensics.run_agent`, line for line, with `make_repl` / `user_message` / `system_text` injected."""
    repl = make_repl(records, condition)
    tools = F.forensics_tool_schemas()
    seed = records[case.seed_idx]
    messages: list[dict] = [
        {"role": "system", "content": system_text(records, condition)},
        {"role": "user", "content": user_message(repl, seed, condition)},
    ]
    for rnd in range(1, max_rounds + 1):
        resp = await client.chat(messages, tools=tools, think=False, num_ctx=num_ctx)
        meter.in_tok += resp.prompt_eval_count
        meter.out_tok += resp.eval_count
        meter.gpu_s += resp.gpu_seconds
        meter.max_prompt_tok = max(meter.max_prompt_tok, resp.prompt_eval_count)
        meter.rounds = rnd

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
                meter.tools.append(name)
                if result.startswith(F.NOT_AVAILABLE):
                    meter.not_available += 1
                meter.trace.append({"round": rnd, "tool": name, "args": args,
                                    "result_chars": len(result), "result_preview": result[:160]})
                messages.append({"role": "tool", "tool_name": name, "content": result})
            if meter.total > max_total_tokens:
                return F.Outcome(None, "", True, "token_ceiling")
            continue

        final = F.parse_final(resp.content)
        meter.trace.append({"round": rnd, "final": (resp.content or "")[:300]})
        if final:
            return F.Outcome(final[0], final[1], False, "")
        messages.append({"role": "assistant", "content": resp.content or ""})
        messages.append({"role": "user", "content":
                         'Give your final answer as JSON {"line_indices": [...], "root_service": "..."}.'})
    return F.Outcome(None, "", True, "max_rounds")


# ----------------------------------------------------------------------------------------------
# pre-registered secondary metric: did the run search for the request's own trace id?
# ----------------------------------------------------------------------------------------------
def _hexes(s: str) -> list[str]:
    import re
    return re.findall(r"[0-9a-f]{8,}", str(s).lower())


def used_trace_id(trace_events: list[dict], seed_trace: str) -> dict:
    """Which tools the run pointed at the seed's trace id (any >= 8-hex run that is a substring of it).

    `grep_trace`: a grep pattern carried it. `lookup_trace`: lines_for_trace / a digest's trace_id= scope
    carried it (in Tt those reply "not available", and the attempt is still counted).
    """
    tid = (seed_trace or "").lower()
    out = {"grep_trace": False, "lookup_trace": False}
    if not tid:
        return out
    for ev in trace_events or []:
        name, args = ev.get("tool", ""), ev.get("args") or {}
        if not name:
            continue
        hit = any(h in tid for v in args.values() for h in _hexes(v))
        if not hit:
            continue
        if name == "grep":
            out["grep_trace"] = True
        elif name in ("lines_for_trace", "errors_by_cluster", "errors_by_service"):
            out["lookup_trace"] = True
    return out
