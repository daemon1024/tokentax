"""REPL helpers the RLM root model calls to navigate a large window WITHOUT reading it all.

THREE conditions, with MATCHED aggregation power (see WITHDRAWAL.md for why this matters):

  plain                body only. Tools: overview, grep, peek, errors_by_cluster
  structured_no_trace  + service.name + severity. Tools: the above + errors_by_service
  structured           + trace_id.    Tools: the above + extract_trace_ids, lines_for_trace

The 2026-06 runs gave an ERROR-count digest to the structured arm ONLY, so the measured "structure
advantage" was a tool advantage. Every condition now gets the best aggregator computable from the data
it can actually see: `errors_by_cluster` (Drain templates over message bodies) needs no fields at all,
so the plain arm is no longer handicapped. Any residual gap is attributable to structure.

Contrasts this supports:
  plain vs structured_no_trace   -> what does `service.name` buy?
  structured_no_trace vs structured -> what does `trace_id` buy, holding service+severity constant?

Every helper returns a short string the root model reads; the point is that the sum of those strings
is far smaller than the whole window. Token accounting (in rlm.py) counts exactly those.
"""

from __future__ import annotations

import re

from tokentax.methods.drain import _make_miner, _normalize
from tokentax.nezha import LogRecord, _service_of

CONDITIONS = ("plain", "structured_no_trace", "structured")


class LogREPL:
    def __init__(self, records: list[LogRecord], trace_aware: bool | None = None,
                 condition: str | None = None):
        """Pass `condition`; `trace_aware` is kept as a back-compatible alias.

        trace_aware=True  -> 'structured'   (all fields)
        trace_aware=False -> 'plain'        (no fields)
        """
        if condition is None:
            if trace_aware is None:
                raise ValueError("pass condition= (or the legacy trace_aware=)")
            condition = "structured" if trace_aware else "plain"
        if condition not in CONDITIONS:
            raise ValueError(f"unknown condition: {condition!r}; expected one of {CONDITIONS}")

        self.records = records
        self.condition = condition
        self.has_fields = condition in ("structured", "structured_no_trace")
        self.trace_aware = condition == "structured"

        # Condition-aware searchable lines. 'plain' is genuinely plain — body only, so the model must
        # infer the culprit from content. The structured variants expose OTLP fields as queryable tags.
        if self.condition == "structured":
            self.lines = [f"[{i}] svc={_service_of(r.pod)} sev={r.level or 'LOG'} "
                          f"trace={r.trace_id[:8]} {r.to_plain()}"
                          for i, r in enumerate(records)]
        elif self.condition == "structured_no_trace":
            self.lines = [f"[{i}] svc={_service_of(r.pod)} sev={r.level or 'LOG'} {r.to_plain()}"
                          for i, r in enumerate(records)]
        else:
            self.lines = [f"[{i}] {r.to_plain()}" for i, r in enumerate(records)]

        self._by_trace: dict[str, list[int]] = {}
        for i, r in enumerate(records):
            if r.trace_id:
                self._by_trace.setdefault(r.trace_id, []).append(i)
        self._cluster_cache: str | None = None

    # --- always available ---
    def overview(self) -> str:
        sev: dict[str, int] = {}
        for r in self.records:
            sev[r.level or "LOG"] = sev.get(r.level or "LOG", 0) + 1
        out = [f"window: {len(self.records)} log lines.", f"severity counts: {sev}"]
        # The service roster is a structured field. Leaking it in the plain condition (as the 2026-06
        # code did) hands the plain arm the candidate answer set for free.
        if self.has_fields:
            services = sorted({_service_of(r.pod) for r in self.records})
            out.append(f"{len(services)} services: {', '.join(services)}")
        else:
            out.append("no service field in this condition; navigate by content with "
                       "grep/peek/errors_by_cluster.")
        if self.trace_aware:
            out.append(f"distinct trace_ids: {len(self._by_trace)} "
                       f"(use extract_trace_ids / lines_for_trace).")
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

    def errors_by_cluster(self, limit: int = 10) -> str:
        """Compact digest: ERROR lines grouped into Drain message-templates, ranked by count.

        The plain arm's matched-power aggregator — needs no fields, only message bodies, so it is
        available in EVERY condition. This is the control that makes `errors_by_service` interpretable:
        if structure adds nothing over text clustering, the two digests localise equally well.
        """
        if self._cluster_cache is not None:
            return self._cluster_cache
        miner = _make_miner()
        counts: dict[str, int] = {}
        for r in self.records:
            if r.is_error:
                res = miner.add_log_message(_normalize(r.to_plain()))
                tmpl = res["template_mined"]
                counts[tmpl] = counts.get(tmpl, 0) + 1
        if not counts:
            self._cluster_cache = "no errors in window."
            return self._cluster_cache
        ranked = sorted(counts.items(), key=lambda kv: -kv[1])[:limit]
        body = "\n".join(f"{n}x  {t[:160]}" for t, n in ranked)
        self._cluster_cache = f"ERROR message-templates (most first, {len(counts)} distinct):\n{body}"
        return self._cluster_cache

    # --- needs service.name (structured + structured_no_trace) ---
    def errors_by_service(self) -> str:
        """Compact digest: ERROR-record count per service, ranked. Requires the service.name field."""
        if not self.has_fields:
            return "not available: plain logs have no service field to aggregate by."
        counts: dict[str, int] = {}
        for r in self.records:
            if r.is_error:
                counts[_service_of(r.pod)] = counts.get(_service_of(r.pod), 0) + 1
        if not counts:
            return "no errors in window."
        ranked = sorted(counts.items(), key=lambda kv: -kv[1])
        return "ERROR counts by service (most first): " + ", ".join(f"{s}={n}" for s, n in ranked)

    # --- needs trace_id (structured only) ---
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
            if name == "errors_by_cluster":
                return self.errors_by_cluster(int(arg("limit", "max", default=10)))
            if name == "errors_by_service":
                return self.errors_by_service()
            if name == "extract_trace_ids":
                return self.extract_trace_ids(
                    bool(arg("only_with_errors", "errors_only", "errors", default=False)),
                    int(arg("limit", "max", default=40)))
            if name == "lines_for_trace":
                return self.lines_for_trace(str(arg("trace_id", "traceId", "id", "trace")))
        except (ValueError, TypeError, KeyError) as e:
            return f"tool error in {name}: {e}"
        return f"unknown tool: {name}"


def tool_schemas(trace_aware: bool | None = None, condition: str | None = None,
                 matched_schemas: bool = False) -> list[dict]:
    """Ollama tool schemas for the available REPL helpers.

    Descriptions are deliberately PARALLEL across conditions: each arm's aggregator is described in the
    same neutral terms ("compact digest ... ranked by ERROR count"). The 2026-06 code told the structured
    arm its digest was "the cheapest way to localize a fault - call this first" and told the plain arm
    nothing, which is prompt-level steering on top of the tool-level advantage.
    """
    if condition is None:
        if trace_aware is None:
            raise ValueError("pass condition= (or the legacy trace_aware=)")
        condition = "structured" if trace_aware else "plain"
    has_fields = condition in ("structured", "structured_no_trace")

    # matched_schemas: declare the SAME tool set in every arm, so the per-request schema cost is
    # identical and the only thing that varies is the DATA. Without this, `structured` carries two
    # extra tool definitions (459 vs 320 tok/request) -- ~139 tok x ~3 rounds ~= 417 tok, which
    # accounted for essentially all of the "trace_id costs 20% more" effect first measured. Tools
    # whose backing field is absent already return an explicit "not available" string, so declaring
    # them everywhere is safe.
    if matched_schemas:
        has_fields = True
        condition = "structured"

    def fn(name, desc, props, required):
        return {"type": "function", "function": {
            "name": name, "description": desc,
            "parameters": {"type": "object", "properties": props, "required": required}}}

    tools = [
        fn("overview", "Summarize the window: line count and severity counts. Call this first.",
           {}, []),
        fn("grep", "Search log lines by case-insensitive regex; returns matching lines with indices.",
           {"pattern": {"type": "string"}, "max_matches": {"type": "integer"}}, ["pattern"]),
        fn("peek", "Return log lines in the index range [start, end).",
           {"start": {"type": "integer"}, "end": {"type": "integer"}}, ["start", "end"]),
        fn("errors_by_cluster",
           "Compact digest: ERROR lines grouped into message-templates, ranked by count.",
           {"limit": {"type": "integer"}}, []),
    ]
    if has_fields:
        tools.append(fn("errors_by_service",
                        "Compact digest: ERROR lines grouped by service, ranked by count.",
                        {}, []))
    if condition == "structured":
        tools += [
            fn("extract_trace_ids",
               "List trace_ids with their line/error counts and services (most errors first).",
               {"only_with_errors": {"type": "boolean"}, "limit": {"type": "integer"}}, []),
            fn("lines_for_trace", "Return all log lines belonging to one trace_id.",
               {"trace_id": {"type": "string"}}, ["trace_id"]),
        ]
    return tools
