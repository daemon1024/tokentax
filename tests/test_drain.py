"""Unit test for the Drain baseline on a tiny, trivially-separable synthetic set."""

from __future__ import annotations

from dataclasses import dataclass

from tokentax.methods.drain import DrainClassifier


@dataclass
class Ex:
    lines: list[str]
    label: int


def _make_set():
    # anomalous traces carry a distinctive error template; normal traces do not.
    anom = [Ex(["ERROR payment charge failed code 500", "ERROR retry exhausted"], 1) for _ in range(12)]
    norm = [Ex(["INFO request handled ok 200", "INFO cache hit user"], 0) for _ in range(12)]
    return anom + norm


def test_drain_fits_and_separates():
    train = _make_set()
    clf = DrainClassifier(sim_th=0.4, depth=4)
    clf.fit(train)
    res = clf.predict(train)
    assert res.n_templates > 0
    assert len(res.y_pred) == len(train)
    # trivially separable -> should recover training labels well
    acc = sum(int(p == e.label) for p, e in zip(res.y_pred, train, strict=True)) / len(train)
    assert acc >= 0.9


def test_drain_zero_tokens_property():
    # Drain is the cost floor: the run script records 0 tokens; here we assert it produces
    # predictions without any LLM client involved.
    clf = DrainClassifier()
    clf.fit(_make_set())
    res = clf.predict(_make_set())
    assert all(p in (0, 1) for p in res.y_pred)
