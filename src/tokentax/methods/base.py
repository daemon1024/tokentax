"""The Method contract — the non-negotiable interface every analysis method returns.

A method takes a window of log records (in some condition) plus a task, and returns a Result
carrying the prediction AND the full cost accounting. The cost fields are what the whole benchmark
exists to compare, so they are part of the contract, not an afterthought.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Result:
    prediction: Any                  # task-specific (label str, or set of trace_ids, ...)
    input_tokens: int = 0            # Σ prompt_eval_count over every call
    output_tokens: int = 0           # Σ eval_count over every call
    total_tokens: int = 0            # input + output (the headline cost)
    latency_ms: float = 0.0          # wall-clock for this example
    gpu_seconds: float = 0.0         # Σ(prompt_eval_duration + eval_duration)/1e9, LOCAL only
    rlm_rounds: int = 0              # tool-call rounds (RLM only)
    aborted: bool = False            # hit the token/cycle ceiling without an answer
    abort_reason: str = ""
    raw_trace: Any = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if not self.total_tokens:
            self.total_tokens = self.input_tokens + self.output_tokens


class Method(ABC):
    """Base class for all analysis methods. ``name`` is used as the cell key."""

    name: str = "method"

    @abstractmethod
    def predict(self, window: Any, task: Any) -> Result:
        """Analyze one window for one task and return a Result with full cost accounting."""
        raise NotImplementedError
