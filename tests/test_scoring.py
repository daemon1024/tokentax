"""Unit tests for scoring + baselines (cross-checked against hand-computed values)."""

from __future__ import annotations

from tokentax.metrics.scoring import (
    any_error_baseline,
    binary_metrics,
    bootstrap_ci,
    majority_baseline,
    multiclass_metrics,
)


def test_binary_metrics_matches_hand_computation():
    y_true = [1, 1, 0, 0, 1]
    y_pred = [1, 0, 0, 1, 1]
    # TP=2, FP=1, FN=1 -> P=2/3, R=2/3, F1=2/3
    m = binary_metrics(y_true, y_pred)
    assert abs(m["precision"] - 2 / 3) < 1e-9
    assert abs(m["recall"] - 2 / 3) < 1e-9
    assert abs(m["f1"] - 2 / 3) < 1e-9


def test_multiclass_metrics():
    m = multiclass_metrics(["a", "b", "c", "a"], ["a", "b", "c", "b"])
    assert abs(m["accuracy"] - 0.75) < 1e-9
    assert 0.0 <= m["macro_f1"] <= 1.0


def test_bootstrap_ci_bounds():
    y_true = [1, 0] * 25
    y_pred = [1, 0] * 25            # perfect
    groups = [f"g{i // 2}" for i in range(50)]
    lo, hi = bootstrap_ci(y_true, y_pred, groups, average="binary", n=200, seed=0)
    assert 0.0 <= lo <= hi <= 1.0
    assert hi == 1.0               # perfect predictions -> upper bound 1.0


def test_majority_baseline():
    pred = majority_baseline([0, 0, 0, 1], [9, 9, 9])
    assert pred == [0, 0, 0]


def test_any_error_baseline():
    assert any_error_baseline([True, False, True]) == [1, 0, 1]
