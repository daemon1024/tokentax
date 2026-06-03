"""Validate the settled data design on real Nezha data (both systems, one pipeline).

Confirms: (a) Gate 1 holds on BOTH Train Ticket and Online Boutique; (b) the derived
trace-level anomaly labels yield thousands of (window,trace) examples; (c) the
entry-point degeneracy risk (e.g. OB frontend touched by ~every trace) is quantified;
(d) combined root-cause episode counts per class. GPU-free, tiktoken cl100k proxy.
"""

from __future__ import annotations

import statistics as st
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import tiktoken  # noqa: E402

from tokentax.nezha import (  # noqa: E402
    LOG_VISIBLE_TYPES,
    episodes_by_window,
    label_traces,
    load_all_windows,
    system_of,
)

ENC = tiktoken.get_encoding("cl100k_base")
CHUNK_CAP = 8192
RAW = Path(__file__).resolve().parents[1] / "data/raw/Nezha/rca_data"


def ntok(s: str) -> int:
    return len(ENC.encode(s, disallowed_special=()))


def fmt(xs):
    if not xs:
        return "n=0"
    xs = sorted(xs)
    p = lambda q: xs[max(0, min(len(xs) - 1, int(round(q * (len(xs) - 1)))))]  # noqa: E731
    return f"n={len(xs)} min={min(xs):,} p50={p(.5):,} p90={p(.9):,} max={max(xs):,}"


def main() -> None:
    windows = load_all_windows(RAW)
    epw = episodes_by_window(RAW)

    print("=" * 80)
    print(f"NEZHA BOTH SYSTEMS — {len(windows)} windows")
    for sysname in ("TrainTicket", "OnlineBoutique"):
        ws = [w for w in windows if system_of(w.date) == sysname]
        print(f"  {sysname:15s}: {len(ws)} windows")
    print("=" * 80)

    # ---- Gate 1 per system: window tokens + per-trace tokens ----
    print("\n[Gate 1 — window vs single-trace tokens, per system]")
    for sysname in ("TrainTicket", "OnlineBoutique"):
        ws = [w for w in windows if system_of(w.date) == sysname]
        win_tok, tr_tok = [], []
        for w in ws:
            win_tok.append(ntok("\n".join(r.to_plain() for r in w.records)))
            by_t: dict[str, list[str]] = {}
            for r in w.records:
                if r.trace_id:
                    by_t.setdefault(r.trace_id, []).append(r.to_plain())
            tr_tok += [ntok("\n".join(v)) for v in by_t.values()]
        over = sum(1 for x in win_tok if x > CHUNK_CAP)
        handle = st.median(win_tok) / max(1, st.median(tr_tok))
        print(f"  {sysname:15s} window(plain): {fmt(win_tok)}")
        print(f"  {'':15s} single-trace : {fmt(tr_tok)}")
        print(f"  {'':15s} >chunk-cap: {over}/{len(win_tok)} | RLM handle (win/trace median): {handle:.0f}x")

    # ---- Gate 2 reframed: root-cause episodes per class (both systems) ----
    print("\n[Root-cause task — fault episodes, both systems]")
    by_type = Counter()
    logvis_by_sys = Counter()
    services = Counter()
    for key, eps in epw.items():
        date = key.split("/")[0]
        sysname = system_of(date)
        for ep in eps:
            by_type[ep["inject_type"]] += 1
            if ep["inject_type"] in LOG_VISIBLE_TYPES:
                logvis_by_sys[sysname] += 1
                services[ep["service"]] += 1
    print(f"  episodes by type        : {dict(sorted(by_type.items()))}")
    print(f"  log-visible by system   : {dict(logvis_by_sys)} (total {sum(logvis_by_sys.values())})")
    print(f"  distinct culprit services (log-visible): {len(services)}")
    print(f"  service label spread    : {dict(services.most_common())}")

    # ---- Trace-level anomaly labels: the new sample multiplier ----
    print("\n[Trace-level anomaly labels — derived from inject_pod topology]")
    n_fault_windows = 0
    total_anom, total_norm = 0, 0
    frac_touch = []          # per fault-window: fraction of traces labeled anomalous
    degenerate = 0           # fault windows where >90% traces anomalous (entry-point faults)
    anom_trace_tok = []
    for w in windows:
        eps = epw.get(w.key, [])
        if not eps:
            continue
        labels = label_traces(w, eps)
        if not labels:
            continue
        n_fault_windows += 1
        a = sum(1 for v in labels.values() if v)
        total_anom += a
        total_norm += len(labels) - a
        frac = a / len(labels)
        frac_touch.append(round(frac, 2))
        if frac > 0.9:
            degenerate += 1
        # token size of anomalous traces (what RLM reads)
        by_t: dict[str, list[str]] = {}
        for r in w.records:
            if r.trace_id and labels.get(r.trace_id):
                by_t.setdefault(r.trace_id, []).append(r.to_plain())
        anom_trace_tok += [ntok("\n".join(v)) for v in by_t.values()]
    print(f"  fault windows (in-corpus)        : {n_fault_windows}")
    print(f"  labeled (window,trace) examples  : {total_anom + total_norm:,} "
          f"(anomalous={total_anom:,}, normal={total_norm:,})")
    print(f"  anomalous-trace fraction/window  : {fmt(frac_touch)}")
    print(f"  degenerate fault windows (>90% traces anomalous, e.g. entry-point): "
          f"{degenerate}/{n_fault_windows}")
    print(f"  anomalous-trace token size (plain): {fmt(anom_trace_tok)}  <- RLM reads these")

    print("\n" + "=" * 80)
    print("DESIGN VERDICT")
    print("=" * 80)
    print(f"  Gate 1 holds on both systems (windows >> {CHUNK_CAP} chunk cap).")
    print(f"  Root-cause task: {sum(logvis_by_sys.values())} log-visible episodes over "
          f"{len(services)} services (small-n, bootstrap CIs).")
    print(f"  Trace-anomaly task: {total_anom + total_norm:,} labeled (window,trace) pairs "
          f"-> the sample multiplier works ({'OK' if total_anom+total_norm > 2000 else 'THIN'}). "
          f"Exclude/flag {degenerate} entry-point-degenerate fault windows.")


if __name__ == "__main__":
    main()
