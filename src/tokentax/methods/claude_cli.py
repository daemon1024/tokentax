"""Claude via the `claude -p` CLI (uses the user's subscription, no API key).

Each call carries a fixed ~30k-token Claude Code harness overhead (system prompt + tools). That
overhead is CONSTANT across conditions, so it cancels in the structured-vs-plain (otel-vs-raw)
comparison — we report tokens as-is (no subtraction), noting the constant offset. Token usage is
read from `--output-format json`'s `usage` block.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass


@dataclass
class ClaudeResponse:
    content: str
    input_tokens: int       # all input processed: prompt + cached harness (creation+read)
    output_tokens: int
    cost_usd: float
    raw: dict

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


def claude_call(
    prompt: str, model: str = "sonnet", timeout: float = 900.0,
    allowed_tools: str | None = None,
) -> ClaudeResponse:
    """One headless Claude call via the subscription CLI. Prompt passed on stdin (handles big logs).

    allowed_tools: e.g. "Grep,Read,Bash" to let Claude navigate a log file with its native tools
    (the RLM path) — usage then reflects only what it read, not the whole file.
    """
    cmd = ["claude", "-p", "--output-format", "json", "--model", model]
    if allowed_tools:
        cmd += ["--allowedTools", allowed_tools, "--permission-mode", "bypassPermissions"]
    proc = subprocess.run(
        cmd, input=prompt, capture_output=True, text=True, timeout=timeout,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"claude -p failed (rc={proc.returncode}): {proc.stderr[:300]}")
    data = json.loads(proc.stdout)
    if data.get("is_error"):
        raise RuntimeError(f"claude -p error: {data.get('result', '')[:300]}")
    u = data.get("usage", {}) or {}
    in_tok = (int(u.get("input_tokens", 0) or 0)
              + int(u.get("cache_creation_input_tokens", 0) or 0)
              + int(u.get("cache_read_input_tokens", 0) or 0))
    return ClaudeResponse(
        content=data.get("result", ""),
        input_tokens=in_tok,
        output_tokens=int(u.get("output_tokens", 0) or 0),
        cost_usd=float(data.get("total_cost_usd", 0) or 0),
        raw=data,
    )
