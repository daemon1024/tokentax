"""Run the pre-registered request-ambiguity gate on MANIFEST WINDOWS instead of a whole capture.

`check_request_ambiguity.py` measures concurrency over an entire capture. The experiment, though, hands a
model one 75-second window at a time, so the ambiguity that matters is what is visible INSIDE a window.
This wrapper changes nothing about the gate's logic: it imports `read_records`, `analyse` and `verdict`
unchanged and only decides which records each call sees.

Isolation trick. Windows are concatenated into one record list so the gate's own `analyse` can be reused
verbatim, but each window's timestamps are shifted by `idx * 1e13` ns (10,000 s) and its trace ids are
prefixed with `idx:`. A request that straddles a window boundary is therefore SPLIT, exactly as the model
would see it, and neighbouring windows cannot lend each other concurrency.

Usage:
    .venv/bin/python scripts/check_request_ambiguity_windows.py \
        --logs data/otel_demo/logs.jsonl --manifest data/otel_demo/manifest_multifault.json \
        --edge-service frontend --edge-service frontend-proxy --edge-service "" \
        --json results/runs/gate/otel_demo_multifault_windows.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import check_request_ambiguity as gate  # noqa: E402

SHIFT_NS = 10_000_000_000_000  # 1e13 ns = 10,000 s between windows; far above any window or W


def slice_windows(recs: list[dict], manifest: list[dict]) -> list[dict]:
    """Records inside each manifest window, isolated from every other window (see module doc)."""
    stamped = sorted((r for r in recs if r["ts"]), key=lambda r: r["ts"])
    out: list[dict] = []
    for idx, m in enumerate(manifest):
        s, e = int(m["start_ns"]), int(m["end_ns"])
        for r in stamped:
            if s <= r["ts"] <= e:
                out.append({**r, "ts": r["ts"] - s + idx * SHIFT_NS + SHIFT_NS,
                            "trace": f"{idx}:{r['trace']}" if r["trace"] else ""})
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--logs", required=True)
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--edge-service", action="append", default=None,
                    help="repeatable; '' means every service")
    ap.add_argument("--window", type=float, default=2.0, help="headline W for the verdict")
    ap.add_argument("--json", default="")
    a = ap.parse_args()

    manifest = json.loads(Path(a.manifest).read_text())
    recs = gate.read_records(Path(a.logs))
    ok, msg = gate.check_units(recs)
    print(f"units: {msg}")
    if not ok:
        print("VERDICT: INDETERMINATE (timestamp units unsafe)")
        return 1
    win = slice_windows(recs, manifest)
    print(f"{len(manifest)} windows, {len(win):,} records inside them (of {len(recs):,})")

    report = []
    for edge in (a.edge_service if a.edge_service is not None else [""]):
        print(f"\nedge={edge or '(all services)'}")
        print(f"  {'W(s)':>7}{'usable':>8}{'med concurrent':>16}{'med services':>14}{'single-svc':>12}")
        sweep = []
        for w in gate.W_SWEEP:
            s = gate.analyse(win, w, edge)
            sweep.append(s)
            print(f"  {w:>7.2f}{s['usable']:>8}{s['median_concurrent_requests']:>16.1f}"
                  f"{s['median_trace_services']:>14.1f}{s['single_service_frac']:>11.0%}")
        head = gate.analyse(win, a.window, edge)
        v, why = gate.verdict(head)
        print(f"  edge errors {head['edge_errors']} ({head['edge_errors_untraced']} untraced)")
        print(f"  VERDICT @W={a.window}s: {v} - {why}")
        report.append({"edge_service": edge or "(all)", "headline": head, "sweep": sweep,
                       "verdict": v, "why": why})

    if a.json:
        Path(a.json).parent.mkdir(parents=True, exist_ok=True)
        Path(a.json).write_text(json.dumps({"manifest": a.manifest, "windows": len(manifest),
                                            "records_in_windows": len(win), "results": report}, indent=1))
        print(f"\nwrote {a.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
