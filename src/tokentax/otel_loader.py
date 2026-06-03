"""Load captured OTel Demo OTLP-JSON LogRecords into the benchmark's LogRecord/Window model.

The collector's file exporter writes one JSON object per line:
  {"resourceLogs":[{"resource":{"attributes":[...]},"scopeLogs":[{"logRecords":[{...}]}]}]}
Each logRecord has timeUnixNano, severityNumber/Text, body.stringValue, traceId, spanId, attributes.

We map these onto `tokentax.nezha.LogRecord` (pod = service.name) so the existing windowizer,
condition variants, methods, and Drain all work unchanged across both data sources.
"""

from __future__ import annotations

import json
from pathlib import Path

from tokentax.nezha import LogRecord


def _sev(num: int, text: str) -> str:
    if num >= 21:
        return "FATAL"
    if num >= 17:
        return "ERROR"
    if num >= 13:
        return "WARN"
    if num >= 9:
        return "INFO"
    if num >= 1:
        return "DEBUG"
    t = (text or "").upper()
    return {"INFORMATION": "INFO", "WARNING": "WARN", "ERR": "ERROR"}.get(t, t)


def _attr_val(v: dict):
    if "stringValue" in v:
        return v["stringValue"]
    if "intValue" in v:
        return v["intValue"]
    if "boolValue" in v:
        return v["boolValue"]
    if "doubleValue" in v:
        return v["doubleValue"]
    return None


def _attrs(attr_list: list[dict]) -> dict:
    return {a["key"]: _attr_val(a.get("value", {})) for a in attr_list or []}


def parse_otlp_jsonl(path: str | Path) -> list[LogRecord]:
    out: list[LogRecord] = []
    for line in open(path, encoding="utf-8", errors="replace"):
        line = line.strip()
        if not line:
            continue
        try:
            doc = json.loads(line)
        except json.JSONDecodeError:
            continue
        for rl in doc.get("resourceLogs", []):
            res = _attrs(rl.get("resource", {}).get("attributes", []))
            service = str(res.get("service.name", "unknown"))
            for sl in rl.get("scopeLogs", []):
                for lr in sl.get("logRecords", []):
                    a = _attrs(lr.get("attributes", []))
                    body = (lr.get("body", {}) or {}).get("stringValue", "") or ""
                    # fold string-ish attributes into the message so methods see the detail
                    extra = " ".join(f"{k}={v}" for k, v in a.items()
                                     if v is not None and not str(k).startswith(("telemetry.", "process.")))
                    message = (body + (" " + extra if extra else "")).strip()
                    try:
                        tun = int(lr.get("timeUnixNano") or lr.get("observedTimeUnixNano") or 0)
                    except (ValueError, TypeError):
                        tun = 0
                    out.append(LogRecord(
                        time_unix_nano=tun,
                        node=str(res.get("k8s.node.name", "")),
                        pod=service,           # service.name plays the role of pod/component
                        container=service,
                        trace_id=str(lr.get("traceId", "") or ""),
                        span_id=str(lr.get("spanId", "") or ""),
                        message=message,
                        level=_sev(int(lr.get("severityNumber", 0) or 0), lr.get("severityText", "")),
                        parse_fail=False,
                    ))
    return out
