"""Tabulate every rca-lab gate result (results/runs/rcalab_gate/*.json) as markdown. No model, no network.

    .venv/bin/python scripts/rcalab_gate_summary.py [--regen]

--regen re-runs scripts/rcalab_gate.py for every verified capture in the manifest first.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GATES = ROOT / "results/runs/rcalab_gate"
MANIFEST = ROOT / "results/datasets/rcalab_manifest.json"


def regen() -> None:
    m = json.loads(MANIFEST.read_text())
    for e in m["captures"]:
        if e.get("status") != "ok" or e["scenario"] == "healthy" or not e.get("windows", {}).get("baseline"):
            continue
        d = ROOT / e["path"]
        if not (d / "meta_raw.json").exists() and not (d / "meta.json").exists():
            continue
        r = subprocess.run([sys.executable, str(ROOT / "scripts/rcalab_gate.py"), str(d),
                            "--json", str(GATES / f"{e['name']}.json")], capture_output=True, text=True)
        print(f"{e['name']}: {'ok' if r.returncode == 0 else 'FAILED ' + r.stderr[-200:]}", file=sys.stderr)


def row(g: dict) -> str:
    fl, bl = g["fault_logs"], g["baseline_logs"]
    lr, am = g["log_reach"], g["argmax"]
    fs, bs = g.get("fault_spans", {}), g.get("baseline_spans", {})
    amb = {x["W"]: x for x in g["ambiguity"]["all_services"]}
    v = g["verdict"]
    p99 = (f"{bs.get('slow_ms', 0):,.0f} -> slow traces {bs.get('slow_traces', '—')} vs "
           f"{fs.get('slow_traces', '—')}") if fs else "—"
    return (f"| {g.get('capture', g['scenario'])} | {g['culprit']} | {bl['error_per_min']} | {fl['error_per_min']} | "
            f"{fl['error_records']} | {fl['records_with_trace']}/{fl['records']} | "
            f"{am['top'] or '—'}{' (tie)' if am['tied'] else ''} {'✓' if am['strictly_correct'] else '✗'} | "
            f"{lr['culprit_log_records']} | {lr['reach_traces']}/{lr['foreign_erroring_traces']} | "
            f"{fs.get('error_traces_reaching_culprit', '—')}/{fs.get('error_traces', '—')} | "
            f"{amb[2.0]['median_concurrent']:.0f} / {amb[2.0]['median_services']:.0f} | "
            f"{g['tokens_fault_window']['repl_lines_plain']:,} | {p99} | "
            f"{'PASS' if v['WS'] else 'fail'} | {'PASS' if v['S3'] else 'fail'} | {'PASS' if v['PR'] else 'fail'} |")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--regen", action="store_true")
    a = ap.parse_args()
    if a.regen:
        regen()
    rows = [json.loads(p.read_text()) for p in sorted(GATES.glob("*.json"))]
    print("| capture | culprit (truth) | ERROR/min baseline | ERROR/min fault | ERROR in fault | "
          "records with trace_id | argmax(errors_by_service) | culprit's own log records | "
          "culprit reached from foreign error traces, LOGS | error traces reaching culprit, SPANS | "
          "W=2s median concurrent / services | fault-window tokens (plain lines) | baseline p99 root ms -> "
          "slow traces base vs fault | WS | S3 | PR |")
    print("|" + "---|" * 16)
    for g in rows:
        print(row(g))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
