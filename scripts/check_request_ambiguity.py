"""Can trace context possibly pay? A no-model pre-check, run BEFORE any cell is spent.

THE ARGUMENT. Per-request forensics starts from one edge error line and asks which lines belong to
that request. `trace_id` answers it by lookup. Without it you must guess from a time window. So the
saving is bounded by how many OTHER requests are in flight at that moment — if one request is in
flight, the time window IS the request and trace context buys nothing at any window size.

THE METRIC. For each ERROR record at the edge service:

    concurrent_requests = |{ distinct traceId among records within +/-W of it }|
    trace_services      = |{ distinct service among records sharing its traceId }|

`concurrent_requests` is the primary figure and the kill variable. It is bounded by in-flight
requests, so unlike a line-count ratio it CANNOT be inflated by a chatty service: a hundred log
lines from one request still count as one request. An earlier version of this check divided lines-
in-window by lines-in-trace, which measured log volume and W, not ambiguity, and could not fail.

`trace_services` guards the other end: if the erroring request only ever touched one service, the
trace arm has nothing to read even when the lookup is free.

KILL CRITERION, pre-registered, conjunctive. PROCEED only if, at the highest load level,
    median(concurrent_requests) >= 5     AND     median(trace_services) >= 2
Otherwise STOP: trace context cannot pay for itself on this workload and no model will change that.

W is not a single pre-registered value because the verdict moves with it. Every report prints a
sweep (0.05 / 0.25 / 1 / 2 / 5 / 30 s) so the knob is visible, and the headline uses --window.

Usage:
    .venv/bin/python scripts/check_request_ambiguity.py --selftest
    .venv/bin/python scripts/check_request_ambiguity.py --logs captured/logs.jsonl
    .venv/bin/python scripts/check_request_ambiguity.py --logs a.jsonl --load-level high --json out.json
"""

from __future__ import annotations

import argparse
import json
import statistics as st
import sys
from collections import defaultdict
from pathlib import Path

W_SWEEP = (0.05, 0.25, 1.0, 2.0, 5.0, 30.0)
MIN_CONCURRENT = 5.0      # pre-registered
MIN_SERVICES = 2.0        # pre-registered
MIN_EDGE_ERRORS = 30      # below this a level is INDETERMINATE, not PASS/FAIL

# OTLP timeUnixNano for any plausible capture date sits in this band. A capture in ms or s would be
# ~1e12 / ~1e9 and would silently make every window wrong by 10^3..10^9, which is exactly the class
# of bug that produces a confident wrong verdict.
NS_LO, NS_HI = 1.0e18, 2.0e18


def _attrs(lst):
    out = {}
    for a in lst or []:
        v = a.get("value", {}) or {}
        out[a.get("key")] = (v.get("stringValue") or v.get("intValue")
                             or v.get("boolValue") or v.get("doubleValue"))
    return out


def _body(rec) -> str:
    """Log body. `stringValue` is the common case; kvlistValue occurs and must not read as empty."""
    b = rec.get("body", {}) or {}
    if "stringValue" in b:
        return str(b["stringValue"])
    if "kvlistValue" in b:
        kv = _attrs((b["kvlistValue"] or {}).get("values", []))
        return " ".join(f"{k}={v}" for k, v in kv.items())
    return ""


def read_records(path: Path) -> list[dict]:
    """Parse OTLP-JSON logs written by the collector's file exporter (one object per line)."""
    recs = []
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                doc = json.loads(line)
            except json.JSONDecodeError:
                continue
            for rl in doc.get("resourceLogs", []):
                res = _attrs(rl.get("resource", {}).get("attributes", []))
                svc = str(res.get("service.name", "") or "")
                for sl in rl.get("scopeLogs", []):
                    for r in sl.get("logRecords", []):
                        try:
                            ts = int(r.get("timeUnixNano") or r.get("observedTimeUnixNano") or 0)
                        except (TypeError, ValueError):
                            ts = 0
                        recs.append({
                            "ts": ts or None,
                            "svc": svc,
                            "trace": str(r.get("traceId", "") or ""),
                            "sev": int(r.get("severityNumber") or 0),
                            "sevtext": str(r.get("severityText", "") or "").upper(),
                            "body": _body(r),
                        })
    return recs


def is_error(r) -> bool:
    if r["sev"] >= 17:
        return True
    return r["sev"] == 0 and r["sevtext"] in ("ERROR", "FATAL", "CRITICAL", "SEVERE")


def check_units(recs) -> tuple[bool, str]:
    ts = sorted(r["ts"] for r in recs if r["ts"])
    if not ts:
        return False, "no record carries a timestamp"
    med = ts[len(ts) // 2]
    if not (NS_LO <= med <= NS_HI):
        return False, (f"median timestamp {med} is outside the nanosecond band "
                       f"[{NS_LO:.0e},{NS_HI:.0e}] — units are probably not ns; every window "
                       f"would be wrong by orders of magnitude")
    span = (ts[-1] - ts[0]) / 1e9
    return True, f"timestamps look like ns; capture spans {span:,.1f}s ({len(ts):,} stamped records)"


def analyse(recs, w: float, edge: str) -> dict:
    timed = sorted((r for r in recs if r["ts"]), key=lambda r: r["ts"])
    by_trace = defaultdict(list)
    for r in timed:
        if r["trace"]:
            by_trace[r["trace"]].append(r)

    errs = [r for r in timed if is_error(r) and (not edge or r["svc"] == edge)]
    untraced = sum(1 for r in errs if not r["trace"])
    usable = [r for r in errs if r["trace"]]

    conc, nsvc, single = [], [], 0
    win = int(w * 1e9)
    for e in usable:
        lo, hi = e["ts"] - win, e["ts"] + win
        # distinct requests in flight around this error — the quantity that bounds the saving
        conc.append(len({r["trace"] for r in timed if r["trace"] and lo <= r["ts"] <= hi}))
        svcs = {r["svc"] for r in by_trace.get(e["trace"], ())}
        nsvc.append(len(svcs))
        if len(svcs) <= 1:
            single += 1

    def q(v, f):
        return f(v) if v else 0.0

    return {
        "window_s": w,
        "edge_service": edge,
        "edge_errors": len(errs),
        "edge_errors_untraced": untraced,
        "usable": len(usable),
        "median_concurrent_requests": q(conc, st.median),
        "p25_concurrent": q(sorted(conc), lambda v: v[len(v) // 4]) if conc else 0,
        "max_concurrent": max(conc) if conc else 0,
        "median_trace_services": q(nsvc, st.median),
        "single_service_traces": single,
        "single_service_frac": (single / len(usable)) if usable else 0.0,
        "distinct_traces": len(by_trace),
        "records": len(recs),
    }


def verdict(a: dict) -> tuple[str, str]:
    if a["usable"] < MIN_EDGE_ERRORS:
        return "INDETERMINATE", (f"only {a['usable']} usable edge errors "
                                 f"(need >={MIN_EDGE_ERRORS}); drive more load or run longer")
    if a["median_concurrent_requests"] < MIN_CONCURRENT:
        return "STOP", (f"median {a['median_concurrent_requests']:.1f} concurrent requests "
                        f"< {MIN_CONCURRENT}: the time window IS effectively the request, so "
                        f"trace_id has nothing to disambiguate")
    if a["median_trace_services"] < MIN_SERVICES:
        return "STOP", (f"median {a['median_trace_services']:.1f} services per erroring trace "
                        f"< {MIN_SERVICES}: the trace arm has no cross-service evidence to read")
    return "PROCEED", (f"median {a['median_concurrent_requests']:.1f} concurrent requests and "
                       f"{a['median_trace_services']:.1f} services per erroring trace")


def selftest() -> int:
    """Synthetic OTLP fixtures with known-correct answers. No cluster, no capture."""
    base = 1_750_000_000_000_000_000  # in the ns band

    def rec(t_off_s, svc, trace, sev=9):
        return {"ts": base + int(t_off_s * 1e9), "svc": svc, "trace": trace,
                "sev": sev, "sevtext": "", "body": "x"}

    # A: 1 erroring request, 3 services, and 20 chatty INFO lines from the SAME request.
    # A line-count ratio would call this hugely ambiguous. Concurrency says 1 — correct.
    A = [rec(0, "api-gateway", "t1", 17), rec(0.01, "product-catalog", "t1"),
         rec(0.02, "recommendation", "t1")] + [rec(0.03 + i * 0.001, "api-gateway", "t1")
                                               for i in range(20)]
    a = analyse(A, 2.0, "api-gateway")
    assert a["median_concurrent_requests"] == 1, a
    assert a["median_trace_services"] == 3, a
    assert verdict(a)[0] == "INDETERMINATE", verdict(a)   # only 1 edge error
    assert "chatter cannot inflate" or True

    # B: 40 erroring requests, 8 concurrent, 3 services each -> PROCEED
    B = []
    for i in range(40):
        t = i * 0.1
        tid = f"b{i}"
        B += [rec(t, "api-gateway", tid, 17), rec(t + .01, "product-catalog", tid),
              rec(t + .02, "recommendation", tid)]
    b = analyse(B, 0.25, "api-gateway")
    assert b["usable"] == 40, b
    assert b["median_concurrent_requests"] >= 5, b
    assert verdict(b)[0] == "PROCEED", verdict(b)

    # C: same 40 requests but each touches ONE service -> STOP on trace_services
    C = []
    for i in range(40):
        C += [rec(i * 0.1, "api-gateway", f"c{i}", 17), rec(i * 0.1 + .01, "api-gateway", f"c{i}")]
    c = analyse(C, 0.25, "api-gateway")
    assert c["median_trace_services"] == 1, c
    assert verdict(c)[0] == "STOP", verdict(c)

    # D: serial requests, nothing concurrent -> STOP even with 3 services each
    D = []
    for i in range(40):
        t = i * 60.0
        D += [rec(t, "api-gateway", f"d{i}", 17), rec(t + .01, "product-catalog", f"d{i}"),
              rec(t + .02, "recommendation", f"d{i}")]
    d = analyse(D, 2.0, "api-gateway")
    assert d["median_concurrent_requests"] == 1, d
    assert verdict(d)[0] == "STOP", verdict(d)

    # E: unit guard must reject a millisecond capture
    ok, msg = check_units([{"ts": 1_750_000_000_000}])
    assert not ok, msg
    ok2, _ = check_units([{"ts": base}])
    assert ok2

    # F: untraced edge errors are counted, never silently dropped
    F = [rec(0, "api-gateway", "", 17), rec(1, "api-gateway", "f1", 17),
         rec(1.01, "product-catalog", "f1")]
    f = analyse(F, 2.0, "api-gateway")
    assert f["edge_errors"] == 2 and f["edge_errors_untraced"] == 1 and f["usable"] == 1, f

    print("selftest OK — chatter-immunity, proceed, single-service stop, serial stop, "
          "unit guard, untraced accounting")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--logs")
    ap.add_argument("--edge-service", default="api-gateway")
    ap.add_argument("--window", type=float, default=2.0)
    ap.add_argument("--load-level", default="unspecified")
    ap.add_argument("--json", default="")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()

    if a.selftest:
        return selftest()
    if not a.logs:
        print("need --logs PATH (or --selftest)", file=sys.stderr)
        return 2
    p = Path(a.logs)
    if not p.exists():
        print(f"missing {p}", file=sys.stderr)
        return 2

    recs = read_records(p)
    if not recs:
        print("no OTLP log records parsed — is this the collector file-exporter output?",
              file=sys.stderr)
        return 1
    ok, umsg = check_units(recs)
    print(f"units: {umsg}")
    if not ok:
        print("VERDICT: INDETERMINATE (timestamp units unsafe)")
        return 1

    print(f"\nW sweep (edge={a.edge_service}, load={a.load_level}) — the verdict moves with W, "
          f"so the knob is shown:")
    print(f"  {'W(s)':>7}{'usable':>8}{'med concurrent':>16}{'med services':>14}{'single-svc':>12}")
    sweep = []
    for w in W_SWEEP:
        s = analyse(recs, w, a.edge_service)
        sweep.append(s)
        print(f"  {w:>7.2f}{s['usable']:>8}{s['median_concurrent_requests']:>16.1f}"
              f"{s['median_trace_services']:>14.1f}{s['single_service_frac']:>11.0%}")

    head = analyse(recs, a.window, a.edge_service)
    v, why = verdict(head)
    print(f"\nedge errors {head['edge_errors']} ({head['edge_errors_untraced']} with EMPTY traceId "
          f"— unusable, reported not dropped)")
    print(f"distinct traces in capture: {head['distinct_traces']:,}   records: {head['records']:,}")
    print(f"\nVERDICT @W={a.window}s: {v} — {why}")
    print(f"  criterion: median_concurrent >= {MIN_CONCURRENT} AND median_services >= "
          f"{MIN_SERVICES}, with >= {MIN_EDGE_ERRORS} usable edge errors")

    if a.json:
        Path(a.json).parent.mkdir(parents=True, exist_ok=True)
        Path(a.json).write_text(json.dumps(
            {"load_level": a.load_level, "headline": head, "sweep": sweep,
             "verdict": v, "why": why}, indent=1))
        print(f"wrote {a.json}")
    return 0 if v == "PROCEED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
