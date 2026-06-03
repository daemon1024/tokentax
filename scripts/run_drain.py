"""Drain baseline on the trace-anomaly-localization task (both Nezha systems). GPU-free, 0 tokens.

End-to-end infra-free milestone: build (window,trace) examples -> group-aware split ->
Drain templates + LogisticRegression -> F1 with group bootstrap CI, vs majority and any-ERROR
baselines. Writes results/runs/drain_trace_anomaly.json.
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
    majority_baseline,
)
from tokentax.nezha import build_trace_anomaly_examples, group_split  # noqa: E402

RAW = ROOT / "data/raw/Nezha/rca_data"


def main() -> None:
    print("building trace-anomaly examples (both systems, excluding entry-point-degenerate)…")
    examples = build_trace_anomaly_examples(RAW, exclude_degenerate=True)
    n_pos = sum(e.label for e in examples)
    print(f"  {len(examples):,} examples | anomalous={n_pos:,} normal={len(examples)-n_pos:,} "
          f"| windows={len({e.window_key for e in examples})}")

    test_groups = group_split([e.window_key for e in examples], test_frac=0.3, seed=0)
    train = [e for e in examples if e.window_key not in test_groups]
    test = [e for e in examples if e.window_key in test_groups]
    print(f"  group-aware split: train={len(train):,} test={len(test):,} "
          f"(test windows={len(test_groups)})")

    print("fitting Drain + LogisticRegression…")
    clf = DrainClassifier(sim_th=0.4, depth=4)
    clf.fit(train)
    res = clf.predict(test)
    y_true = [e.label for e in test]
    groups = [e.window_key for e in test]

    drain_m = binary_metrics(y_true, res.y_pred)
    lo, hi = bootstrap_ci(y_true, res.y_pred, groups, average="binary")
    maj = binary_metrics(y_true, majority_baseline([e.label for e in train], y_true))
    anyerr = binary_metrics(y_true, any_error_baseline([e.has_error for e in test]))

    print("\n" + "=" * 70)
    print("DRAIN — trace-anomaly localization (both systems)")
    print("=" * 70)
    print(f"  templates mined        : {res.n_templates}")
    print(f"  fit/predict            : {res.fit_ms:.0f} ms / {res.predict_ms:.0f} ms  (0 LLM tokens)")
    print(f"  Drain F1               : {drain_m['f1']:.3f}  (P={drain_m['precision']:.3f} "
          f"R={drain_m['recall']:.3f})  95% CI [{lo:.3f}, {hi:.3f}]")
    print(f"  majority baseline F1   : {maj['f1']:.3f}")
    print(f"  any-ERROR baseline F1  : {anyerr['f1']:.3f}  (P={anyerr['precision']:.3f} "
          f"R={anyerr['recall']:.3f})  <- expected weak: errors pervade normal traffic")
    beats = drain_m["f1"] > max(maj["f1"], anyerr["f1"])
    print(f"  Drain beats both baselines: {beats}")

    out = {
        "task": "trace_anomaly_localization",
        "method": "drain",
        "n_examples": len(examples),
        "n_train": len(train),
        "n_test": len(test),
        "n_templates": res.n_templates,
        "drain": {**drain_m, "f1_ci95": [lo, hi]},
        "baselines": {"majority": maj, "any_error": anyerr},
        "tokens": 0,
        "fit_ms": res.fit_ms,
        "predict_ms": res.predict_ms,
    }
    outpath = ROOT / "results/runs/drain_trace_anomaly.json"
    outpath.parent.mkdir(parents=True, exist_ok=True)
    outpath.write_text(json.dumps(out, indent=2))
    print(f"\nwrote {outpath.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
