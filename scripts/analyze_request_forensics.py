"""Pre-registered paired analysis of the per-request forensics run. See REQUEST_FORENSICS_PREREG.md.

    .venv/bin/python scripts/analyze_request_forensics.py                       # main run (+ replicate if present)
    .venv/bin/python scripts/analyze_request_forensics.py --baselines           # + model-free reference numbers
    .venv/bin/python scripts/analyze_request_forensics.py --main results/runs/request_forensics_smoke.jsonl

Every statistic is defined in `tokentax.forensics_stats` and was named in the pre-registration. Nothing is
added after the data are seen; extra descriptive tables are labelled DESCRIPTIVE.
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

# --- pre-registered decision constants ---
RATIO_MARGIN = 0.80          # T must be at least 20% cheaper per correct answer than S
REPLICATE_TOL = 0.20         # replicate ratio may differ from the main-run ratio by < this
F1_NONINFERIORITY = -0.05    # mean paired F1(T) - F1(S) must be >= this
ALPHA = 0.05
N_BOOT = 5000
BOOT_SEED = 20261020


def read(path: Path) -> list[dict]:
    return [json.loads(x) for x in path.read_text().splitlines() if x.strip()] if path.exists() else []


def fmt(x, nd=3):
    return "—" if x is None else (f"{x:,.{nd}f}" if isinstance(x, float) else f"{x:,}")


def accounting(rows: list[dict]) -> list[str]:
    rows = S.dedupe(rows)
    c = Counter((r["model"], r["arm"], r["status"]) for r in rows)
    statuses = ("answered", "no_answer", "timeout", "transport", "unavailable")
    out = ["| model | arm | " + " | ".join(statuses) + " |", "|---|---|" + "---|" * len(statuses)]
    for m in sorted({r["model"] for r in rows}):
        for a in S.ARMS:
            out.append(f"| {m} | {a} | " + " | ".join(str(c[(m, a, s)]) for s in statuses) + " |")
    return out


def arm_table(rows: list[dict], model: str | None = None) -> list[str]:
    triples = [t for t in S.complete_triples(rows) if model is None or t[0] == model]
    out = ["| arm | cells | correct (F1>=0.8) | mean F1 | median F1 | F1==1 | F1>=0.5 | fail | "
           "median tok (answered) | mean tok (answered) | mean tok (all observed) | tokens/correct | "
           "mean rounds | not-available calls/cell |",
           "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for a in S.ARMS:
        rs = [t[2][a] for t in triples]
        if not rs:
            continue
        ans = [r for r in rs if r["status"] == "answered"]
        f1 = [r["f1"] for r in rs]
        tpc = S.tokens_per_correct(rs)
        out.append(
            f"| {a} | {len(rs)} | {sum(r['correct'] for r in rs)} | {st.mean(f1):.3f} | {st.median(f1):.3f} | "
            f"{sum(1 for r in rs if r['f1'] >= 0.9999)} | {sum(1 for r in rs if r['f1'] >= 0.5)} | "
            f"{len(rs) - len(ans)} | "
            f"{fmt(st.median([r['total_tok'] for r in ans]) if ans else None, 0)} | "
            f"{fmt(st.mean([r['total_tok'] for r in ans]) if ans else None, 0)} | "
            f"{fmt(st.mean([r['total_tok'] for r in rs]), 0)} | {fmt(tpc, 0)} | "
            f"{st.mean([r['rounds'] for r in rs]):.1f} | {st.mean([r['n_not_available'] for r in rs]):.2f} |")
    return out


def case_level(rows: list[dict], a: str, b: str, field: str, log_ratio: bool, answered_only: bool):
    """One number per CASE (averaged over the models that have the pair): the independent unit."""
    per_case: dict[str, list[float]] = defaultdict(list)
    for _m, c, by in S.complete_triples(rows, (a, b), answered_only=answered_only):
        if log_ratio:
            if by[a][field] > 0 and by[b][field] > 0:
                per_case[c].append(math.log(by[b][field] / by[a][field]))
        else:
            per_case[c].append(by[b][field] - by[a][field])
    return {c: st.mean(v) for c, v in per_case.items()}


def contrast(rows: list[dict], a: str, b: str) -> dict:
    """b relative to a (T vs S means a='S', b='T')."""
    out: dict = {"a": a, "b": b, "per_model": {}}
    models = sorted({r["model"] for r in rows})
    for m in models:
        df1 = S.paired_deltas(rows, a, b, "f1", model=m)
        dtk = S.paired_deltas(rows, a, b, "total_tok", answered_only=True, model=m)
        ra, rb = S.per_model_tpc(rows, a).get(m), S.per_model_tpc(rows, b).get(m)
        out["per_model"][m] = {
            "dF1": {**S.summarize(df1), "sign": S.sign_test(df1)},
            "dTok_answered": {**S.summarize(dtk), "sign": S.sign_test(dtk)},
            "tpc_a": ra, "tpc_b": rb, "tpc_ratio": (rb / ra) if (ra and rb) else None,
        }
    cf1 = case_level(rows, a, b, "f1", False, False)
    ctk = case_level(rows, a, b, "total_tok", True, True)
    out["case_dF1"] = {**S.summarize(list(cf1.values())), "sign": S.sign_test(cf1.values())}
    out["case_dlogTok_answered"] = {**S.summarize(list(ctk.values())), "sign": S.sign_test(ctk.values()),
                                    "geo_ratio": math.exp(st.mean(ctk.values())) if ctk else None}
    out["tpc_geo_ratio"] = S.geo_ratio(rows, b, a)
    out["tpc_ci"] = S.bootstrap_ci(rows, lambda r, cs: S.geo_ratio(r, b, a, cs), N_BOOT, BOOT_SEED)
    return out


def contrast_md(c: dict) -> list[str]:
    a, b = c["a"], c["b"]
    out = [f"**{b} vs {a}**  (deltas are {b} minus {a})", "",
           "| scope | n pairs | dF1 mean | dF1 median | F1 sign (+/-/ties, p) | n answered pairs | "
           "dTok median | dTok mean | tok sign (+/-, p) | TPC ratio |",
           "|---|---|---|---|---|---|---|---|---|---|"]
    for m, v in c["per_model"].items():
        d, t = v["dF1"], v["dTok_answered"]
        sg, tg = d["sign"], t["sign"]
        out.append(f"| {m} | {d['n']} | {fmt(d['mean'])} | {fmt(d['median'])} | "
                   f"{sg['pos']}/{sg['neg']}/{sg['ties']}, p={sg['p']:.3f} | {t['n']} | "
                   f"{fmt(t['median'], 0)} | {fmt(t['mean'], 0)} | {tg['pos']}/{tg['neg']}, p={tg['p']:.3f} | "
                   f"{fmt(v['tpc_ratio'])} |")
    d, t = c["case_dF1"], c["case_dlogTok_answered"]
    out.append(f"| **by case (mean over models)** | {d['n']} | {fmt(d['mean'])} | {fmt(d['median'])} | "
               f"{d['sign']['pos']}/{d['sign']['neg']}/{d['sign']['ties']}, p={d['sign']['p']:.3f} | {t['n']} | "
               f"geo-ratio {fmt(t['geo_ratio'])} | | {t['sign']['pos']}/{t['sign']['neg']}, "
               f"p={t['sign']['p']:.3f} | **{fmt(c['tpc_geo_ratio'])}** |")
    ci = c["tpc_ci"]
    out += ["", f"Geometric-mean (over models) tokens-per-correct ratio {b}/{a} = **{fmt(c['tpc_geo_ratio'])}**, "
            f"95% cluster-bootstrap CI [{fmt(ci['lo'])}, {fmt(ci['hi'])}] "
            f"({ci['n_boot'] - ci['n_undefined']}/{ci['n_boot']} draws defined)."]
    return out


def falsification(rows: list[dict], rep_rows: list[dict], models: list[str]) -> dict:
    ts = contrast(rows, "S", "T")
    ratio, ci = ts["tpc_geo_ratio"], ts["tpc_ci"]
    f1_mean = ts["case_dF1"]["mean"]
    checks = {
        "FALS_cost_margin": {"rule": f"geo-mean TPC ratio T/S <= {RATIO_MARGIN}",
                           "value": ratio, "fires": ratio is None or ratio > RATIO_MARGIN},
        "FALS_ci": {"rule": "bootstrap 95% CI upper bound < 1.0", "value": ci["hi"],
                  "fires": ci["hi"] is None or ci["hi"] >= 1.0},
        "FALS_noninferior": {"rule": f"mean case-level dF1(T-S) >= {F1_NONINFERIORITY}",
                           "value": f1_mean, "fires": f1_mean is None or f1_mean < F1_NONINFERIORITY},
    }
    rep_models = sorted({r["model"] for r in rep_rows})
    if rep_models:
        m = rep_models[0]
        main_r = ts["per_model"].get(m, {}).get("tpc_ratio")
        rep_s, rep_t = S.per_model_tpc(rep_rows, "S").get(m), S.per_model_tpc(rep_rows, "T").get(m)
        rep_r = (rep_t / rep_s) if (rep_s and rep_t) else None
        ok = (main_r is not None and rep_r is not None and rep_r <= 1.0
              and abs(main_r - rep_r) < REPLICATE_TOL)
        checks["FALS_replicate"] = {
            "rule": f"{m}: replicate T/S ratio <= 1.0 and within {REPLICATE_TOL} of the main-run ratio",
            "value": {"main": main_r, "replicate": rep_r}, "fires": not ok}
    else:
        checks["FALS_replicate"] = {"rule": "replicate required", "value": None, "fires": True,
                                  "note": "no replicate on disk: the effect cannot be separated from noise"}
    fired = [k for k, v in checks.items() if v["fires"]]
    a1 = ts["case_dF1"]
    superior = bool(a1["mean"] is not None and a1["mean"] > 0 and a1["sign"]["p"] < ALPHA)
    return {"checks": checks, "fired": fired, "falsification_fires": bool(fired),
            "T_raises_F1_over_S": superior, "contrast": ts}


def strata(rows: list[dict]) -> list[str]:
    out = ["| fault stratum | arm | cells | correct | mean F1 | median F1 | mean tok (all observed) |",
           "|---|---|---|---|---|---|---|"]
    triples = S.complete_triples(rows)
    for fault in sorted({t[2]["P"]["fault"] for t in triples}):
        for a in S.ARMS:
            rs = [t[2][a] for t in triples if t[2]["P"]["fault"] == fault]
            out.append(f"| {fault} | {a} | {len(rs)} | {sum(r['correct'] for r in rs)} | "
                       f"{st.mean([r['f1'] for r in rs]):.3f} | {st.median([r['f1'] for r in rs]):.3f} | "
                       f"{st.mean([r['total_tok'] for r in rs]):,.0f} |")
    return out


def tool_use(rows: list[dict]) -> list[str]:
    out = ["| arm | first tool | share of cells |", "|---|---|---|"]
    triples = S.complete_triples(rows)
    for a in S.ARMS:
        c = Counter(t[2][a]["first_tool"] or "(none)" for t in triples)
        n = sum(c.values())
        for tool, k in c.most_common(4):
            out.append(f"| {a} | {tool} | {k / n:.0%} |")
    out += ["", "| arm | cells calling lines_for_trace | cells calling lines_near | cells calling grep | "
            "cells with >=1 not-available reply |", "|---|---|---|---|---|"]
    for a in S.ARMS:
        rs = [t[2][a] for t in triples]
        n = len(rs)
        out.append(f"| {a} | {sum('lines_for_trace' in r['tools_used'] for r in rs)}/{n} | "
                   f"{sum('lines_near' in r['tools_used'] for r in rs)}/{n} | "
                   f"{sum('grep' in r['tools_used'] for r in rs)}/{n} | "
                   f"{sum(r['n_not_available'] > 0 for r in rs)}/{n} |")
    return out


def root_table(rows: list[dict]) -> list[str]:
    out = ["| arm | root-service exact match (answered cells) | predictor `seed's own service` |", "|---|---|---|"]
    triples = S.complete_triples(rows)
    base = sum(1 for t in triples if t[2]["P"]["seed_service"] == t[2]["P"]["truth_root"])
    for a in S.ARMS:
        rs = [t[2][a] for t in triples if t[2][a]["status"] == "answered"]
        out.append(f"| {a} | {sum(r['root_correct'] for r in rs)}/{len(rs)} | {base}/{len(triples)} |")
    return out


def baselines() -> list[str]:
    """MODEL-FREE reference numbers: how well does a time window alone recover the request, and what does
    reading it cost, against the mechanical `lines_for_trace` lower bound."""
    import tiktoken

    from tokentax import forensics as F
    from tokentax.otel_loader import windows_from_manifest
    enc = tiktoken.get_encoding("cl100k_base")
    cases_doc = json.loads((ROOT / "results/runs/request_forensics_cases.json").read_text())
    windows = windows_from_manifest(ROOT / "data/otel_demo/logs.jsonl",
                                    ROOT / "data/otel_demo/manifest_multifault.json")
    el = {c.key: c for c in F.eligible_cases(windows)}
    cases = [el[c["key"]] for c in cases_doc["main"]]
    out = ["| W (s) | lines in window, median | time-window-only F1, mean | F1>=0.8 | tokens to read that window (cl100k), median |",
           "|---|---|---|---|---|"]
    for w in (0.05, 0.1, 0.25, 0.5, 1.0):
        f1s, nl, tk = [], [], []
        for c in cases:
            recs = windows[c.window_idx].records
            t0 = recs[c.seed_idx].time_unix_nano
            idx = [i for i, r in enumerate(recs) if abs(r.time_unix_nano - t0) <= w * 1e9]
            f1s.append(F.score_lines(idx, c)["f1"])
            nl.append(len(idx))
            tk.append(sum(len(enc.encode(recs[i].to_plain())) for i in idx))
        out.append(f"| {w} | {st.median(nl):.0f} | {st.mean(f1s):.3f} | {sum(f >= 0.8 for f in f1s)}/{len(f1s)} | "
                   f"{st.median(tk):,.0f} |")
    tr = [sum(len(enc.encode(windows[c.window_idx].records[i].to_plain())) for i in c.truth) for c in cases]
    win = [sum(len(enc.encode(r.to_plain())) for r in windows[c.window_idx].records[::25]) * 25
           for c in cases[:6]]
    out += ["", f"Tokens in the exact lines of the request (what `lines_for_trace` returns, plain bodies): "
            f"median {st.median(tr):,.0f}, max {max(tr):,}. Whole window (cl100k estimate from every 25th line, "
            f"first 6 cases): ~{st.median(win):,.0f}."]
    # span of the request in time
    spans = []
    for c in cases:
        recs = windows[c.window_idx].records
        ts = [recs[i].time_unix_nano for i in (*c.truth, c.seed_idx)]
        spans.append((max(ts) - min(ts)) / 1e6)
    out.append(f"Time span of the request (first to last line): median {st.median(spans):,.0f} ms, "
               f"max {max(spans):,.0f} ms.")
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--main", default=str(ROOT / "results/runs/request_forensics.jsonl"))
    ap.add_argument("--rep", default=str(ROOT / "results/runs/request_forensics_rep2.jsonl"))
    ap.add_argument("--baselines", action="store_true")
    ap.add_argument("--json", default="")
    a = ap.parse_args()
    rows, rep = read(Path(a.main)), read(Path(a.rep))
    if not rows:
        print("no rows")
        return 1
    models = sorted({r["model"] for r in rows})
    triples = S.complete_triples(rows)
    P = lambda *xs: print(*xs, sep="\n")  # noqa: E731

    P(f"# analysis of {Path(a.main).name}", "",
      f"{len(S.dedupe(rows))} deduped cells; {len(triples)} complete (model, case) triples "
      f"over {len({t[1] for t in triples})} cases; models: {', '.join(models)}", "",
      "## Cell accounting (transport/unavailable are NOT observations and are excluded below)", "",
      *accounting(rows), "", "## Arms, intention-to-treat over complete triples (pooled over models)", "",
      *arm_table(rows), "")
    for m in models:
        P(f"### {m}", "", *arm_table(rows, m), "")
    for x, y in (("S", "T"), ("P", "S"), ("P", "T")):
        P(f"## Paired contrast {y} vs {x}", "", *contrast_md(contrast(rows, x, y)), "")
    fz = falsification(rows, rep, models)
    P("## Pre-registered falsification checks (T vs S)", "")
    for k, v in fz["checks"].items():
        val = v["value"]
        P(f"- {k}: {v['rule']} -> value {json.dumps(val) if isinstance(val, dict) else fmt(val)} "
          f"-> {'FIRES' if v['fires'] else 'holds'}" + (f" ({v['note']})" if v.get("note") else ""))
    P("", f"**Falsification condition fires: {fz['falsification_fires']}** (fired: {fz['fired'] or 'none'}). "
      f"T raises F1 over S (case-level mean dF1 > 0 and sign p < {ALPHA}): {fz['T_raises_F1_over_S']}.", "",
      "## DESCRIPTIVE: by fault stratum", "", *strata(rows), "",
      "## DESCRIPTIVE: tool use", "", *tool_use(rows), "",
      "## SECONDARY: root service", "", *root_table(rows), "")
    ctx = Counter()
    for r in S.dedupe(rows):
        ctx[r["max_prompt_tok"] > r["cfg"]["num_ctx"]] += 1
    P(f"max single-round prompt vs num_ctx: {ctx[True]} of {sum(ctx.values())} cells exceeded num_ctx "
      f"(provider-counted tokens; largest {max(r['max_prompt_tok'] for r in rows):,}).", "")
    if rep:
        P("## Replicate (noise)", "", *accounting(rep), "", *arm_table(rep), "")
    if a.baselines:
        P("## MODEL-FREE reference (no LLM)", "", *baselines(), "")
    if a.json:
        Path(a.json).write_text(json.dumps(fz, indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
