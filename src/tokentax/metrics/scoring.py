"""Scoring + baselines, with group-level bootstrap CIs.

Bootstrap resamples at the GROUP level (window/episode), not the example level, because traces
within a window are autocorrelated — example-level resampling understates CI width (REVIEW STATS-6).
"""

from __future__ import annotations

import numpy as np
from sklearn.metrics import (
    f1_score,
    precision_recall_fscore_support,
)


def binary_metrics(y_true, y_pred) -> dict[str, float]:
    p, r, f, _ = precision_recall_fscore_support(
        y_true, y_pred, average="binary", zero_division=0
    )
    return {"precision": float(p), "recall": float(r), "f1": float(f)}


def multiclass_metrics(y_true, y_pred) -> dict[str, float]:
    acc = float(np.mean(np.asarray(y_true) == np.asarray(y_pred)))
    macro_f1 = float(f1_score(y_true, y_pred, average="macro", zero_division=0))
    return {"accuracy": acc, "macro_f1": macro_f1}


def bootstrap_ci(
    y_true, y_pred, groups, metric: str = "f1", average: str = "binary",
    n: int = 1000, seed: int = 0,
) -> tuple[float, float]:
    """Group-level bootstrap 95% CI for f1 (binary or macro)."""
    yt = np.asarray(y_true)
    yp = np.asarray(y_pred)
    g = np.asarray(groups)
    uniq = np.unique(g)
    idx_by_group = {gg: np.where(g == gg)[0] for gg in uniq}
    rng = np.random.default_rng(seed)
    stats: list[float] = []
    for _ in range(n):
        chosen = rng.choice(uniq, size=len(uniq), replace=True)
        idx = np.concatenate([idx_by_group[c] for c in chosen])
        if average == "binary":
            stats.append(f1_score(yt[idx], yp[idx], average="binary", zero_division=0))
        else:
            stats.append(f1_score(yt[idx], yp[idx], average="macro", zero_division=0))
    lo, hi = np.percentile(stats, [2.5, 97.5])
    return float(lo), float(hi)


# --- mandatory baselines (a method must beat these to mean anything) ---

def majority_baseline(y_train, y_test) -> list:
    """Predict the most common training label for every test example."""
    vals, counts = np.unique(np.asarray(y_train), return_counts=True)
    maj = vals[int(np.argmax(counts))]
    return [maj] * len(y_test)


def any_error_baseline(has_error_flags) -> list[int]:
    """Zero-token trace-anomaly baseline: predict anomalous iff the trace has any ERROR line.

    Expected to be ~useless on Nezha (ERROR logs pervade normal traffic) — which is the point:
    the task needs correlation, not error counting.
    """
    return [int(bool(x)) for x in has_error_flags]
