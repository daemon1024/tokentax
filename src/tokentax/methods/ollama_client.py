"""Ollama client — same code for local and Ollama Cloud, selected purely by environment.

env:
  OLLAMA_HOST    local default http://localhost:11434; cloud https://ollama.com/api
  OLLAMA_MODEL   e.g. qwen3.5:9b (dev) / qwen3.5:27b (RLM) / qwen3.5:122b (final)
  OLLAMA_API_KEY when set, sent as `Authorization: Bearer ...` (the Ollama Cloud path)

The API key is read ONLY from the environment — never passed in code or args.
Returns content + the token/duration counters the benchmark accounts on (prompt_eval_count,
eval_count, prompt_eval_duration, eval_duration). Live-tested once Ollama is reachable (Phase 0
smoke test); the Drain slice does not import this module.
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from typing import Any

import httpx


@dataclass
class LLMResponse:
    content: str
    prompt_eval_count: int = 0
    eval_count: int = 0
    prompt_eval_duration_ns: int = 0
    eval_duration_ns: int = 0
    total_duration_ns: int = 0
    tool_calls: list[dict] | None = None
    raw: dict | None = None

    @property
    def total_tokens(self) -> int:
        return self.prompt_eval_count + self.eval_count

    @property
    def gpu_seconds(self) -> float:
        # prefill + decode; excludes load_duration. LOCAL only — cloud returns these as null,
        # so this is 0.0 on cloud (use total_duration_ns / tokens there instead).
        return (self.prompt_eval_duration_ns + self.eval_duration_ns) / 1e9

    @property
    def latency_ms(self) -> float:
        return self.total_duration_ns / 1e6


class OllamaClient:
    def __init__(
        self,
        host: str | None = None,
        model: str | None = None,
        timeout: float = 300.0,
        max_retries: int = 4,
    ) -> None:
        self.host = (host or os.environ.get("OLLAMA_HOST", "http://localhost:11434")).rstrip("/")
        self.model = model or os.environ.get("OLLAMA_MODEL", "qwen3.5:9b")
        self._api_key = os.environ.get("OLLAMA_API_KEY")  # environment ONLY
        self.timeout = timeout
        self.max_retries = max_retries

    @property
    def is_cloud(self) -> bool:
        return bool(self._api_key)

    def _headers(self) -> dict[str, str]:
        h = {"Content-Type": "application/json"}
        if self._api_key:
            h["Authorization"] = f"Bearer {self._api_key}"
        return h

    def _options(self, **overrides: Any) -> dict[str, Any]:
        # Determinism (REVIEW MEASURE-3): temp 0, fixed seed, explicit context window.
        opts = {"temperature": 0, "seed": 0, "num_ctx": 8192}
        opts.update(overrides)
        return opts

    async def _post(self, path: str, payload: dict) -> dict:
        url = f"{self.host}{path}"
        last: Exception | None = None
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            for attempt in range(self.max_retries):
                try:
                    r = await client.post(url, json=payload, headers=self._headers())
                    r.raise_for_status()
                    return r.json()
                # httpx.HTTPError is the base class, so it also covers TransportError.
                except httpx.HTTPError as e:  # pragma: no cover
                    last = e
                    await asyncio.sleep(2**attempt * 0.5)
        raise RuntimeError(f"Ollama {url} failed after {self.max_retries} retries: {last}")

    @staticmethod
    def _extract(data: dict, content: str, tool_calls: list[dict] | None) -> LLMResponse:
        return LLMResponse(
            content=content,
            prompt_eval_count=int(data.get("prompt_eval_count", 0) or 0),
            eval_count=int(data.get("eval_count", 0) or 0),
            prompt_eval_duration_ns=int(data.get("prompt_eval_duration", 0) or 0),
            eval_duration_ns=int(data.get("eval_duration", 0) or 0),
            total_duration_ns=int(data.get("total_duration", 0) or 0),
            tool_calls=tool_calls,
            raw=data,
        )

    async def generate(
        self, prompt: str, system: str | None = None, think: bool | None = None, **opts: Any
    ) -> LLMResponse:
        payload: dict[str, Any] = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "options": self._options(**opts),
        }
        if system:
            payload["system"] = system
        if think is not None:
            payload["think"] = think
        data = await self._post("/api/generate", payload)
        return self._extract(data, data.get("response", ""), None)

    async def chat(
        self, messages: list[dict], tools: list[dict] | None = None,
        think: bool | None = None, **opts: Any,
    ) -> LLMResponse:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "options": self._options(**opts),
        }
        if tools:
            payload["tools"] = tools
        if think is not None:
            payload["think"] = think
        data = await self._post("/api/chat", payload)
        msg = data.get("message", {}) or {}
        return self._extract(data, msg.get("content", ""), msg.get("tool_calls"))
