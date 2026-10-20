"""Per-request forensics: given ONE error line, find the other lines of the same request.

This is the task on which `trace_id` is a JOIN KEY rather than a label. The earlier culprit-service
task was answered by counting ERROR lines per service and never needed a cross-service join, which is
why adding `trace_id` measured as a null there (results/NAVIGATION.md, WITHDRAWAL.md).

Three arms, mapped onto the existing `LogREPL` conditions, differing ONLY in the fields on each line:

    P  plain                 body only (identity scrubbed by LogRecord.body())
    S  structured_no_trace   + service.name + severity
    T  structured            + trace_id

Ground truth for the line set is "every line sharing the seed's trace_id", so it does not depend on
fault labels. The seed line itself is given to the model, so it is removed from BOTH the truth set and
the prediction before scoring; otherwise a trace of four lines would hand every arm 25% F1 for free.

Hard rules inherited from CLAUDE.md, and where they are enforced here:
  * matched tool capability  -> `forensics_tool_schemas()` is ONE schema, byte-identical in every arm; a
                                tool whose backing field is absent replies with an explicit
                                "not available" string. `lines_near` is new and is in every arm.
  * one system prompt         -> `SYSTEM` has no per-arm text. The overview is data only (no "use the
                                trace tools" hint in T, no "no service field" hint in P).
  * failures are data         -> `Meter` accumulates tokens as rounds complete, so a wall-clock timeout
                                keeps the tokens spent so far (a lower bound) instead of becoming 0.
"""

from __future__ import annotations

import bisect
import json
import random
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from tokentax.methods.repl import LogREPL, tool_schemas
from tokentax.nezha import LogRecord, _service_of

ARMS = {"P": "plain", "S": "structured_no_trace", "T": "structured"}
ARM_OF = {v: k for k, v in ARMS.items()}

# Fixed config of `lines_near`; part of the pre-registration, identical in every arm.
NEAR_MAX_LINES = 40
NEAR_MAX_SECONDS = 30.0
NEAR_DEFAULT_SECONDS = 0.5

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


# ----------------------------------------------------------------------------------------------
# time
# ----------------------------------------------------------------------------------------------
def parse_timestamp(value) -> int:
    """Unix nanoseconds from an ISO-8601 string (Z or offset; naive means UTC) or a bare number.

    A bare number is read as s / ms / us / ns by magnitude, because a model that copies a timestamp
    out of a tool result may hand back any of them.
    """
    if isinstance(value, bool):
        raise ValueError(f"not a timestamp: {value!r}")
    if isinstance(value, int | float):
        return _from_number(float(value))
    s = str(value).strip()
    if not s:
        raise ValueError("empty timestamp")
    try:
        return _from_number(float(s))
    except ValueError:
        pass
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00").replace(" ", "T", 1))
    except ValueError as e:
        raise ValueError(f"cannot parse {s!r} as ISO-8601 or epoch") from e
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return ((dt - _EPOCH) // timedelta(microseconds=1)) * 1000


def _from_number(v: float) -> int:
    a = abs(v)
    if a >= 1e17:
        return int(v)
    if a >= 1e14:
        return int(v * 1e3)
    if a >= 1e11:
        return int(v * 1e6)
    return int(v * 1e9)


def iso(ns: int) -> str:
    """UTC ISO-8601 with millisecond precision, e.g. 2026-06-03T18:35:22.288Z."""
    dt = _EPOCH + timedelta(seconds=ns // 1_000_000_000)
    return f"{dt:%Y-%m-%dT%H:%M:%S}.{(ns % 1_000_000_000) // 1_000_000:03d}Z"


# ----------------------------------------------------------------------------------------------
# tools
# ----------------------------------------------------------------------------------------------
class ForensicsREPL(LogREPL):
    """`LogREPL` + `lines_near`, with an overview that carries data only and trace-prefix resolution."""

    def __init__(self, records: list[LogRecord], condition: str):
        super().__init__(records, condition=condition)
        self._times = [r.time_unix_nano for r in records]
        if self._times != sorted(self._times):
            raise ValueError("records must be time-sorted: index order is what `lines_near` relies on")

    # --- overview: data only, identical wording in every arm ---
    def overview(self) -> str:
        out = [f"window: {len(self.records)} log lines."]
        if self._times:
            out.append(f"time span: {iso(self._times[0])} to {iso(self._times[-1])} (UTC).")
        if self.has_fields:
            sev: dict[str, int] = {}
            for r in self.records:
                sev[r.level or "LOG"] = sev.get(r.level or "LOG", 0) + 1
            out.append(f"severity counts: {sev}")
            services = sorted({_service_of(r.pod) for r in self.records})
            out.append(f"{len(services)} services: {', '.join(services)}")
        if self.trace_aware:
            out.append(f"distinct trace_ids: {len(self._by_trace)}")
        return "\n".join(out)

    # --- a trace_id is displayed as an 8-char prefix on every line, so accept a unique prefix ---
    def _resolve_trace(self, tid: str) -> str:
        tid = str(tid or "").strip()
        if not self.trace_aware or tid in self._by_trace or len(tid) < 8:
            return tid
        hits = [k for k in self._by_trace if k.startswith(tid)]
        return hits[0] if len(hits) == 1 else tid

    def _scope(self, trace_id: str = ""):
        return super()._scope(self._resolve_trace(trace_id))

    def lines_for_trace(self, trace_id: str) -> str:
        return super().lines_for_trace(self._resolve_trace(trace_id))

    # --- the new tool, available in every arm: time is not a structured field, every log has it ---
    def lines_near(self, timestamp, seconds=NEAR_DEFAULT_SECONDS, max_lines: int = NEAR_MAX_LINES) -> str:
        try:
            centre = parse_timestamp(timestamp)
        except ValueError as e:
            return f"bad timestamp: {e}"
        try:
            sec = float(seconds)
        except (TypeError, ValueError):
            return f"bad seconds: {seconds!r}"
        if not 0 <= sec <= NEAR_MAX_SECONDS:
            return f"seconds must be between 0 and {NEAR_MAX_SECONDS:g}."
        half = int(sec * 1e9)
        lo = bisect.bisect_left(self._times, centre - half)
        hi = bisect.bisect_right(self._times, centre + half)
        n = hi - lo
        if n == 0:
            span = f" (window spans {iso(self._times[0])} to {iso(self._times[-1])})" if self._times else ""
            return f"no lines within +/-{sec:g}s of {iso(centre)}{span}."
        idxs = list(range(lo, hi))
        if n > max_lines:
            # keep the lines CLOSEST to the centre, but show them in index (= time) order
            idxs = sorted(sorted(idxs, key=lambda i: (abs(self._times[i] - centre), i))[:max_lines])
        body = "\n".join(self.lines[i] for i in idxs)
        more = (f"\n... ({n - len(idxs)} further lines in range not shown; narrow `seconds`)"
                if n > len(idxs) else "")
        return f"{n} lines within +/-{sec:g}s of {iso(centre)}:\n{body}{more}"

    def call(self, name: str, args: dict) -> str:
        if name != "lines_near":
            return super().call(name, args)

        def arg(*keys, default=None):
            for k in keys:
                if k in args and args[k] not in (None, ""):
                    return args[k]
            return default

        ts = arg("timestamp", "time", "ts", "at", "t")
        if ts is None:
            return "tool error in lines_near: timestamp is required."
        return self.lines_near(ts, arg("seconds", "window", "radius", "secs", "delta",
                                       default=NEAR_DEFAULT_SECONDS))


def forensics_tool_schemas() -> list[dict]:
    """ONE schema for all three arms: the existing matched set plus `lines_near`.

    Byte-identical across arms by construction (it takes no condition argument), so the per-request
    schema cost cannot differ and the only thing that varies is the data behind the tools.
    """
    tools = tool_schemas(condition="structured", matched_schemas=True)
    tools.append({"type": "function", "function": {
        "name": "lines_near",
        "description": ("Return the log lines within +/- `seconds` of an ISO-8601 UTC timestamp, "
                        "with their indices."),
        "parameters": {"type": "object",
                       "properties": {"timestamp": {"type": "string"}, "seconds": {"type": "number"}},
                       "required": ["timestamp", "seconds"]}}})
    return tools


# ----------------------------------------------------------------------------------------------
# cases
# ----------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class Case:
    """One seed error line and its ground truth, inside one window."""
    window_idx: int
    window_key: str
    fault: str
    seed_idx: int
    trace_id: str
    seed_service: str
    root_service: str            # service of the FIRST error line of the trace
    n_services: int
    truth: tuple[int, ...]       # indices of the OTHER lines of the trace, ascending

    @property
    def key(self) -> str:
        return f"{self.window_key}#{self.seed_idx}"


def eligible_cases(windows, min_other_lines: int = 2, min_services: int = 2,
                   exclude_services: tuple[str, ...] = ()) -> list[Case]:
    """Every ERROR line that can serve as a seed.

    The seed is the LAST error line of its trace (the symptom end), so the first error line of the
    trace is the originating one; with a single error line the two coincide. One seed per trace.
    A seed is eligible when its trace is non-trivial: at least `min_other_lines` other lines in at
    least `min_services` services (the same two conditions the model-free gate pre-registers).
    """
    out: list[Case] = []
    for wi, w in enumerate(windows):
        by_trace: dict[str, list[int]] = {}
        for i, r in enumerate(w.records):
            if r.trace_id:
                by_trace.setdefault(r.trace_id, []).append(i)
        for tid, idxs in by_trace.items():
            errs = [i for i in idxs if w.records[i].is_error]
            if not errs:
                continue
            seed = errs[-1]
            seed_svc = _service_of(w.records[seed].pod)
            if seed_svc in exclude_services:
                continue
            svcs = {_service_of(w.records[i].pod) for i in idxs}
            others = tuple(i for i in idxs if i != seed)
            if len(others) < min_other_lines or len(svcs) < min_services:
                continue
            out.append(Case(
                window_idx=wi, window_key=w.key, fault=w.fault or "normal", seed_idx=seed,
                trace_id=tid, seed_service=seed_svc,
                root_service=_service_of(w.records[errs[0]].pod),
                n_services=len(svcs), truth=others))
    out.sort(key=lambda c: (c.window_idx, c.seed_idx))
    return out


def sample_cases(eligible: list[Case], main_n: dict[str, int], pilot_n: dict[str, int],
                 seed: int) -> tuple[list[Case], list[Case]]:
    """Stratified (by fault) fixed-seed sample. PILOT and MAIN are disjoint by construction.

    Each stratum is shuffled once; the first `pilot_n` go to the pilot and the next `main_n` to the
    main run, so the main sample does not depend on whether a pilot was drawn.
    """
    rng = random.Random(seed)
    main: list[Case] = []
    pilot: list[Case] = []
    for fault in sorted(set(main_n) | set(pilot_n)):
        pool = [c for c in eligible if c.fault == fault]
        rng.shuffle(pool)
        npil, nmain = pilot_n.get(fault, 0), main_n.get(fault, 0)
        pilot += pool[:npil]
        main += pool[npil:npil + nmain]
    rng.shuffle(main)
    return main, pilot


# ----------------------------------------------------------------------------------------------
# prompt
# ----------------------------------------------------------------------------------------------
SYSTEM = (
    "You are an SRE doing per-request forensics on a microservice log window that is too large to "
    "read in full. You are given ONE log line that recorded an error. Find every OTHER log line in the "
    "window that belongs to the same end-to-end request as that line (the same user request as it "
    "passed through the services), and name the service where the failure originated. "
    "Log lines are numbered [i]; those numbers are what you report. Use the tools to navigate "
    "efficiently; a tool may reply that it is not available for this log format. "
    "{roster}"
    "When confident, reply with ONLY JSON "
    "{{\"line_indices\": [<int>, ...], \"root_service\": \"<service name>\"}} "
    "listing every other line of that request (not the given line itself), "
    "and DO NOT call a tool in that final turn."
)


def roster_text(records: list[LogRecord]) -> str:
    names = sorted({_service_of(r.pod) for r in records})
    return (f"The failure originated in exactly one of these {len(names)} services: "
            f"{', '.join(names)}. Answer root_service with one of these names verbatim. ")


def render_seed(record: LogRecord, condition: str) -> str:
    """The seed line exactly as the arm's own lines render, minus the [i] index (which is not given)."""
    svc, sev = _service_of(record.pod), record.level or "LOG"
    if condition == "structured":
        return f"svc={svc} sev={sev} trace={record.trace_id} {record.to_plain()}"
    if condition == "structured_no_trace":
        return f"svc={svc} sev={sev} {record.to_plain()}"
    if condition == "plain":
        return record.to_plain()
    raise ValueError(f"unknown condition: {condition!r}")


def user_message(repl: ForensicsREPL, record: LogRecord, condition: str) -> str:
    return (f"Window overview:\n{repl.overview()}\n\n"
            f"The error line, logged at {iso(record.time_unix_nano)}:\n"
            f"{render_seed(record, condition)}\n\n"
            "Find the other lines of the same request and the service where the failure originated.")


def _as_index(x) -> int | None:
    if isinstance(x, bool):
        return None
    if isinstance(x, int):
        return x
    if isinstance(x, float) and x.is_integer():
        return int(x)
    if isinstance(x, str) and re.fullmatch(r"\s*\[?\s*\d+\s*\]?\s*", x):
        return int(re.sub(r"[^\d]", "", x))
    return None


def parse_final(content: str) -> tuple[list[int], str] | None:
    """(line_indices, root_service) from a final turn, or None if there is no usable answer."""
    for m in re.finditer(r"\{[^{}]*\}", content or "", flags=re.DOTALL):
        try:
            obj = json.loads(m.group(0))
        except json.JSONDecodeError:
            continue
        raw = next((obj[k] for k in ("line_indices", "lines", "indices") if k in obj), None)
        if not isinstance(raw, list):
            continue
        idx = [i for i in (_as_index(x) for x in raw) if i is not None]
        root = next((str(obj[k]).strip() for k in ("root_service", "root", "origin_service",
                                                   "culprit_service") if k in obj), "")
        return sorted(set(idx)), root
    return None


# ----------------------------------------------------------------------------------------------
# scoring
# ----------------------------------------------------------------------------------------------
CORRECT_F1 = 0.8   # pre-registered threshold for "correct"


def score_lines(pred: list[int] | set[int], case: Case) -> dict:
    """Precision / recall / F1 over the OTHER lines of the request. The seed is dropped from both sides."""
    truth = set(case.truth)
    got = set(pred) - {case.seed_idx}
    tp = len(got & truth)
    p = tp / len(got) if got else 0.0
    r = tp / len(truth) if truth else 0.0
    f1 = 2 * p * r / (p + r) if (p + r) else 0.0
    return {"precision": p, "recall": r, "f1": f1, "tp": tp, "n_pred": len(got), "n_truth": len(truth)}


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(s).lower())


def root_correct(pred: str, truth: str) -> bool:
    """Exact match after alphanumeric normalisation. `unknown`/empty is never correct."""
    p = _norm(pred)
    return bool(p) and p not in ("unknown", "unsure", "none") and p == _norm(truth)


# ----------------------------------------------------------------------------------------------
# the agent loop
# ----------------------------------------------------------------------------------------------
@dataclass
class Meter:
    """Token / round counters that survive `asyncio.wait_for` cancelling the loop mid-flight."""
    in_tok: int = 0
    out_tok: int = 0
    rounds: int = 0
    gpu_s: float = 0.0
    max_prompt_tok: int = 0     # largest single-round prompt; compared against num_ctx afterwards
    tools: list[str] = field(default_factory=list)
    not_available: int = 0
    trace: list[dict] = field(default_factory=list)

    @property
    def total(self) -> int:
        return self.in_tok + self.out_tok


@dataclass
class Outcome:
    indices: list[int] | None      # None = no usable final answer
    root: str
    aborted: bool
    abort_reason: str


NOT_AVAILABLE = ("not available", "trace ids not available")


async def run_agent(client, records: list[LogRecord], condition: str, case: Case, meter: Meter,
                    max_rounds: int, max_total_tokens: int, num_ctx: int) -> Outcome:
    """The RLMMethod loop, for the forensics task, accumulating into `meter` as it goes.

    Differences from `RLMMethod.apredict`, both forced by the task: a different final-answer format,
    and counters kept in `meter` so a wall-clock timeout still reports the tokens already spent.
    """
    repl = ForensicsREPL(records, condition)
    tools = forensics_tool_schemas()
    seed = records[case.seed_idx]
    messages: list[dict] = [
        {"role": "system", "content": SYSTEM.format(roster=roster_text(records))},
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
                if result.startswith(NOT_AVAILABLE):
                    meter.not_available += 1
                meter.trace.append({"round": rnd, "tool": name, "args": args,
                                    "result_chars": len(result), "result_preview": result[:160]})
                messages.append({"role": "tool", "tool_name": name, "content": result})
            if meter.total > max_total_tokens:
                return Outcome(None, "", True, "token_ceiling")
            continue

        final = parse_final(resp.content)
        meter.trace.append({"round": rnd, "final": (resp.content or "")[:300]})
        if final:
            return Outcome(final[0], final[1], False, "")
        messages.append({"role": "assistant", "content": resp.content or ""})
        messages.append({"role": "user", "content":
                         'Give your final answer as JSON {"line_indices": [...], "root_service": "..."}.'})
    return Outcome(None, "", True, "max_rounds")
