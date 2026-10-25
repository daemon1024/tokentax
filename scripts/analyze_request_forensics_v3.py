"""Analysis of per-request forensics V3, exactly as results/REQUEST_FORENSICS_V3_PREREG.md specifies.

    .venv/bin/python scripts/analyze_request_forensics_v3.py            # -> request_forensics_v3_analysis.{json,md}

Per model x arm: observed cells, right answers (F1 >= 0.8), failures by status, tokens (median / mean over
all observed cells), tokens per right answer (TPC), rounds, and the share of runs that pointed grep / a
lookup at the request's own trace id. Per model, the pre-registered contrasts with their decision rules.
Models are never pooled. Owed cells (never observed) are counted and excluded; nothing is imputed.
"""

from __future__ import annotations

import json
import math
import statistics as st
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from tokentax.forensics_stats import OBSERVED, dedupe, sign_test, tokens_per_correct  # noqa: E402

RUN = ROOT / "results/runs/request_forensics_v3.jsonl"
V2 = ROOT / "results/runs/request_forensics_v2.jsonl"
ARMS = ("P", "S", "T", "Tt", "Th")
MODELS = ("beam", "deepseek-v4-pro:0813", "minimax-m3.1-flash")
N_SEEDS = 30
# (a, b, name): b is the arm with one more thing
CONTRASTS = [("S", "Tt", "printed id"), ("Tt", "T", "lookup"), ("T", "Th", "tell it"),
             ("S", "T", "printed id + lookup"), ("P", "S", "service.name")]


def read(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return dedupe(json.loads(x) for x in path.read_text().splitlines() if x.strip())


def obs(rows, model, arm):
    return [r for r in rows if r["model"] == model and r["arm"] == arm and r["status"] in OBSERVED]


def arm_stats(rows, model, arm) -> dict:
    rs = obs(rows, model, arm)
    all_cells = [r for r in rows if r["model"] == model and r["arm"] == arm]
    if not rs:
        return {"n_obs": 0, "n_rows": len(all_cells)}
    toks = [r["total_tok"] for r in rs]
    rounds = [r["rounds"] for r in rs]
    return {
        "n_obs": len(rs), "n_rows": len(all_cells), "owed": N_SEEDS - len(rs),
        "correct": sum(r["correct"] for r in rs),
        "answered": sum(r["status"] == "answered" for r in rs),
        "no_answer": sum(r["status"] == "no_answer" for r in rs),
        "timeout": sum(r["status"] == "timeout" for r in rs),
        "mean_f1": round(st.mean(r["f1"] for r in rs), 4),
        "tok_median": st.median(toks), "tok_mean": round(st.mean(toks)),
        "tok_sum": sum(toks),
        "tpc": (round(tokens_per_correct(rs)) if tokens_per_correct(rs) else None),
        "rounds_median": st.median(rounds), "rounds_mean": round(st.mean(rounds), 2),
        "grep_trace": sum(bool(r.get("grep_trace")) for r in rs),
        "lookup_trace": sum(bool(r.get("lookup_trace")) for r in rs),
        "not_available_mean": round(st.mean(r["n_not_available"] for r in rs), 2),
        "est_usd": round(sum(r.get("est_usd", 0.0) for r in rows if r["model"] == model and r["arm"] == arm), 3),
    }


def pairs(rows, model, a, b, answered_only=False):
    A = {r["case"]: r for r in obs(rows, model, a)}
    B = {r["case"]: r for r in obs(rows, model, b)}
    out = []
    for c in sorted(set(A) & set(B)):
        if answered_only and not (A[c]["status"] == B[c]["status"] == "answered"):
            continue
        out.append((A[c], B[c]))
    return out


def contrast(rows, model, a, b) -> dict:
    sa, sb = arm_stats(rows, model, a), arm_stats(rows, model, b)
    if not sa.get("n_obs") or not sb.get("n_obs"):
        return {"available": False}
    allp = pairs(rows, model, a, b)
    ansp = pairs(rows, model, a, b, answered_only=True)
    tpc_ratio = (sb["tpc"] / sa["tpc"]) if (sa.get("tpc") and sb.get("tpc")) else None
    ln_tok = [math.log(max(rb["total_tok"], 1) / max(ra["total_tok"], 1)) for ra, rb in ansp]
    f1_diff = st.mean(rb["f1"] - ra["f1"] for ra, rb in allp) if allp else None
    return {
        "available": True, "n_pairs": len(allp), "n_answered_pairs": len(ansp),
        "correct_a": sa["correct"], "correct_b": sb["correct"],
        "tpc_a": sa.get("tpc"), "tpc_b": sb.get("tpc"),
        "tpc_ratio_b_over_a": (round(tpc_ratio, 4) if tpc_ratio else None),
        "correct_sign": sign_test([int(rb["correct"]) - int(ra["correct"]) for ra, rb in allp]),
        "ln_tok_sign": sign_test(ln_tok),
        "ln_tok_mean": (round(st.mean(ln_tok), 4) if ln_tok else None),
        "rounds_sign": sign_test([rb["rounds"] - ra["rounds"] for ra, rb in allp]),
        "rounds_a_median": sa["rounds_median"], "rounds_b_median": sb["rounds_median"],
        "mean_f1_diff": (round(f1_diff, 4) if f1_diff is not None else None),
        "b_cheaper_in": sum(rb["total_tok"] < ra["total_tok"] for ra, rb in allp),
    }


def verdicts(c: dict, kind: str) -> str:
    """The PREREG's decision rules. b = the arm with one more thing."""
    if not c.get("available"):
        return "not run"
    noninf = c["mean_f1_diff"] is not None and c["mean_f1_diff"] >= -0.05
    r = c["tpc_ratio_b_over_a"]
    cs, ts, rs = c["correct_sign"], c["ln_tok_sign"], c["rounds_sign"]
    b_more_correct = cs["p"] < 0.05 and cs["pos"] > cs["neg"]
    b_cheaper = ts["p"] < 0.05 and ts["neg"] > ts["pos"]
    a_cheaper = ts["p"] < 0.05 and ts["pos"] > ts["neg"]
    if kind == "tell it":                       # primary: rounds; non-inferior F1
        if rs["p"] < 0.05 and rs["neg"] > rs["pos"] and noninf:
            return "supported (fewer rounds)"
        if rs["p"] < 0.05 and rs["pos"] > rs["neg"]:
            return "opposite (more rounds)"
        return "not shown"
    # every other contrast: b pays over a if TPC drops by >= 20%, F1 is non-inferior, and either the
    # correctness or the token sign test favours b at p < 0.05
    if r is None:
        if c["correct_b"] and not c["correct_a"]:
            return "supported (a never right)" if (b_more_correct and noninf) else "not shown (a never right)"
        return "not shown (no right answers)"
    if r <= 0.80 and noninf and (b_more_correct or b_cheaper):
        return "supported"
    if r >= 1.25 and (a_cheaper or (cs["p"] < 0.05 and cs["neg"] > cs["pos"])):
        return "opposite"
    return "not shown"


def drift(v3, v2) -> dict:
    """Not decision-bearing: V3's fresh controls against V2's cells, same model, same arm."""
    out = {}
    for m in ("beam", "minimax-m3.1-flash"):
        for arm in ("P", "S", "T"):
            a, b = arm_stats(v2, m, arm), arm_stats(v3, m, arm)
            if a.get("n_obs") and b.get("n_obs"):
                out[f"{m} {arm}"] = {"v2_correct": a["correct"], "v3_correct": b["correct"],
                                     "v2_tpc": a.get("tpc"), "v3_tpc": b.get("tpc"),
                                     "v2_tok_median": a["tok_median"], "v3_tok_median": b["tok_median"]}
    return out


def fmt(x):
    if x is None:
        return "–"
    if isinstance(x, float) and not x.is_integer():
        return f"{x:,.2f}"
    return f"{int(x):,}"


def main() -> int:
    rows = read(RUN)
    if not rows:
        print("no V3 rows yet", file=sys.stderr)
        return 1
    v2 = read(V2)
    out = {"run": str(RUN.relative_to(ROOT)), "n_rows": len(rows),
           "n_observed": sum(r["status"] in OBSERVED for r in rows),
           "not_observed": {s: sum(r["status"] == s for r in rows) for s in ("transport", "unavailable")},
           "est_usd": round(sum(r.get("est_usd", 0.0) for r in rows), 2),
           "arms": {}, "contrasts": {}, "drift_vs_v2": drift(rows, v2)}
    md = ["# Per-request forensics V3: analysis (generated; do not edit)", "",
          f"Rows: {out['n_rows']}, observed {out['n_observed']}, not observed {out['not_observed']}, "
          f"estimated spend ${out['est_usd']}.", ""]
    for m in MODELS:
        out["arms"][m] = {a: arm_stats(rows, m, a) for a in ARMS}
        md += [f"## {m}", "",
               "| arm | obs | right | no_answer | timeout | tok median | tok mean | tokens / right | rounds med | grep id | lookup id |",
               "|---|---|---|---|---|---|---|---|---|---|---|"]
        for a in ARMS:
            s = out["arms"][m][a]
            if not s.get("n_obs"):
                md.append(f"| {a} | 0 | | | | | | | | | |")
                continue
            md.append(f"| {a} | {s['n_obs']} | {s['correct']} | {s['no_answer']} | {s['timeout']} | "
                      f"{fmt(s['tok_median'])} | {fmt(s['tok_mean'])} | {fmt(s['tpc'])} | "
                      f"{fmt(s['rounds_median'])} | {s['grep_trace']} | {s['lookup_trace']} |")
        md += ["", "| contrast | pairs | right a→b | TPC a→b | ratio | correct sign p | tokens sign p | "
               "rounds med a→b | rounds sign p | ΔF1 | verdict |", "|---|---|---|---|---|---|---|---|---|---|---|"]
        out["contrasts"][m] = {}
        for a, b, name in CONTRASTS:
            c = contrast(rows, m, a, b)
            c["verdict"] = verdicts(c, name)
            out["contrasts"][m][f"{a}->{b}"] = {"name": name, **c}
            if not c.get("available"):
                md.append(f"| {a}→{b} ({name}) | | | | | | | | | | not run |")
                continue
            md.append(f"| {a}→{b} ({name}) | {c['n_pairs']} | {c['correct_a']}→{c['correct_b']} | "
                      f"{fmt(c['tpc_a'])}→{fmt(c['tpc_b'])} | {fmt(c['tpc_ratio_b_over_a'])} | "
                      f"{c['correct_sign']['p']:.3g} | {c['ln_tok_sign']['p']:.3g} | "
                      f"{fmt(c['rounds_a_median'])}→{fmt(c['rounds_b_median'])} | {c['rounds_sign']['p']:.3g} | "
                      f"{fmt(c['mean_f1_diff'])} | {c['verdict']} |")
        md.append("")
    if out["drift_vs_v2"]:
        md += ["## Fresh controls vs V2 (not decision-bearing)", "",
               "| model arm | right V2→V3 | TPC V2→V3 | tok median V2→V3 |", "|---|---|---|---|"]
        for k, d in out["drift_vs_v2"].items():
            md.append(f"| {k} | {d['v2_correct']}→{d['v3_correct']} | {fmt(d['v2_tpc'])}→{fmt(d['v3_tpc'])} | "
                      f"{fmt(d['v2_tok_median'])}→{fmt(d['v3_tok_median'])} |")
    stem = ROOT / "results/runs/request_forensics_v3_analysis"
    stem.with_suffix(".json").write_text(json.dumps(out, indent=1, default=str))
    stem.with_suffix(".md").write_text("\n".join(md) + "\n")
    print("\n".join(md))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
