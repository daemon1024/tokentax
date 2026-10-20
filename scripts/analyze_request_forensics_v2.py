"""Pre-registered analysis of per-request forensics V2 (results/REQUEST_FORENSICS_V2_PREREG.md).

    .venv/bin/python scripts/analyze_request_forensics_v2.py                 # main (+ replicate if present)
    .venv/bin/python scripts/analyze_request_forensics_v2.py --main results/runs/request_forensics_v2_smoke.jsonl

Every statistic comes from `tokentax.forensics_stats` (unit-tested) and is named in the pre-registration.
Analysis units: COMPLETE QUADRUPLES, i.e. (model, seed) where all four arms P / S / T / TI were observed,
so every arm is compared on identical cells. Failures (no_answer / timeout) are observations: F1 = 0,
tokens kept, never zero-filled. transport / unavailable rows are not observations and are only counted.
"""

from __future__ import annotations

import argparse
import json
import math
import statistics as st
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from tokentax import forensics_stats as S  # noqa: E402

ARMS = ("P", "S", "T", "TI")
# --- pre-registered decision constants (same values as V1 where V1 had them) ---
RATIO_MARGIN = 0.80          # an index arm must be >= 20% cheaper per correct answer than S
F1_NONINFERIORITY = -0.05    # mean case-level F1(arm) - F1(S) must be >= this
ALPHA = 0.05
N_BOOT = 5000
BOOT_SEED = 20261020


def read(path: Path) -> list[dict]:
    return [json.loads(x) for x in path.read_text().splitlines() if x.strip()] if path.exists() else []


def quads(rows, arms=ARMS, answered_only=False):
    return S.complete_triples(rows, arms, answered_only=answered_only)


def tpc_by_model(rows, arm, cases=None) -> dict[str, float | None]:
    acc: dict[str, list[dict]] = defaultdict(list)
    for m, c, by in quads(rows):
        if cases is None or c in cases:
            acc[m].append(by[arm])
    return {m: S.tokens_per_correct(v) for m, v in acc.items()}


def geo_ratio(rows, num, den, cases=None) -> float | None:
    """Geometric mean over models of TPC(num)/TPC(den) (within-model first: tokenizers differ)."""
    n, d = tpc_by_model(rows, num, cases), tpc_by_model(rows, den, cases)
    logs = [math.log(n[m] / d[m]) for m in n if n[m] and d.get(m)]
    return math.exp(st.mean(logs)) if logs else None


def case_level(rows, a, b, field, log_ratio=False, answered_only=False) -> dict[str, float]:
    """Per seed: mean over models of field(b)-field(a), or of ln(field(b)/field(a))."""
    per: dict[str, list[float]] = defaultdict(list)
    for _m, c, by in quads(rows, (a, b), answered_only=answered_only):
        x, y = by[a][field], by[b][field]
        if log_ratio:
            if x > 0 and y > 0:
                per[c].append(math.log(y / x))
        else:
            per[c].append(y - x)
    return {c: st.mean(v) for c, v in per.items() if v}


def contrast(rows, a, b) -> dict:
    """b vs a: TPC ratio (+ cluster-bootstrap CI), F1 delta + sign test, token ln-ratio + sign test."""
    qcases = {c for _m, c, _ in quads(rows)}
    sub = [r for r in rows if r["case"] in qcases and r["arm"] in (a, b)]
    ratio = geo_ratio(rows, b, a)

    def stat(sample, keys):
        return geo_ratio(sample, b, a, keys)
    ci = S.bootstrap_ci([r for r in rows if r["case"] in qcases], stat, n_boot=N_BOOT, seed=BOOT_SEED) \
        if ratio is not None else {"lo": None, "hi": None, "n_undefined": None, "n_boot": 0}
    df1 = case_level([r for r in rows if r["case"] in qcases], a, b, "f1")
    dtok = case_level([r for r in rows if r["case"] in qcases], a, b, "total_tok", log_ratio=True,
                      answered_only=True)
    return {"a": a, "b": b, "tpc_ratio": ratio, "ci": ci,
            "mean_df1": st.mean(df1.values()) if df1 else None, "df1_sign": S.sign_test(df1.values()),
            "median_ln_tok_ratio": st.median(dtok.values()) if dtok else None,
            "tok_sign": S.sign_test(dtok.values()), "n_cases_f1": len(df1), "n_cases_tok": len(dtok),
            "n_rows": len(sub)}


def index_arm_verdict(c: dict) -> dict:
    """Pre-registered: an index arm (T or TI) 'pays' vs S iff NONE of these fires."""
    fired = []
    if c["tpc_ratio"] is None or c["tpc_ratio"] > RATIO_MARGIN:
        fired.append(f"TPC ratio {c['tpc_ratio']} > {RATIO_MARGIN} (or undefined)")
    if c["ci"]["hi"] is None or c["ci"]["hi"] >= 1.0:
        fired.append(f"bootstrap CI upper {c['ci']['hi']} >= 1.0 (or undefined)")
    if c["mean_df1"] is None or c["mean_df1"] < F1_NONINFERIORITY:
        fired.append(f"mean dF1 {c['mean_df1']} < {F1_NONINFERIORITY}")
    return {"pays": not fired, "fired": fired}


def replicate_checks(main, rep) -> dict:
    """Noise replicate (model 1, arms T and TI only): does the headline survive a second run?

    H1/H2 replicate condition: TPC(arm, replicate) / TPC(S, main) must still be <= RATIO_MARGIN.
    TI-vs-T: the run-to-run spread |ln TPC(rep)/TPC(main)| of T and of TI bounds what a TI-vs-T
    difference must exceed to be called real.
    """
    if not rep:
        return {"present": False}
    m = sorted({r["model"] for r in rep})[0]
    mrows = [r for r in main if r["model"] == m]
    qcases = {c for _m, c, _ in quads(mrows)}
    out = {"present": True, "model": m}
    s_main = S.tokens_per_correct([r for r in S.dedupe(mrows) if r["arm"] == "S" and r["case"] in qcases
                                   and r["status"] in S.OBSERVED])
    for arm in ("T", "TI"):
        tm = S.tokens_per_correct([r for r in S.dedupe(mrows) if r["arm"] == arm and r["case"] in qcases
                                   and r["status"] in S.OBSERVED])
        tr = S.tokens_per_correct([r for r in S.dedupe(rep) if r["arm"] == arm and r["case"] in qcases
                                   and r["status"] in S.OBSERVED])
        out[arm] = {"tpc_main": tm, "tpc_rep": tr,
                    "rep_over_S_main": (tr / s_main) if (tr and s_main) else None,
                    "abs_ln_rep_main": abs(math.log(tr / tm)) if (tr and tm) else None}
    return out


def accounting(rows) -> list[str]:
    c = Counter((r["model"], r["arm"], r["status"]) for r in S.dedupe(rows))
    sts = ("answered", "no_answer", "timeout", "transport", "unavailable")
    out = ["| model | arm | " + " | ".join(sts) + " |", "|---|---|" + "---|" * len(sts)]
    for m in sorted({r["model"] for r in rows}):
        for a in ARMS:
            out.append(f"| {m} | {a} | " + " | ".join(str(c[(m, a, s)]) for s in sts) + " |")
    return out


def arm_table(rows, model=None) -> list[str]:
    q = [t for t in quads(rows) if model is None or t[0] == model]
    out = ["| arm | cells | correct | mean F1 | failures (no_answer/timeout) | median tok (answered) | "
           "mean tok (answered) | mean tok (all observed) | tokens/correct | mean rounds |",
           "|---|---|---|---|---|---|---|---|---|---|"]
    for a in ARMS:
        rs = [by[a] for _m, _c, by in q]
        ans = [r["total_tok"] for r in rs if r["status"] == "answered"]
        fails = sum(1 for r in rs if r["status"] != "answered")
        tpc = S.tokens_per_correct(rs)
        f = lambda v: f"{v:,.0f}" if v is not None else "—"
        out.append(f"| {a} | {len(rs)} | {sum(r['correct'] for r in rs)} | "
                   f"{(st.mean(r['f1'] for r in rs) if rs else 0):.3f} | {fails} | "
                   f"{f(st.median(ans) if ans else None)} | {f(st.mean(ans) if ans else None)} | "
                   f"{f(st.mean(r['total_tok'] for r in rs) if rs else None)} | {f(tpc)} | "
                   f"{(st.mean(r['rounds'] for r in rs) if rs else 0):.1f} |")
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--main", default=str(ROOT / "results/runs/request_forensics_v2.jsonl"))
    ap.add_argument("--rep", default=str(ROOT / "results/runs/request_forensics_v2_rep2.jsonl"))
    ap.add_argument("--json", default="")
    a = ap.parse_args()
    rows = S.dedupe(read(Path(a.main)))
    rep = S.dedupe(read(Path(a.rep)))
    if not rows:
        print("no rows")
        return 1
    print("## Accounting (every row, deduplicated; first observation wins)\n")
    print("\n".join(accounting(rows)))
    q = quads(rows)
    print(f"\ncomplete quadruples: {len(q)} over {len({m for m, _, _ in q})} model(s), "
          f"{len({c for _, c, _ in q})} seed(s)\n")
    print("## All models (complete quadruples)\n")
    print("\n".join(arm_table(rows)))
    for m in sorted({m for m, _, _ in q}):
        print(f"\n### {m}\n")
        print("\n".join(arm_table(rows, m)))
    res = {}
    print("\n## Contrasts (b vs a)\n")
    for x, y in (("S", "T"), ("S", "TI"), ("T", "TI"), ("P", "S"), ("P", "T"), ("P", "TI")):
        c = contrast(rows, x, y)
        res[f"{x}->{y}"] = c
        print(f"- {x} -> {y}: TPC ratio {c['tpc_ratio']}, 95% CI [{c['ci']['lo']}, {c['ci']['hi']}] "
              f"(undefined draws {c['ci']['n_undefined']}); mean dF1 {c['mean_df1']} "
              f"(sign {c['df1_sign']}); median ln tok ratio (answered pairs) {c['median_ln_tok_ratio']} "
              f"(sign {c['tok_sign']})")
    h1, h2 = index_arm_verdict(res["S->T"]), index_arm_verdict(res["S->TI"])
    rc = replicate_checks(rows, rep)
    for name, h, arm in (("H1 (T vs S)", h1, "T"), ("H2 (TI vs S)", h2, "TI")):
        if rc.get("present"):
            r = rc[arm]["rep_over_S_main"]
            if r is None or r > RATIO_MARGIN:
                h["fired"].append(f"replicate TPC({arm})/TPC(S) = {r} > {RATIO_MARGIN}")
                h["pays"] = False
        else:
            h["replicated"] = False
        print(f"\n{name}: {'PAYS' if h['pays'] else 'FALSIFICATION FIRED'}; fired = {h['fired']}"
              f"{'' if rc.get('present') else ' (no replicate yet: not confirmed)'}")
    ti_t = res["T->TI"]
    noise = max((rc[a]["abs_ln_rep_main"] or 0) for a in ("T", "TI")) if rc.get("present") else None
    h3 = (ti_t["tpc_ratio"] is not None and ti_t["tpc_ratio"] < 1.0 and ti_t["tok_sign"]["p"] < ALPHA
          and ti_t["mean_df1"] is not None and ti_t["mean_df1"] >= F1_NONINFERIORITY
          and noise is not None and abs(math.log(ti_t["tpc_ratio"])) > noise)
    print(f"\nH3 (TI cheaper than T): {'YES' if h3 else 'NOT SHOWN'}; ratio {ti_t['tpc_ratio']}, "
          f"tok sign p {ti_t['tok_sign']['p']}, mean dF1 {ti_t['mean_df1']}, replicate noise |ln| {noise}")
    if a.json:
        Path(a.json).write_text(json.dumps({"contrasts": res, "H1": h1, "H2": h2, "H3": h3,
                                            "replicate": rc}, indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
