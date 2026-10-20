"""Offline tests for the pre-registered paired analysis of the forensics run."""

from __future__ import annotations

import math

from tokentax import forensics_stats as S


def _row(model, arm, case, tok, f1=1.0, status="answered", correct=None):
    ok = (f1 >= 0.8 and status == "answered") if correct is None else correct
    return {"model": model, "arm": arm, "case": case, "status": status, "total_tok": tok,
            "f1": f1, "correct": ok}


def test_dedupe_first_observation_wins_and_transport_is_replaced():
    rows = [_row("m", "P", "c1", 0, status="transport"),
            _row("m", "P", "c1", 500),                      # the retry that finally ran
            _row("m", "P", "c1", 999),                      # a second run must NOT replace it
            _row("m", "S", "c1", 0, status="unavailable")]
    out = {(r["arm"]): r for r in S.dedupe(rows)}
    assert out["P"]["total_tok"] == 500
    assert out["S"]["status"] == "unavailable"
    assert S.cells(rows)[("m", "c1")].keys() == {"P"}       # unavailable is not an observation


def test_complete_triples_excludes_incomplete_and_optionally_failures():
    rows = [_row("m", a, "c1", 100) for a in "PST"]
    rows += [_row("m", "P", "c2", 100), _row("m", "S", "c2", 100)]                 # no T
    rows += [_row("m", "P", "c3", 100), _row("m", "S", "c3", 100, f1=0, status="timeout"),
             _row("m", "T", "c3", 100)]
    assert [c for _m, c, _ in S.complete_triples(rows)] == ["c1", "c3"]
    assert [c for _m, c, _ in S.complete_triples(rows, answered_only=True)] == ["c1"]


def test_tokens_per_correct_keeps_failure_tokens_in_the_numerator():
    rows = [_row("m", "P", "a", 100), _row("m", "P", "b", 100, f1=0.2),
            _row("m", "P", "c", 300, f1=0, status="timeout")]
    # 500 tokens spent for 1 correct answer. Dropping the failures would claim 100.
    assert S.tokens_per_correct(rows) == 500
    assert S.tokens_per_correct([_row("m", "P", "a", 100, f1=0.1)]) is None


def test_a_giveup_does_not_look_cheap():
    cheap_giveup = [_row("m", "S", f"c{i}", 50, f1=0, status="no_answer") for i in range(9)] \
        + [_row("m", "S", "c9", 1000)]
    honest = [_row("m", "T", f"c{i}", 400) for i in range(5)] \
        + [_row("m", "T", f"c{i}", 400, f1=0.1) for i in range(5, 10)]
    assert S.tokens_per_correct(cheap_giveup) == 1450       # (9*50 + 1000) / 1
    assert S.tokens_per_correct(honest) == 800              # 4000 / 5


def test_sign_test_exact_values():
    assert S.sign_test([1] * 10)["p"] == 2 / 1024
    r = S.sign_test([1, 1, -1, 0, 0])
    assert (r["n"], r["pos"], r["neg"], r["ties"]) == (3, 2, 1, 2)
    assert math.isclose(r["p"], 1.0)
    assert S.sign_test([0, 0])["p"] == 1.0
    assert S.sign_test([5, 5, 5, 5, 5, -1])["p"] == 2 * (1 + 6) / 64


def test_paired_deltas_direction_is_b_minus_a():
    rows = [_row("m", "S", "c1", 1000), _row("m", "T", "c1", 400),
            _row("m", "S", "c2", 500), _row("m", "T", "c2", 700)]
    assert S.paired_deltas(rows, "S", "T", "total_tok") == [-600, 200]


def test_geo_ratio_is_within_model_so_tokenizers_do_not_dominate():
    rows = []
    for c in ("c1", "c2"):
        rows += [_row("fine", "S", c, 10_000), _row("fine", "T", c, 5_000)]      # T is 0.5x
        rows += [_row("coarse", "S", c, 100), _row("coarse", "T", c, 200)]       # T is 2x
    rows += [_row(m, "P", c, 1) for m in ("fine", "coarse") for c in ("c1", "c2")]
    assert math.isclose(S.geo_ratio(rows, "T", "S"), 1.0)  # sqrt(0.5 * 2)
    # a pooled sum would have said T/S = (10_400)/(20_200)=0.51 -- the tokenizer-dominated answer
    assert S.per_model_tpc(rows, "T")["fine"] == 5_000


def test_bootstrap_ci_brackets_a_clear_effect_and_counts_undefined_draws():
    rows = []
    for i in range(20):
        c = f"c{i}"
        rows += [_row("m", "P", c, 900), _row("m", "S", c, 1000), _row("m", "T", c, 500)]
    ci = S.bootstrap_ci(rows, lambda r, cases: S.geo_ratio(r, "T", "S", cases), n_boot=200, seed=1)
    assert math.isclose(ci["lo"], 0.5) and math.isclose(ci["hi"], 0.5)
    assert ci["n_undefined"] == 0

    # when T is never correct the ratio is undefined in every draw; that must be reported, not hidden
    bad = [_row("m", a, f"c{i}", 100, f1=0.0 if a == "T" else 1.0) for i in range(5) for a in "PST"]
    ci2 = S.bootstrap_ci(bad, lambda r, cases: S.geo_ratio(r, "T", "S", cases), n_boot=50, seed=1)
    assert ci2["lo"] is None and ci2["n_undefined"] == 50


def test_bootstrap_is_reproducible():
    rows = []
    for i in range(12):
        c = f"c{i}"
        rows += [_row("m", "P", c, 900), _row("m", "S", c, 1000 + 37 * i),
                 _row("m", "T", c, 600 + 91 * (i % 5), f1=1.0 if i % 4 else 0.0)]
    stat = lambda r, cases: S.geo_ratio(r, "T", "S", cases)  # noqa: E731
    assert S.bootstrap_ci(rows, stat, n_boot=100, seed=5) == S.bootstrap_ci(rows, stat, n_boot=100, seed=5)
