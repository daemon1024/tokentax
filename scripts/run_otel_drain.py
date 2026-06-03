"""Drain on the OTel Demo find-failed-request-traces task (GPU-free). Proves the accuracy axis.

Label = trace contains an ERROR from the fault origin (product-catalog) = an affected request.
Recoverable by construction now (the origin logs its fault), so Drain/any-ERROR ace it — the point
is that accuracy is ACHIEVABLE here (unlike Nezha's 0.51 topology-fingerprint); the method
differentiation on this task is TOKEN COST (RLM greps ~50 errors vs in-context reading ~700k tokens).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from tokentax.methods.drain import DrainClassifier  # noqa: E402
from tokentax.metrics.scoring import (  # noqa: E402
    any_error_baseline,
    binary_metrics,
    bootstrap_ci,
)
from tokentax.nezha import TraceExample, group_split  # noqa: E402
from tokentax.otel_loader import windows_from_manifest  # noqa: E402

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


def main() -> None:
    exs = build_examples()
    pos = sum(e.label for e in exs)
    print(f"{len(exs)} trace examples | affected={pos} ({pos / len(exs):.1%}) "
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
    print(f"Drain F1={m['f1']:.3f} (P={m['precision']:.2f} R={m['recall']:.2f}) "
          f"CI[{lo:.2f},{hi:.2f}] templates={res.n_templates}")
    print(f"any-ERROR baseline F1={anyerr['f1']:.3f}  (recoverable: accuracy is achievable, unlike Nezha)")
    out = {"task": "otel_find_failed_traces", "n": len(exs), "affected": pos,
           "drain": {**m, "f1_ci95": [lo, hi]}, "any_error_baseline": anyerr}
    (ROOT / "results/runs/otel_drain.json").write_text(json.dumps(out, indent=2))
    print("wrote results/runs/otel_drain.json")


if __name__ == "__main__":
    main()
