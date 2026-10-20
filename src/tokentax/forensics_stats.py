"""Paired analysis for the per-request forensics run (results/REQUEST_FORENSICS_PREREG.md).

Every quantity here is the one the pre-registration names; nothing is added after seeing results.

ROW STATUS. A cell ends in exactly one status:
    answered     the model produced a parseable final answer
    no_answer    it aborted (token ceiling / round cap) or never produced parseable JSON
    timeout      the wall-clock cell timeout fired; tokens are the rounds that completed (a LOWER bound)
    transport    HTTP 429 / 5xx / connect error: the model did not run. NOT an observation.
    unavailable  HTTP 402 / 403 / 404 / 410: the model cannot be called at all. NOT an observation.

`answered`, `no_answer`, `timeout` are observations. They all enter the intention-to-treat tables with
F1 = 0 and their observed tokens; a timeout is never booked as zero tokens. `transport` and
`unavailable` are excluded and counted separately.
"""

from __future__ import annotations

import math
import random
import statistics as st
from collections import defaultdict
from collections.abc import Callable, Iterable

OBSERVED = ("answered", "no_answer", "timeout")
ARMS = ("P", "S", "T")


def dedupe(rows: Iterable[dict]) -> list[dict]:
    """One row per (model, arm, case).

    A retried cell appends a second row. The FIRST observation wins and is never replaced, so a cell
    cannot be re-rolled until it comes out favourably; a transport/unavailable row is replaced by any
    later row, because that cell never ran.
    """
    best: dict[tuple, dict] = {}
    for r in rows:
        k = (r["model"], r["arm"], r["case"])
        prev = best.get(k)
        if prev is None or prev["status"] not in OBSERVED:
            best[k] = r
    return list(best.values())


def cells(rows: Iterable[dict]) -> dict[tuple[str, str], dict[str, dict]]:
    """(model, case) -> {arm: observed row}, keeping only observed rows."""
    out: dict[tuple[str, str], dict[str, dict]] = defaultdict(dict)
    for r in dedupe(rows):
        if r["status"] in OBSERVED:
            out[(r["model"], r["case"])][r["arm"]] = r
    return out


def complete_triples(rows: Iterable[dict], arms: tuple[str, ...] = ARMS,
                     answered_only: bool = False) -> list[tuple[str, str, dict[str, dict]]]:
    """(model, case, {arm: row}) where every arm has an observation (and, optionally, an answer)."""
    out = []
    for (m, c), by_arm in sorted(cells(rows).items()):
        if all(a in by_arm for a in arms):
            if answered_only and any(by_arm[a]["status"] != "answered" for a in arms):
                continue
            out.append((m, c, {a: by_arm[a] for a in arms}))
    return out


def tokens_per_correct(rows: Iterable[dict]) -> float | None:
    """Σ observed tokens over ALL observed cells ÷ number correct. None when nothing was correct.

    Failures keep their observed tokens in the numerator and contribute nothing to the denominator,
    which is the point: an arm that gives up early does not look cheap.
    """
    rows = list(rows)
    ok = sum(1 for r in rows if r["correct"])
    if not ok:
        return None
    return sum(r["total_tok"] for r in rows) / ok


def sign_test(diffs: Iterable[float]) -> dict:
    """Exact two-sided binomial sign test. Zeros (ties) are dropped, as is conventional."""
    d = list(diffs)
    nz = [x for x in d if x != 0]
    n = len(nz)
    pos = sum(1 for x in nz if x > 0)
    if n == 0:
        return {"n": 0, "pos": 0, "neg": 0, "ties": len(d), "p": 1.0}
    k = min(pos, n - pos)
    p = min(1.0, 2 * sum(math.comb(n, i) for i in range(k + 1)) / 2 ** n)
    return {"n": n, "pos": pos, "neg": n - pos, "ties": len(d) - n, "p": p}


def summarize(xs: list[float]) -> dict:
    if not xs:
        return {"n": 0, "mean": None, "median": None}
    return {"n": len(xs), "mean": st.mean(xs), "median": st.median(xs)}


def paired_deltas(rows: Iterable[dict], a: str, b: str, field: str,
                  answered_only: bool = False, model: str | None = None) -> list[float]:
    """field(b) - field(a) over complete (a, b) pairs of one (model, case)."""
    out = []
    for m, _c, by in complete_triples(rows, (a, b), answered_only=answered_only):
        if model is None or m == model:
            out.append(by[b][field] - by[a][field])
    return out


def per_model_tpc(rows: list[dict], arm: str, cases: set[str] | None = None) -> dict[str, float | None]:
    """Tokens-per-correct per model for one arm, over complete triples (so arms see identical cells)."""
    acc: dict[str, list[dict]] = defaultdict(list)
    for m, c, by in complete_triples(rows):
        if cases is None or c in cases:
            acc[m].append(by[arm])
    return {m: tokens_per_correct(v) for m, v in acc.items()}


def geo_ratio(rows: list[dict], num: str, den: str, cases: set[str] | None = None) -> float | None:
    """Geometric mean over models of TPC(num)/TPC(den).

    Tokens are counted by each provider's own tokenizer, so a raw pooled sum would be dominated by
    whichever model tokenizes most finely. Ratios are taken WITHIN a model and only then averaged.
    """
    n, d = per_model_tpc(rows, num, cases), per_model_tpc(rows, den, cases)
    logs = [math.log(n[m] / d[m]) for m in n if n[m] and d.get(m)]
    return math.exp(st.mean(logs)) if logs else None


def bootstrap_ci(rows: list[dict], stat: Callable[[list[dict], set[str]], float | None],
                 n_boot: int = 2000, seed: int = 0, alpha: float = 0.05) -> dict:
    """Cluster bootstrap over CASES: a resample keeps every model and arm of a drawn case together,
    because the models share the cases and the three arms share a case. Draws where the statistic is
    undefined (an arm with no correct answer in the resample) are counted, not hidden."""
    rows = dedupe(rows)
    case_ids = sorted({c for _m, c, _ in complete_triples(rows)})
    if not case_ids:
        return {"lo": None, "hi": None, "n_undefined": 0, "n_boot": 0}
    rng = random.Random(seed)
    by_case: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_case[r["case"]].append(r)
    vals, undefined = [], 0
    for _ in range(n_boot):
        draw = [rng.choice(case_ids) for _ in case_ids]
        # re-key duplicated cases so each draw is its own cluster
        sample, keys = [], set()
        for j, c in enumerate(draw):
            tag = f"{c}~{j}"
            keys.add(tag)
            sample += [{**r, "case": tag} for r in by_case[c]]
        v = stat(sample, keys)
        if v is None:
            undefined += 1
        else:
            vals.append(v)
    if not vals:
        return {"lo": None, "hi": None, "n_undefined": undefined, "n_boot": n_boot}
    vals.sort()
    lo = vals[int(alpha / 2 * len(vals))]
    hi = vals[min(len(vals) - 1, int((1 - alpha / 2) * len(vals)))]
    return {"lo": lo, "hi": hi, "n_undefined": undefined, "n_boot": n_boot}
