"""In-context LLM method — read the whole window in one prompt (chunk if it overflows).

The "read everything" baseline the RLM must beat on tokens. Formats a window in one of the three
conditions, sends it to Qwen via Ollama, and parses a JSON answer. If the window exceeds the input
budget it is split into record-chunks, each queried, and the answers aggregated.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field

import tiktoken

from tokentax.methods.base import Result
from tokentax.methods.ollama_client import OllamaClient
from tokentax.nezha import LogRecord, format_window

_ENC = tiktoken.get_encoding("cl100k_base")

SYSTEM = {
    "root_cause": (
        "You are an SRE analyzing logs from ONE fixed time window of a microservice system. "
        "Exactly one service has an injected fault. Identify the single culprit service, using the "
        "service name exactly as it appears in the logs (e.g. 'ts-basic-service' or 'paymentservice'). "
        'Respond with ONLY JSON: {"culprit_service": "<name>"}.'
    ),
    "trace_anomaly": (
        "You are an SRE. The window below contains many distributed traces; some are affected by an "
        "injected fault and some are normal. List the trace_ids of the anomalous traces. "
        'Respond with ONLY JSON: {"anomalous_trace_ids": ["<id>", ...]}.'
    ),
}


def _parse_json(content: str) -> dict:
    content = content.strip()
    content = re.sub(r"^```(?:json)?|```$", "", content, flags=re.MULTILINE).strip()
    m = re.search(r"\{.*\}", content, flags=re.DOTALL)
    if not m:
        return {}
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return {}


def _ntok(s: str) -> int:
    return len(_ENC.encode(s, disallowed_special=()))


def _chunk_records(records: list[LogRecord], condition: str, max_input_tokens: int) -> list[str]:
    """Split records so each rendered chunk is <= max_input_tokens (proxy-measured)."""
    chunks: list[str] = []
    cur: list[LogRecord] = []
    for r in records:
        cur.append(r)
        if _ntok(format_window(cur, condition)) >= max_input_tokens:
            chunks.append(format_window(cur[:-1] or cur, condition))
            cur = [r]
    if cur:
        chunks.append(format_window(cur, condition))
    return [c for c in chunks if c]


@dataclass
class _Agg:
    prediction: object
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: float = 0.0
    n_calls: int = 0
    raw: list = field(default_factory=list)


class InContextMethod:
    name = "in_context"

    def __init__(self, client: OllamaClient, max_input_tokens: int = 110_000, num_ctx: int = 131_072):
        self.client = client
        self.max_input_tokens = max_input_tokens
        self.num_ctx = num_ctx

    async def apredict(self, records: list[LogRecord], condition: str, task: str) -> Result:
        system = SYSTEM[task]
        full = format_window(records, condition)
        chunks = [full] if _ntok(full) <= self.max_input_tokens else _chunk_records(
            records, condition, self.max_input_tokens
        )
        agg = _Agg(prediction=None)
        culprit_votes: list[str] = []
        anomalous: set[str] = set()
        t0 = time.perf_counter()
        for chunk in chunks:
            resp = await self.client.chat(
                [{"role": "system", "content": system}, {"role": "user", "content": chunk}],
                think=False, num_ctx=self.num_ctx,
            )
            agg.input_tokens += resp.prompt_eval_count
            agg.output_tokens += resp.eval_count
            agg.n_calls += 1
            agg.raw.append(resp.content)
            parsed = _parse_json(resp.content)
            if task == "root_cause":
                v = str(parsed.get("culprit_service", "")).strip()
                if v and v.lower() not in ("none", "unknown", ""):
                    culprit_votes.append(v)
            else:
                for tid in parsed.get("anomalous_trace_ids", []) or []:
                    anomalous.add(str(tid).strip())
        agg.latency_ms = (time.perf_counter() - t0) * 1000

        if task == "root_cause":
            pred = max(set(culprit_votes), key=culprit_votes.count) if culprit_votes else "unknown"
        else:
            pred = anomalous
        return Result(
            prediction=pred,
            input_tokens=agg.input_tokens,
            output_tokens=agg.output_tokens,
            latency_ms=agg.latency_ms,
            gpu_seconds=0.0,  # cloud exposes no per-request GPU time
            rlm_rounds=agg.n_calls,
            raw_trace=agg.raw,
        )
