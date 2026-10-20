"""Per-request forensics V2: the V1 arms P / S / T unchanged, plus a fourth arm TI ("T-index").

    TI  structured_trace_index   lines rendered EXACTLY as S (svc= sev= body, no `trace=` prefix),
                                 but the seed line carries its full trace_id and the trace index is
                                 live: lines_for_trace, extract_trace_ids and the trace_id= scope of
                                 both digests work as they do in T.

Why the arm exists: in T every line the model reads carries `trace=<8 hex>`, measured at 6.4 cl100k
tokens per line in situ (talk/NUMBERS.md, Stage 3 caveat 1). TI asks whether the join key can pay as an
INDEX (one id in the question, a lookup tool) without paying that tax on every returned line.

Contrasts: S -> T  (the V1 primary, trace_id printed + index); S -> TI (index only); TI -> T (the
per-line prefix, holding the index constant).

What is NOT different between arms: the tool schema (`forensics.forensics_tool_schemas()`, byte-identical,
no condition argument), the system prompt, the overview wording, the seed timestamp, and the agent loop.
P / S / T cells are run by `forensics.run_agent` itself; only TI goes through `run_agent_v2`, which is the
same loop with the REPL and seed rendering injected (tests/test_forensics_v2.py checks that the two loops
send identical messages for P / S / T).
"""

from __future__ import annotations

import asyncio
import json

import httpx

from tokentax import forensics as F
from tokentax.methods.ollama_client import OllamaClient
from tokentax.nezha import LogRecord, _service_of

ARMS_V2 = {"P": "plain", "S": "structured_no_trace", "T": "structured", "TI": "structured_trace_index"}
ARM_ORDER = ("P", "S", "T", "TI")
TRACE_INDEX = "structured_trace_index"


class TraceIndexREPL(F.ForensicsREPL):
    """`ForensicsREPL` in the structured condition (trace index live), re-rendering every line as S does."""

    def __init__(self, records: list[LogRecord]):
        super().__init__(records, condition="structured")
        self.lines = [f"[{i}] svc={_service_of(r.pod)} sev={r.level or 'LOG'} {r.to_plain()}"
                      for i, r in enumerate(records)]
        self.condition = TRACE_INDEX


def make_repl(records: list[LogRecord], condition: str) -> F.ForensicsREPL:
    if condition == TRACE_INDEX:
        return TraceIndexREPL(records)
    return F.ForensicsREPL(records, condition)


def render_seed(record: LogRecord, condition: str) -> str:
    """The seed as the arm's own lines render it; TI shows the full trace_id, exactly as T does."""
    if condition == TRACE_INDEX:
        return F.render_seed(record, "structured")
    return F.render_seed(record, condition)


def user_message(repl: F.ForensicsREPL, record: LogRecord, condition: str) -> str:
    """`forensics.user_message` with the V2 seed renderer (identical text for P / S / T)."""
    return (f"Window overview:\n{repl.overview()}\n\n"
            f"The error line, logged at {F.iso(record.time_unix_nano)}:\n"
            f"{render_seed(record, condition)}\n\n"
            "Find the other lines of the same request and the service where the failure originated.")


async def run_agent_v2(client, records: list[LogRecord], condition: str, case: F.Case, meter: F.Meter,
                       max_rounds: int, max_total_tokens: int, num_ctx: int) -> F.Outcome:
    """`forensics.run_agent`, line for line, with `make_repl` / `user_message` injected."""
    repl = make_repl(records, condition)
    tools = F.forensics_tool_schemas()
    seed = records[case.seed_idx]
    messages: list[dict] = [
        {"role": "system", "content": F.SYSTEM.format(roster=F.roster_text(records))},
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


async def run_cell_agent(client, records, condition, case, meter, max_rounds, max_total_tokens, num_ctx):
    """P / S / T through the unchanged V1 loop; TI through the injected copy."""
    if condition == TRACE_INDEX:
        return await run_agent_v2(client, records, condition, case, meter, max_rounds, max_total_tokens,
                                  num_ctx)
    return await F.run_agent(client, records, condition, case, meter, max_rounds, max_total_tokens, num_ctx)


# ----------------------------------------------------------------------------------------------
# a client that stops on a usage limit instead of retrying into it
# ----------------------------------------------------------------------------------------------
class UsageLimitReached(RuntimeError):
    """HTTP 429 whose body says the account's usage limit is exhausted. Never retried."""


def is_usage_limit(status: int, body: str) -> bool:
    return status == 429 and "usage limit" in (body or "").lower()


class GuardedOllamaClient(OllamaClient):
    """`OllamaClient` with one change: a 429 whose body says "usage limit" raises `UsageLimitReached`
    at once. The base client backs off and retries every 429 (correct for a rate limit, wrong for an
    exhausted account: each retry is another request against a spent quota). Everything else, including
    the retry schedule and the error text `classify_error` parses, is the base client's."""

    async def _post(self, path: str, payload: dict) -> dict:
        url = f"{self.host}{path}"
        last: Exception | None = None
        body = ""
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            for attempt in range(self.max_retries):
                try:
                    r = await client.post(url, json=payload, headers=self._headers())
                    if is_usage_limit(r.status_code, r.text):
                        raise UsageLimitReached(f"HTTP 429 usage limit: {r.text[:300]}")
                    body = r.text[:200] if r.status_code >= 400 else ""
                    r.raise_for_status()
                    return r.json()
                except httpx.HTTPStatusError as e:
                    last = e
                    if e.response.status_code == 429:
                        try:
                            wait = float(e.response.headers.get("retry-after", 0)) or 2 ** attempt * 8
                        except ValueError:
                            wait = 2 ** attempt * 8
                        await asyncio.sleep(min(wait, 120))
                    else:
                        await asyncio.sleep(2 ** attempt * 0.5)
                except httpx.HTTPError as e:
                    last = e
                    await asyncio.sleep(2 ** attempt * 0.5)
        raise RuntimeError(f"Ollama {url} failed after {self.max_retries} retries: {last} body={body!r}")
