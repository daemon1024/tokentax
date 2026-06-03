"""Drain on the OTel Demo find-failed-request-traces task (GPU-free). Proves the accuracy axis.

Label = trace contains an ERROR from the fault origin (product-catalog) = an affected request.
Recoverable by construction now (the origin logs its fault), so Drain/any-ERROR ace it — the point
is that accuracy is ACHIEVABLE here (unlike Nezha's 0.51 topology-fingerprint); the method
differentiation on this task is TOKEN COST (RLM greps ~50 errors vs in-context reading ~700k tokens).
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from tokentax.methods.drain import DrainClassifier  # noqa: E402
from tokentax.metrics.scoring import (  # noqa: E402
    any_error_baseline,
    binary_metrics,
    bootstrap_ci,
    majority_baseline,
    multiclass_metrics,
)
from tokentax.nezha import TraceExample, group_split  # noqa: E402
from tokentax.otel_loader import windows_from_manifest  # noqa: E402

CULPRITS = ["product-catalog", "cart", "ad", "payment"]

LOGS = ROOT / "data/otel_demo/logs.jsonl"
MANIFEST = ROOT / "data/otel_demo/manifest.json"
ORIGINS = {"productCatalogFailure": "product-catalog", "paymentFailure": "payment",
           "cartFailure": "cart", "adFailure": "ad"}


def build_examples() -> list[TraceExample]:
    windows = windows_from_manifest(LOGS, MANIFEST)
    origins = set(ORIGINS.values())
    exs: list[TraceExample] = []
    for w in windows:
        by_trace: dict[str, list] = {}
        for r in w.records:
            if r.trace_id:
                by_trace.setdefault(r.trace_id, []).append(r)
        for tid, recs in by_trace.items():
            label = 1 if any(r.is_error and r.pod in origins for r in recs) else 0
            exs.append(TraceExample("otel", w.key, tid, recs, label, len({r.pod for r in recs})))
    return exs


def build_root_cause_examples() -> list[TraceExample]:
    """Per affected trace: label = culprit-service index (the origin that errored in it)."""
    idx = {s: i for i, s in enumerate(CULPRITS)}
    exs: list[TraceExample] = []
    for w in windows_from_manifest(LOGS, MANIFEST):
        by_trace: dict[str, list] = {}
        for r in w.records:
            if r.trace_id:
                by_trace.setdefault(r.trace_id, []).append(r)
        for tid, recs in by_trace.items():
            culprits = {r.pod for r in recs if r.is_error and r.pod in idx}
            if len(culprits) == 1:
                svc = culprits.pop()
                exs.append(TraceExample("otel", w.key, tid, recs, idx[svc], len({r.pod for r in recs})))
    return exs


def main() -> None:
    out: dict = {}

    # Task 1 — find-failed-request-traces (binary, recoverable)
    exs = build_examples()
    pos = sum(e.label for e in exs)
    print(f"[find-failed-traces] {len(exs)} traces | affected={pos} ({pos / len(exs):.1%}) "
          f"| windows={len({e.window_key for e in exs})}")
    test_w = group_split([e.window_key for e in exs], test_frac=0.34, seed=1)
    train = [e for e in exs if e.window_key not in test_w]
    test = [e for e in exs if e.window_key in test_w]
    clf = DrainClassifier()
    clf.fit(train)
    res = clf.predict(test)
    yt = [e.label for e in test]
    m = binary_metrics(yt, res.y_pred)
    lo, hi = bootstrap_ci(yt, res.y_pred, [e.window_key for e in test])
    anyerr = binary_metrics(yt, any_error_baseline([e.has_error for e in test]))
    print(f"  Drain F1={m['f1']:.3f} CI[{lo:.2f},{hi:.2f}] | any-ERROR baseline F1={anyerr['f1']:.3f}")
    out["find_failed_traces"] = {"n": len(exs), "affected": pos,
                                 "drain": {**m, "f1_ci95": [lo, hi]}, "any_error_baseline": anyerr}

    # Task 2 — root-cause / culprit-service (multi-class, recoverable)
    rexs = build_root_cause_examples()
    dist = {CULPRITS[k]: v for k, v in Counter(e.label for e in rexs).items()}
    print(f"[root-cause] {len(rexs)} affected traces by culprit: {dist}")
    if rexs:
        rtest_w = group_split([e.window_key for e in rexs], test_frac=0.34, seed=2)
        rtr = [e for e in rexs if e.window_key not in rtest_w]
        rte = [e for e in rexs if e.window_key in rtest_w]
        rclf = DrainClassifier()
        rclf.fit(rtr)
        rres = rclf.predict(rte)
        ryt = [e.label for e in rte]
        rm = multiclass_metrics(ryt, rres.y_pred)
        rmaj = multiclass_metrics(ryt, majority_baseline([e.label for e in rtr], ryt))
        print(f"  Drain acc={rm['accuracy']:.3f} macro_F1={rm['macro_f1']:.3f} | "
              f"majority macro_F1={rmaj['macro_f1']:.3f}")
        out["root_cause"] = {"n": len(rexs), "by_culprit": dist, "drain": rm, "majority_baseline": rmaj}

    (ROOT / "results/runs/otel_drain.json").write_text(json.dumps(out, indent=2))
    print("wrote results/runs/otel_drain.json")


if __name__ == "__main__":
    main()
