"""Model-free gate for rca-lab scenario captures. Decides which stage comparisons a model run could test.

Run on one scenario directory written by the capture procedure (`data/rcalab/<scenario>/`):

    logs.jsonl     OTLP-JSON resourceLogs, baseline + fault segment (collector file exporter)
    traces.jsonl   OTLP-JSON resourceSpans, same interval (may be gzipped: traces.jsonl.gz)
    meta.json      {"scenario", "culprit", "baseline_start_ns", "baseline_end_ns",
                    "fault_start_ns", "fault_end_ns", ...}

No model is called. Every quantity is computed by `tokentax.rcalab` (unit-tested; reproduces the
published sc-10 numbers) or by the unchanged functions of `scripts/check_request_ambiguity.py`.

CRITERIA, fixed before any degradation capture was looked at:

  WS  which-service task (Stages 0-2) has a signal to find:
        fault-segment ERROR log records >= 10, AND
        fault ERROR rate >= 2x the baseline ERROR rate (per minute).
      Otherwise the logs carry no fault signal and every stage would be measuring a guess.

  S3  trace_id can pay on the which-service task (the open Stage 3 question):
        WS, AND argmax(errors_by_service) is NOT strictly correct (else a digest names the culprit
        with no join, the settled Nezha/OTel-Demo null), AND
        the culprit is reachable by trace_id from a foreign ERROR log line in >= 5 traces and
        >= 10% of foreign-erroring traces (LOGS, because the arms read logs).

  PR  per-request task: `check_request_ambiguity.verdict` is PROCEED at W = 2 s over ALL services
      (median concurrent requests >= 5 AND median services per erroring trace >= 2, >= 30 usable),
      the same criterion and fallback REQUEST_FORENSICS_PREREG.md used. W = 0.05/0.25 are reported.

Usage:
    .venv/bin/python scripts/rcalab_gate.py data/rcalab/sc-06 [--json results/runs/rcalab_gate/sc-06.json]
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import shutil
import sys
import tempfile
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import tiktoken  # noqa: E402

from tokentax import rcalab as R  # noqa: E402
from tokentax import rcalab_dataset as DS  # noqa: E402
from tokentax.methods.repl import LogREPL  # noqa: E402
from tokentax.nezha import _service_of, format_window  # noqa: E402
from tokentax.rcalab import open_text  # noqa: E402

_spec = importlib.util.spec_from_file_location("cra", ROOT / "scripts/check_request_ambiguity.py")
CRA = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(CRA)

ENC = tiktoken.get_encoding("cl100k_base")
W_REPORT = (0.05, 0.25, 1.0, 2.0)
MIN_ERR, MIN_RATE_X = 10, 2.0
MIN_REACH, MIN_REACH_FRAC = 5, 0.10


def ntok(s: str) -> int:
    return len(ENC.encode(s, disallowed_special=()))


def _plain_logs(d: Path) -> Path:
    """check_request_ambiguity.read_records wants a plain file; decompress a .zst/.gz copy if needed."""
    p = DS.find_file(d, "logs")
    if p.suffix == ".jsonl":
        return p
    tmp = Path(tempfile.mkdtemp()) / "logs.jsonl"
    with open_text(p) as src, open(tmp, "w", encoding="utf-8") as dst:
        shutil.copyfileobj(src, dst)
    return tmp


def token_sizes(recs) -> dict:
    """cl100k size of the whole window as each arm would see it, and as Stage 0 would read it."""
    out = {}
    for cond in ("plain", "structured_no_trace", "structured"):
        out[f"repl_lines_{cond}"] = ntok("\n".join(LogREPL(recs, condition=cond).lines)) if recs else 0
    out["stage0_format_window_plain"] = ntok(format_window(recs, "plain")) if recs else 0
    return out


def gate(d: Path) -> dict:
    meta = json.loads((d / ("meta_raw.json" if (d / "meta_raw.json").exists() else "meta.json")).read_text())
    scenario = meta.get("scenario", d.name)
    culprit = meta.get("culprit") or DS.truth_for(scenario, "fault")["culprit_service"]
    if not culprit:   # no single application service is at fault (DNS for all, DB-internal latent risk)
        culprit = "(none)"
    b0, b1 = int(meta["baseline_start_ns"]), int(meta["baseline_end_ns"])
    f0, f1 = int(meta["fault_start_ns"]), int(meta["fault_end_ns"])
    bmin, fmin = (b1 - b0) / 60e9, (f1 - f0) / 60e9

    plain_logs = _plain_logs(d)
    allrecs = DS.parse_logs(plain_logs)
    base, fault = R.window(allrecs, b0, b1), R.window(allrecs, f0, f1)

    def logblock(recs, minutes):
        errs = [r for r in recs if r.is_error]
        ebs = R.errors_by_service(recs)
        return {
            "minutes": round(minutes, 2), "records": len(recs),
            "records_with_trace": sum(1 for r in recs if r.trace_id),
            "error_records": len(errs),
            "error_per_min": round(len(errs) / minutes, 2) if minutes else 0.0,
            "warn_records": sum(1 for r in recs if r.level == "WARN"),
            "records_by_service": dict(Counter(_service_of(r.pod) for r in recs).most_common()),
            "errors_by_service": dict(ebs.most_common()),
        }

    out = {"capture": d.name, "scenario": meta.get("scenario", d.name), "culprit": culprit, "meta": meta,
           "baseline_logs": logblock(base, bmin), "fault_logs": logblock(fault, fmin)}

    ebs = R.errors_by_service(fault)
    top, tied = R.argmax_service(ebs)
    out["argmax"] = {"top": top, "tied": tied, "strictly_correct": R.argmax_correct(ebs, culprit)}
    out["log_reach"] = R.log_reach(fault, culprit)
    out["culprit_named_in_foreign_errors"] = R.culprit_named_in_errors(fault, culprit)
    out["error_templates_sample"] = sorted(
        Counter(f"{_service_of(r.pod)}: {r.to_plain()[:140]}" for r in fault if r.is_error).items(),
        key=lambda kv: -kv[1])[:12]

    tp = DS.find_file(d, "traces")
    if tp:
        bsp = R.parse_spans(tp, b0, b1)
        slow = R.root_duration_quantile(bsp, 0.99)
        fsp = R.parse_spans(tp, f0, f1)
        out["baseline_spans"] = R.span_reach(bsp, culprit, slow_ms=slow)
        out["fault_spans"] = R.span_reach(fsp, culprit, slow_ms=slow)
        del bsp, fsp

    # check_request_ambiguity, unchanged, on the fault segment only
    cra_recs = [r for r in CRA.read_records(plain_logs) if r["ts"] and f0 <= r["ts"] <= f1]
    ok, umsg = CRA.check_units(cra_recs) if cra_recs else (False, "no records")
    amb = {"units_ok": ok, "units": umsg, "all_services": [], "api_gateway": []}
    for w in W_REPORT:
        for key, edge in (("all_services", ""), ("api_gateway", "api-gateway")):
            a = CRA.analyse(cra_recs, w, edge)
            v, why = CRA.verdict(a)
            amb[key].append({"W": w, "usable": a["usable"], "edge_errors": a["edge_errors"],
                             "median_concurrent": a["median_concurrent_requests"],
                             "median_services": a["median_trace_services"],
                             "single_service_frac": round(a["single_service_frac"], 3),
                             "verdict": v, "why": why})
    out["ambiguity"] = amb

    out["tokens_fault_window"] = token_sizes(fault)
    # per-minute sub-windows: what one model cell would read if the segment were cut into 60 s windows
    subs = []
    t = f0
    while t + 60e9 <= f1 + 1:
        sub = R.window(fault, int(t), int(t + 60e9))
        subs.append({"start_ns": int(t), "records": len(sub), "errors": sum(r.is_error for r in sub),
                     "tok_plain": ntok("\n".join(LogREPL(sub, condition="plain").lines)) if sub else 0})
        t += 60e9
    out["fault_minutes"] = subs

    # ---- verdicts ----
    fl, bl = out["fault_logs"], out["baseline_logs"]
    rate_ok = fl["error_per_min"] >= MIN_RATE_X * bl["error_per_min"] if bl["error_per_min"] else True
    ws = fl["error_records"] >= MIN_ERR and rate_ok
    lr = out["log_reach"]
    s3 = (ws and culprit != "(none)" and not out["argmax"]["strictly_correct"] and lr["reach_traces"] >= MIN_REACH
          and lr["reach_frac_of_foreign"] >= MIN_REACH_FRAC)
    pr = next(x for x in amb["all_services"] if x["W"] == 2.0)["verdict"] == "PROCEED"
    out["verdict"] = {"WS": ws, "S3": s3, "PR": pr,
                      "WS_why": f"{fl['error_records']} ERROR in fault ({fl['error_per_min']}/min) vs "
                                f"baseline {bl['error_per_min']}/min",
                      "S3_why": f"argmax={top} tied={tied} correct={out['argmax']['strictly_correct']}; "
                                f"reach {lr['reach_traces']}/{lr['foreign_erroring_traces']} foreign-erroring traces",
                      "PR_why": next(x for x in amb["all_services"] if x["W"] == 2.0)["why"]}
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("dir")
    ap.add_argument("--json", default="")
    a = ap.parse_args()
    res = gate(Path(a.dir))
    v = res["verdict"]
    print(json.dumps({k: res[k] for k in ("scenario", "culprit", "baseline_logs", "fault_logs", "argmax",
                                          "log_reach", "culprit_named_in_foreign_errors")}, indent=1))
    for k in ("baseline_spans", "fault_spans"):
        if k in res:
            print(k, json.dumps(res[k]))
    print("error templates:")
    for t, n in res["error_templates_sample"]:
        print(f"  {n:5d}  {t}")
    print("ambiguity (all services):")
    for x in res["ambiguity"]["all_services"]:
        print(f"  W={x['W']:<5} usable={x['usable']:<5} conc={x['median_concurrent']:<6} "
              f"svcs={x['median_services']:<4} {x['verdict']}")
    print("tokens (fault window):", res["tokens_fault_window"])
    print("per-minute:", [(m["records"], m["errors"], m["tok_plain"]) for m in res["fault_minutes"]])
    print(f"VERDICT WS={v['WS']} S3={v['S3']} PR={v['PR']}")
    print("  ", v["WS_why"])
    print("  ", v["S3_why"])
    print("  ", v["PR_why"])
    if a.json:
        Path(a.json).parent.mkdir(parents=True, exist_ok=True)
        Path(a.json).write_text(json.dumps(res, indent=1, default=str))
        print("wrote", a.json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
