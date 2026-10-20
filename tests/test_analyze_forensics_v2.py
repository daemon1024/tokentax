"""Offline tests for the V2 analysis's pre-registered decision logic (synthetic rows)."""

from __future__ import annotations

import importlib.util
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("a2", ROOT / "scripts/analyze_request_forensics_v2.py")
A2 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(A2)


def row(model, arm, case, tok, f1, status="answered"):
    return {"model": model, "arm": arm, "case": case, "total_tok": tok, "f1": f1,
            "correct": status == "answered" and f1 >= 0.8, "status": status, "rounds": 3}


def _rows(t_tok=4000, ti_tok=3500, s_tok=100_000, s_f1=0.3, n=12, models=("m1", "m2")):
    rows = []
    for m in models:
        for i in range(n):
            c = f"c{i}"
            ok = i % 3 == 0                      # S right on a third of the cases
            rows += [row(m, "P", c, 150_000, 0.1, "no_answer" if i % 2 else "answered"),
                     row(m, "S", c, s_tok, 1.0 if ok else s_f1),
                     row(m, "T", c, t_tok + i, 1.0), row(m, "TI", c, ti_tok + i, 1.0)]
    return rows


def test_quadruples_require_all_four_arms():
    rows = _rows(n=3)
    rows = [r for r in rows if not (r["model"] == "m1" and r["case"] == "c0" and r["arm"] == "TI")]
    q = A2.quads(rows)
    assert len(q) == 5 and ("m1", "c0") not in {(m, c) for m, c, _ in q}


def test_tpc_counts_failures_in_the_numerator():
    rows = _rows(n=4, models=("m1",))
    # P: 4 cells x 150k, none correct -> undefined
    assert A2.tpc_by_model(rows, "P")["m1"] is None
    s = [r for r in rows if r["arm"] == "S"]
    assert A2.tpc_by_model(rows, "S")["m1"] == sum(r["total_tok"] for r in s) / sum(r["correct"] for r in s)


def test_index_arm_that_is_much_cheaper_and_as_accurate_pays():
    c = A2.contrast(_rows(), "S", "T")
    assert c["tpc_ratio"] < 0.1 and c["ci"]["hi"] < 1.0 and c["mean_df1"] > 0
    assert A2.index_arm_verdict(c)["pays"]


def test_an_index_arm_no_cheaper_than_S_fires_falsification():
    c = A2.contrast(_rows(t_tok=100_000, s_f1=1.0), "S", "T")
    v = A2.index_arm_verdict(c)
    assert not v["pays"] and any("TPC ratio" in f for f in v["fired"])


def test_non_inferiority_fires_when_the_index_arm_loses_accuracy():
    rows = _rows(s_f1=1.0)
    for r in rows:
        if r["arm"] == "T":
            r["f1"], r["correct"] = 0.5, False
            if r["case"] in ("c0",):
                r["f1"], r["correct"] = 1.0, True
    v = A2.index_arm_verdict(A2.contrast(rows, "S", "T"))
    assert not v["pays"] and any("dF1" in f for f in v["fired"])


def test_case_level_ln_ratio_uses_answered_pairs_only():
    rows = _rows(n=2, models=("m1",))
    d = A2.case_level(rows, "T", "TI", "total_tok", log_ratio=True, answered_only=True)
    assert set(d) == {"c0", "c1"} and all(v < 0 for v in d.values())
    assert math.isclose(d["c0"], math.log(3500 / 4000))


def test_replicate_check_reports_absent_and_ratio():
    rows = _rows(models=("m1",))
    assert A2.replicate_checks(rows, []) == {"present": False}
    rep = [dict(r, total_tok=r["total_tok"] * 2) for r in rows if r["arm"] in ("T", "TI")]
    rc = A2.replicate_checks(rows, rep)
    assert rc["present"] and math.isclose(rc["T"]["abs_ln_rep_main"], math.log(2), rel_tol=1e-3)
    assert rc["T"]["rep_over_S_main"] < 0.8
