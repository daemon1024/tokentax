"""REPL helpers the RLM root model calls to navigate a large window WITHOUT reading it all.

Two toolsets:
  trace-blind (plain condition):   overview, grep, peek           -> must correlate by content
  trace-aware (structured cond.):  + extract_trace_ids, lines_for_trace  <- the punchline

Every helper returns a short string the root model reads; the point is that the sum of those
strings is far smaller than the whole window. Token accounting (in rlm.py) counts exactly those.
"""

from __future__ import annotations

import re

from tokentax.nezha import LogRecord, _service_of


class LogREPL:
    def __init__(self, records: list[LogRecord], trace_aware: bool):
        self.records = records
        self.trace_aware = trace_aware
        # Condition-aware lines so "plain" is genuinely plain: in the plain (trace-blind) condition
        # the searchable line is ONLY the message body — no service/severity prefix — so the model
        # must infer the culprit from content. In the structured condition the OTLP fields
        # (service.name, severity, trace_id) are exposed as queryable tags, like real structured logs.
        if trace_aware:
            self.lines = [f"[{i}] svc={r.pod} sev={r.level or 'LOG'} trace={r.trace_id[:8]} {r.to_plain()}"
                          for i, r in enumerate(records)]
        else:
            self.lines = [f"[{i}] {r.to_plain()}" for i, r in enumerate(records)]
        self._by_trace: dict[str, list[int]] = {}
        for i, r in enumerate(records):
            if r.trace_id:
                self._by_trace.setdefault(r.trace_id, []).append(i)

    # --- always available ---
    def overview(self) -> str:
        services = sorted({_service_of(r.pod) for r in self.records})
        sev: dict[str, int] = {}
        for r in self.records:
            sev[r.level or "LOG"] = sev.get(r.level or "LOG", 0) + 1
        out = [
            f"window: {len(self.records)} log lines, {len(services)} services.",
            f"severity counts: {sev}",
            f"services: {', '.join(services)}",
        ]
        if self.trace_aware:
            out.append(f"distinct trace_ids: {len(self._by_trace)} "
                       f"(use extract_trace_ids / lines_for_trace).")
        else:
            out.append("no trace ids available; navigate by content with grep/peek.")
        return "\n".join(out)

    def grep(self, pattern: str, max_matches: int = 25) -> str:
        try:
            rx = re.compile(pattern, re.IGNORECASE)
        except re.error as e:
            return f"bad regex: {e}"
        hits = [ln for ln in self.lines if rx.search(ln)]
        head = hits[:max_matches]
        more = f"\n... (+{len(hits) - len(head)} more matches)" if len(hits) > len(head) else ""
        return (f"{len(hits)} matches for /{pattern}/:\n" + "\n".join(head) + more) if hits \
            else f"no matches for /{pattern}/"

    def peek(self, start: int, end: int) -> str:
        start = max(0, start)
        end = min(len(self.lines), end)
        return "\n".join(self.lines[start:end]) or "(empty range)"

    # --- trace-aware only ---
    def extract_trace_ids(self, only_with_errors: bool = False, limit: int = 40) -> str:
        if not self.trace_aware:
            return "trace ids not available in this condition."
        items = []
        for tid, idxs in self._by_trace.items():
            n_err = sum(1 for i in idxs if self.records[i].is_error)
            if only_with_errors and n_err == 0:
                continue
            pods = sorted({self.records[i].pod for i in idxs})
            items.append((tid, len(idxs), n_err, pods))
        items.sort(key=lambda x: -x[2])  # most errors first
        head = items[:limit]
        lines = [f"{t} lines={n} errors={e} pods={','.join(_service_of(p) for p in pods)}"
                 for t, n, e, pods in head]
        return (f"{len(items)} trace_ids"
                f"{' with errors' if only_with_errors else ''} (showing {len(head)}):\n"
                + "\n".join(lines))

    def lines_for_trace(self, trace_id: str) -> str:
        if not self.trace_aware:
            return "trace ids not available in this condition."
        idxs = self._by_trace.get(trace_id.strip())
        if not idxs:
            return f"no lines for trace {trace_id}"
        return "\n".join(self.lines[i] for i in idxs)

    # --- dispatch for the orchestrator ---
    def call(self, name: str, args: dict) -> str:
        # small models often emit slightly-wrong arg names (e.g. 'search' for 'pattern'),
        # so accept common aliases rather than failing the tool call.
        def arg(*keys, default=""):
            for k in keys:
                if k in args and args[k] not in (None, ""):
                    return args[k]
            return default
        try:
            if name == "overview":
                return self.overview()
            if name == "grep":
                return self.grep(str(arg("pattern", "search", "query", "q", "regex", "term")),
                                 int(arg("max_matches", "limit", "max", default=25)))
            if name == "peek":
                return self.peek(int(arg("start", "from", "begin", default=0)),
                                 int(arg("end", "to", "stop", default=0)))
            if name == "extract_trace_ids":
                return self.extract_trace_ids(
                    bool(arg("only_with_errors", "errors_only", "errors", default=False)),
                    int(arg("limit", "max", default=40)))
            if name == "lines_for_trace":
                return self.lines_for_trace(str(arg("trace_id", "traceId", "id", "trace")))
        except (ValueError, TypeError, KeyError) as e:
            return f"tool error in {name}: {e}"
        return f"unknown tool: {name}"


def tool_schemas(trace_aware: bool) -> list[dict]:
    """Ollama tool schemas for the available REPL helpers."""
    def fn(name, desc, props, required):
        return {"type": "function", "function": {
            "name": name, "description": desc,
            "parameters": {"type": "object", "properties": props, "required": required}}}

    tools = [
        fn("overview", "Summarize the window: line count, services, severity counts. Call this first.",
           {}, []),
        fn("grep", "Search log lines by case-insensitive regex; returns matching lines with indices.",
           {"pattern": {"type": "string"}, "max_matches": {"type": "integer"}}, ["pattern"]),
        fn("peek", "Return log lines in the index range [start, end).",
           {"start": {"type": "integer"}, "end": {"type": "integer"}}, ["start", "end"]),
    ]
    if trace_aware:
        tools += [
            fn("extract_trace_ids",
               "List trace_ids with their line/error counts and services (most errors first).",
               {"only_with_errors": {"type": "boolean"}, "limit": {"type": "integer"}}, []),
            fn("lines_for_trace", "Return all log lines belonging to one trace_id.",
               {"trace_id": {"type": "string"}}, ["trace_id"]),
        ]
    return tools
