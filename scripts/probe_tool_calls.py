"""ONE tiny request per candidate model: can it drive the Ollama tools API the way the harness does?

    set -a; . ./.env; set +a
    .venv/bin/python scripts/probe_tool_calls.py muse-spark-open beam minimax-m3.1-flash ...

Same client and call shape as the forensics harness (`forensics_v2.GuardedOllamaClient`, think=False,
num_ctx 32,768, temperature 0, seed 0), one tool schema, a prompt that requires calling it. PASS iff the
reply carries a well-formed tool call: function name `get_weather` and an arguments object whose `city`
names Paris. Anything else (no call, wrong name, malformed arguments, HTTP 402/403/404/410/5xx) is a
FAIL and the model is excluded. One attempt per model; a usage-limit 429 stops the probe.
Writes one JSON line per model to results/runs/model_probe.jsonl (appends; the date is in each row).
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from tokentax.forensics_v2 import GuardedOllamaClient, UsageLimitReached  # noqa: E402

OUT = ROOT / "results/runs/model_probe.jsonl"
TOOL = [{"type": "function", "function": {
    "name": "get_weather", "description": "Current weather for a city.",
    "parameters": {"type": "object", "properties": {"city": {"type": "string"}}, "required": ["city"]}}}]
MESSAGES = [{"role": "system", "content": "You answer by calling tools. Never answer from memory."},
            {"role": "user", "content": "What is the weather in Paris right now? Call the tool."}]


def judge(tool_calls) -> tuple[bool, str]:
    if not tool_calls:
        return False, "no tool call"
    fn = (tool_calls[0] or {}).get("function", {}) or {}
    if fn.get("name") != "get_weather":
        return False, f"wrong function name {fn.get('name')!r}"
    args = fn.get("arguments", {})
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except json.JSONDecodeError:
            return False, "arguments not JSON"
    if not isinstance(args, dict) or "paris" not in str(args.get("city", "")).lower():
        return False, f"bad arguments {args!r}"
    return True, "ok"


async def probe(model: str) -> dict:
    c = GuardedOllamaClient(model=model, timeout=120, max_retries=1)
    t0 = time.perf_counter()
    row = {"date": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "model": model, "host": c.host}
    try:
        r = await c.chat(MESSAGES, tools=TOOL, think=False, num_ctx=32_768)
        ok, why = judge(r.tool_calls)
        row.update(passed=ok, reason=why, tool_calls=r.tool_calls, content=(r.content or "")[:200],
                   prompt_tokens=r.prompt_eval_count, output_tokens=r.eval_count, total_tokens=r.total_tokens)
    except UsageLimitReached as e:
        row.update(passed=False, reason="usage_limit", error=str(e)[:300], total_tokens=0)
    except Exception as e:  # noqa: BLE001
        row.update(passed=False, reason="error", error=f"{type(e).__name__}: {e}"[:300], total_tokens=0)
    row["latency_s"] = round(time.perf_counter() - t0, 1)
    return row


async def main(models: list[str]) -> int:
    for m in models:
        row = await probe(m)
        with OUT.open("a") as f:
            f.write(json.dumps(row) + "\n")
        print(f"{'PASS' if row['passed'] else 'FAIL'} {m:28s} {row['reason']:28s} tok={row.get('total_tokens', 0):<6} "
              f"{row.get('error', '')[:90]}", flush=True)
        if row["reason"] == "usage_limit":
            print("usage limit: stopping the probe", flush=True)
            return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main(sys.argv[1:])))
