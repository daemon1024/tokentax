"""Is the injected service REACHABLE by following trace_id from the services that error?

This is the model-free precondition for the whole project. The thesis needs a window where

  (a) the logs contain an error, and
  (b) the service that emits it is NOT the culprit, and
  (c) following `trace_id` off that error line reaches the culprit's lines.

(a) and (b) are what `results/RCA_RECOVERABILITY.md` measured. (c) is what nobody measured, and
without it trace context cannot help no matter how cheap it is: if the culprit shares no trace with
any erroring service, `lines_for_trace` returns lines that do not contain the answer.

No model in the loop. Nothing here calls an LLM or costs a token.

Definitions (stated because each one changes the numbers):
  window          one per-minute log CSV, keyed 'YYYY-MM-DD/HH_MM' (Nezha's own granularity).
  error line      LogRecord.is_error, i.e. severity ERROR/FATAL after `nezha._parse_log_field`,
                  which reads Online Boutique's JSON `severity` key AND Train Ticket's logback
                  `%-5level` token. Both formats, one code path.
  culprit         `_service_of(inject_pod)` — replica suffix collapsed, so 'ts-basic-service-
                  866bd68c97-xcqfx' -> 'ts-basic-service'.
  reachable       >=1 trace_id carried by an error line from a NON-culprit service also carries
                  >=1 line (of any severity) from the culprit. This is the honest test: it asks
                  whether an agent that greps for errors and pivots on trace_id lands on the answer.
  reachable_self  the culprit itself emits an error line. Trace context is not needed there.

Usage:
    .venv/bin/python scripts/check_nezha_trace_reach.py
    .venv/bin/python scripts/check_nezha_trace_reach.py --system TrainTicket --types return,exception
    .venv/bin/python scripts/check_nezha_trace_reach.py --json results/runs/nezha_reach.jsonl
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from tokentax.nezha import (  # noqa: E402
    LOG_VISIBLE_TYPES,
    _service_of,
    episodes_by_window,
    load_all_windows,
    system_of,
)

RAW = ROOT / "data/raw/Nezha/rca_data"


def analyse(window, episodes) -> list[dict]:
    """One row per (window, injected episode). A window can host more than one injection."""
    recs = window.records
    errs = [r for r in recs if r.is_error]
    err_by_svc = Counter(_service_of(r.pod) for r in errs)

    # trace_id -> services touched (any severity); and the traces that carry an error, per service
    svcs_by_trace: dict[str, set[str]] = {}
    for r in recs:
        if r.trace_id:
            svcs_by_trace.setdefault(r.trace_id, set()).add(_service_of(r.pod))

    rows = []
    for ep in episodes:
        culprit = ep["service"]
        n_err_culprit = err_by_svc.get(culprit, 0)

        # traces carrying an error emitted by someone OTHER than the culprit
        foreign_err_traces = {
            r.trace_id for r in errs
            if r.trace_id and _service_of(r.pod) != culprit
        }
        reaching = {t for t in foreign_err_traces if culprit in svcs_by_trace.get(t, ())}

        # token accounting for the reachable path, measured on characters (proxy-free);
        # tiktoken lives elsewhere in this repo and is itself only a proxy.
        reach_chars = sum(
            len(r.message) for t in reaching for r in recs if r.trace_id == t
        )
        window_chars = sum(len(r.message) for r in recs)

        top = err_by_svc.most_common(1)[0][0] if err_by_svc else None
        rows.append({
            "window": window.key,
            "system": system_of(window.date),
            "culprit": culprit,
            "fault_type": ep["inject_type"],
            "log_visible_type": ep["inject_type"] in LOG_VISIBLE_TYPES,
            "n_records": len(recs),
            "n_errors": len(errs),
            "n_err_services": len(err_by_svc),
            "err_by_service": dict(err_by_svc.most_common(6)),
            "culprit_errors": n_err_culprit,
            "culprit_emits_error": n_err_culprit > 0,
            "culprit_is_noisiest": top == culprit and n_err_culprit > 0,
            "argmax_correct": top == culprit,
            "culprit_named_in_error_text": any(culprit in r.message for r in errs),
            "n_foreign_err_traces": len(foreign_err_traces),
            "n_reaching_traces": len(reaching),
            "reachable_via_trace": len(reaching) > 0,
            "reach_chars": reach_chars,
            "window_chars": window_chars,
            "reach_ratio": round(reach_chars / window_chars, 5) if window_chars else None,
        })
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", default=str(RAW))
    ap.add_argument("--system", default="all",
                    choices=["all", "TrainTicket", "OnlineBoutique"])
    ap.add_argument("--types", default="all",
                    help="comma-separated inject_types, or 'all', or 'log_visible'")
    ap.add_argument("--json", default="", help="write one JSON object per row to this path")
    a = ap.parse_args()

    raw = Path(a.raw)
    if not raw.exists():
        print(f"missing {raw}\n  git clone --depth 1 https://github.com/IntelligentDDS/Nezha.git {raw.parent}",
              file=sys.stderr)
        return 2

    by_window = episodes_by_window(raw)
    windows = {w.key: w for w in load_all_windows(raw)}

    rows: list[dict] = []
    missing = 0
    for key, eps in sorted(by_window.items()):
        w = windows.get(key)
        if w is None:
            missing += 1
            continue
        rows.extend(analyse(w, eps))

    if a.system != "all":
        rows = [r for r in rows if r["system"] == a.system]
    if a.types == "log_visible":
        rows = [r for r in rows if r["log_visible_type"]]
    elif a.types != "all":
        want = {t.strip() for t in a.types.split(",")}
        rows = [r for r in rows if r["fault_type"] in want]

    if not rows:
        print("no rows after filtering", file=sys.stderr)
        return 1

    hdr = (f"{'window':<18}{'sys':<8}{'culprit':<26}{'type':<14}"
           f"{'errs':>5}{'#svc':>5}{'self':>5}{'noisy':>6}{'reach':>6}{'ratio':>9}")
    print(hdr)
    print("-" * len(hdr))
    for r in rows:
        ratio = "-" if r["reach_ratio"] is None else format(r["reach_ratio"], ".4f")
        print(f"{r['window']:<18}{r['system']:<8}{r['culprit']:<26}{r['fault_type']:<14}"
              f"{r['n_errors']:>5}{r['n_err_services']:>5}"
              f"{'Y' if r['culprit_emits_error'] else '.':>5}"
              f"{'Y' if r['culprit_is_noisiest'] else '.':>6}"
              f"{'Y' if r['reachable_via_trace'] else '.':>6}"
              f"{ratio:>9}")

    def pct(n, d):
        return f"{n}/{d} ({n / d:.0%})" if d else f"{n}/0"

    for scope in ("all", "TrainTicket", "OnlineBoutique"):
        sub = rows if scope == "all" else [r for r in rows if r["system"] == scope]
        if not sub:
            continue
        n = len(sub)
        lv = [r for r in sub if r["log_visible_type"]]
        witherr = [r for r in sub if r["n_errors"] > 0]
        print(f"\n=== {scope} — {n} injected episodes ({len(lv)} of type exception/return) ===")
        print(f"  window contains ANY error line          {pct(len(witherr), n)}")
        print(f"  culprit emits >=1 ERROR itself          {pct(sum(r['culprit_emits_error'] for r in sub), n)}")
        print(f"  culprit is the noisiest service         {pct(sum(r['culprit_is_noisiest'] for r in sub), n)}")
        print(f"  argmax(errors_by_service) is CORRECT    {pct(sum(r['argmax_correct'] for r in sub), n)}")
        print(f"  culprit named in some error's text      {pct(sum(r['culprit_named_in_error_text'] for r in sub), n)}")
        print(f"  REACHABLE by trace_id from a foreign error line   {pct(sum(r['reachable_via_trace'] for r in sub), n)}")
        # the cell the experiment actually needs: an error exists, argmax is wrong, trace_id saves it
        need = [r for r in sub if r["n_errors"] > 0 and not r["argmax_correct"]]
        saved = [r for r in need if r["reachable_via_trace"]]
        print(f"  cause!=symptom AND reachable            {pct(len(saved), len(need))}"
              f"   <- the usable cells")
        if saved:
            ratios = sorted(r["reach_ratio"] for r in saved if r["reach_ratio"] is not None)
            if ratios:
                med = ratios[len(ratios) // 2]
                print(f"  median reach_chars / window_chars       {med:.4f}"
                      f"  ({1 / med:.0f}x smaller than the window)" if med else "")

    if missing:
        print(f"\nnote: {missing} fault windows had no matching log CSV and were skipped", file=sys.stderr)

    if a.json:
        out = Path(a.json)
        out.parent.mkdir(parents=True, exist_ok=True)
        with open(out, "w") as f:
            for r in rows:
                f.write(json.dumps(r) + "\n")
        print(f"\nwrote {len(rows)} rows -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
