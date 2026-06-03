"""Measure the two make-or-break gates for the tokentax thesis on real Train Ticket data.

GPU-free. Uses tiktoken (cl100k_base) as a PROXY tokenizer for Qwen — fine for an
order-of-magnitude gate check; a Qwen-tokenizer cross-check is a later step (MEASURE-2).

Gate 1 (RLM crossover): do per-minute windows exceed the context cap (~2^14 = 16384,
and the plan's 8192 chunk cap) so the in-context method is FORCED to chunk and RLM
trace-navigation is non-vacuous? Also reports tokens(window)/tokens(single trace) —
the compression ratio the RLM exploits.

Gate 2 (>=50 windows/class): does Train Ticket ALONE yield >=50 log-visible
(exception+return) anomalous windows per class after labeling? This is the number
that could drop Nezha-single-app from a 4 to a 3.
"""

from __future__ import annotations

import statistics as st
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import tiktoken  # noqa: E402

from tokentax.nezha import (  # noqa: E402
    LOG_VISIBLE_TYPES,
    METRIC_ONLY_TYPES,
    load_fault_episodes,
    load_windows,
)

ENC = tiktoken.get_encoding("cl100k_base")
CTX_CAP = 16384      # 2^14, the RLM-3 crossover from the review
CHUNK_CAP = 8192     # the plan's conservative in-context chunk cap
DATES = ["2023-01-29", "2023-01-30"]
RAW = Path(__file__).resolve().parents[1] / "data/raw/Nezha/rca_data"


def ntok(s: str) -> int:
    return len(ENC.encode(s, disallowed_special=()))


def pct(xs, p):
    xs = sorted(xs)
    if not xs:
        return 0
    k = max(0, min(len(xs) - 1, int(round((p / 100) * (len(xs) - 1)))))
    return xs[k]


def fmt(xs):
    if not xs:
        return "n=0"
    return (f"n={len(xs)} min={min(xs):,} p50={pct(xs,50):,} "
            f"p90={pct(xs,90):,} max={max(xs):,} mean={int(st.mean(xs)):,}")


def main() -> None:
    all_windows = []
    for d in DATES:
        all_windows += load_windows(RAW / d)
    episodes = []
    for d in DATES:
        episodes += load_fault_episodes(RAW / d)

    print("=" * 78)
    print(f"NEZHA / TRAIN TICKET — {len(all_windows)} per-minute windows across {DATES}")
    print("=" * 78)

    # ---------- structural sanity ----------
    recs_per = [len(w.records) for w in all_windows]
    traces_per = [len(w.trace_ids()) for w in all_windows]
    multipod_per = [len(w.multi_pod_trace_ids()) for w in all_windows]
    cov = []  # trace_id coverage fraction
    for w in all_windows:
        if w.records:
            cov.append(sum(1 for r in w.records if r.trace_id) / len(w.records))
    print("\n[structure]")
    print(f"  records/window      : {fmt(recs_per)}")
    print(f"  distinct traces/win : {fmt(traces_per)}")
    print(f"  MULTI-POD traces/win: {fmt(multipod_per)}   <- RLM navigates these")
    print(f"  trace_id coverage   : p50={pct(cov,50):.3f} min={min(cov):.3f} "
          f"(frac of log lines carrying a trace_id)")

    # ---------- Gate 1: token sizes per window ----------
    tok_plain, tok_struct, tok_notrace = [], [], []
    per_trace_plain = []  # median plain tokens of a single trace's lines
    for w in all_windows:
        plain = "\n".join(r.to_plain() for r in w.records)
        struct = "\n".join(_dump(r.to_otlp(with_trace=True)) for r in w.records)
        notrace = "\n".join(_dump(r.to_otlp(with_trace=False)) for r in w.records)
        tok_plain.append(ntok(plain))
        tok_struct.append(ntok(struct))
        tok_notrace.append(ntok(notrace))
        # per-trace plain token sizes within this window
        by_trace: dict[str, list[str]] = {}
        for r in w.records:
            if r.trace_id:
                by_trace.setdefault(r.trace_id, []).append(r.to_plain())
        for lines in by_trace.values():
            per_trace_plain.append(ntok("\n".join(lines)))

    print("\n[gate 1 — tokens/window  (tiktoken cl100k proxy)]")
    print(f"  plain (body only)   : {fmt(tok_plain)}")
    print(f"  structured (+ids)   : {fmt(tok_struct)}")
    print(f"  structured-no-trace : {fmt(tok_notrace)}")
    print(f"  single-trace (plain): {fmt(per_trace_plain)}   <- what RLM pulls per trace")
    for name, xs in [("plain", tok_plain), ("structured", tok_struct)]:
        over14 = sum(1 for x in xs if x > CTX_CAP)
        over8 = sum(1 for x in xs if x > CHUNK_CAP)
        print(f"  {name:11s}: {over14}/{len(xs)} windows > 16384 (2^14); "
              f"{over8}/{len(xs)} > 8192 (chunk cap)")
    ratio = (st.median(tok_plain) / st.median(per_trace_plain)) if per_trace_plain else 0
    print(f"  envelope tax (struct/plain median): "
          f"{st.median(tok_struct)/max(1,st.median(tok_plain)):.2f}x")
    print(f"  RLM compression handle (median window / median single trace): {ratio:.1f}x")

    # ---------- Gate 2: labeled windows per class ----------
    win_minutes = {w.key for w in all_windows}
    win_by_key = {w.key: w for w in all_windows}
    by_type: dict[str, int] = {}
    by_type_logvis: dict[str, int] = {}  # episodes whose window actually has >=1 ERROR
    anomalous_keys_logvisible = set()
    rc_service_counts: dict[str, int] = {}
    matched, unmatched = 0, 0
    print("\n[gate 2 — fault episodes -> windows]")
    print(f"  total injection episodes: {len(episodes)}")
    for ep in episodes:
        key = f"{ep['date']}/{ep['inject_minute']}"
        by_type[ep["inject_type"]] = by_type.get(ep["inject_type"], 0) + 1
        if key not in win_minutes:
            unmatched += 1
            continue
        matched += 1
        w = win_by_key[key]
        if ep["inject_type"] in LOG_VISIBLE_TYPES:
            if w.n_errors() >= 1:
                by_type_logvis[ep["inject_type"]] = by_type_logvis.get(ep["inject_type"], 0) + 1
                anomalous_keys_logvisible.add(key)
                rc_service_counts[ep["service"]] = rc_service_counts.get(ep["service"], 0) + 1
    anomalous_minute_keys = {f"{e['date']}/{e['inject_minute']}" for e in episodes} & win_minutes
    normal_count = len(win_minutes) - len(anomalous_minute_keys)
    rc_sorted = dict(sorted(rc_service_counts.items(), key=lambda kv: -kv[1]))
    print(f"  episodes matched to a captured window: {matched}; unmatched(minute not captured): {unmatched}")
    print(f"  episodes by inject_type            : {dict(sorted(by_type.items()))}")
    print(f"  LOG-VISIBLE types {sorted(LOG_VISIBLE_TYPES)} with >=1 ERROR in window: "
          f"{dict(sorted(by_type_logvis.items()))}")
    print(f"  metric-only types {sorted(METRIC_ONLY_TYPES)} -> floor class (expected ~0 ERROR logs)")
    print(f"  distinct anomalous LOG-VISIBLE windows: {len(anomalous_keys_logvisible)}")
    print(f"  normal (non-anomalous-minute) windows  : {normal_count}")
    print(f"  root-cause SERVICE distribution (log-visible): {rc_sorted}")

    # ---------- error-log visibility cross-check ----------
    errs_logvis, errs_metric, errs_normal = [], [], []
    ep_by_key: dict[str, set[str]] = {}
    for ep in episodes:
        ep_by_key.setdefault(f"{ep['date']}/{ep['inject_minute']}", set()).add(ep["inject_type"])
    for w in all_windows:
        types = ep_by_key.get(w.key, set())
        if types & LOG_VISIBLE_TYPES:
            errs_logvis.append(w.n_errors())
        elif types & METRIC_ONLY_TYPES:
            errs_metric.append(w.n_errors())
        elif not types:
            errs_normal.append(w.n_errors())
    print("\n[log-visibility cross-check — ERROR lines per window]")
    print(f"  exception/return windows: {fmt(errs_logvis)}")
    print(f"  metric-only   windows   : {fmt(errs_metric)}  (expect ~0)")
    print(f"  normal        windows   : {fmt(errs_normal)}")

    # ---------- verdicts ----------
    print("\n" + "=" * 78)
    print("VERDICTS")
    print("=" * 78)
    g1 = sum(1 for x in tok_plain if x > CHUNK_CAP) / max(1, len(tok_plain))
    print(f"  GATE 1 (RLM non-vacuous): {g1*100:.0f}% of windows exceed the 8192 chunk cap "
          f"in PLAIN; median window = {st.median(tok_plain):,} tok vs median single "
          f"trace = {int(st.median(per_trace_plain)):,} tok -> "
          f"{'PASS' if g1 >= 0.5 else 'WEAK/FAIL'}")
    nlogvis = len(anomalous_keys_logvisible)
    print(f"  GATE 2 (>=50/class)     : {nlogvis} log-visible anomalous windows total "
          f"(exception={by_type_logvis.get('exception',0)}, return={by_type_logvis.get('return',0)}) "
          f"-> {'PASS' if min(by_type_logvis.get('exception',0), by_type_logvis.get('return',0)) >= 50 else 'FAIL — far under 50/class'}")


def _dump(d: dict) -> str:
    import json
    return json.dumps(d, separators=(",", ":"), ensure_ascii=False)


if __name__ == "__main__":
    main()
