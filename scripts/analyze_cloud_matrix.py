"""Analysis for the corrected 3-arm cloud matrix.

Reports what the 2026-06 runs did not: medians alongside means (token distributions are heavily
right-skewed, so a mean is dominated by one flailing cell), PAIRED per-window differences between
arms, and bootstrap CIs on those differences. Pairing matters — arms are run on the same 12 windows,
so the paired difference is far lower-variance than the difference of means.

    .venv/bin/python scripts/analyze_cloud_matrix.py
"""

from __future__ import annotations

import json
import random
import statistics as st
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / "results/runs/cloud_matrix.jsonl"
DOC = ROOT / "results/CLOUD_ANALYSIS.md"
CONDITIONS = ("plain", "structured_no_trace", "structured")
SEED = 20260820


def boot_ci(vals, stat=st.median, n=10_000, alpha=0.05):
    if not vals:
        return (float("nan"), float("nan"))
    rng = random.Random(SEED)
    k = len(vals)
    reps = sorted(stat([vals[rng.randrange(k)] for _ in range(k)]) for _ in range(n))
    return (reps[int(alpha / 2 * n)], reps[int((1 - alpha / 2) * n)])


def main():
    if not RUN.exists():
        sys.exit(f"no run file at {RUN}")
    rows = [json.loads(x) for x in RUN.read_text().splitlines() if x.strip()]
    ok_rows = [r for r in rows if not r["error"]]

    out = ["# Corrected 3-arm matrix — analysis", "",
           f"{len(rows)} cells, {len(rows) - len(ok_rows)} failed. "
           f"Bootstrap: 10,000 resamples, seed {SEED}, 95% CI on the MEDIAN.", ""]

    # ---- per-condition distribution ----
    out += ["## Token cost by arm (answered cells)", "",
            "| condition | n | acc | mean | median | p90 | max | median 95% CI |",
            "|---|---|---|---|---|---|---|---|"]
    by_cond = defaultdict(list)
    acc = defaultdict(lambda: [0, 0])
    for r in rows:
        acc[r["condition"]][0] += int(r["correct"])
        acc[r["condition"]][1] += 1
    for r in ok_rows:
        by_cond[r["condition"]].append(r["total_tok"])
    for c in CONDITIONS:
        v = sorted(by_cond.get(c, []))
        if not v:
            continue
        lo, hi = boot_ci(v)
        p90 = v[min(len(v) - 1, int(0.9 * len(v)))]
        ok, n = acc[c]
        out.append(f"| {c} | {len(v)} | {ok / n:.2f} | {st.mean(v):,.0f} | {st.median(v):,.0f} | "
                   f"{p90:,.0f} | {max(v):,.0f} | [{lo:,.0f}, {hi:,.0f}] |")

    # ---- paired contrasts: the actual experiment ----
    idx = {(r["model"], r["condition"], r["window"]): r for r in ok_rows}
    pairs = [("plain", "structured_no_trace", "what `service.name` buys"),
             ("structured_no_trace", "structured", "what `trace_id` buys (service+severity held)"),
             ("plain", "structured", "both together")]
    out += ["", "## Paired contrasts — same model, same window", "",
            "Positive `median Δ` means the SECOND arm is cheaper. Ratio is median(b)/median(a) over "
            "pairs where both arms answered.", "",
            "| contrast | pairs | median Δ tok | 95% CI on median Δ | median ratio | acc a → b |",
            "|---|---|---|---|---|---|"]
    for a, b, _label in pairs:
        diffs, ratios, oka, okb = [], [], 0, 0
        for (m, c, w), ra in idx.items():
            if c != a:
                continue
            rb = idx.get((m, b, w))
            if rb is None:
                continue
            diffs.append(ra["total_tok"] - rb["total_tok"])
            if ra["total_tok"] > 0:
                ratios.append(rb["total_tok"] / ra["total_tok"])
            oka += int(ra["correct"])
            okb += int(rb["correct"])
        if not diffs:
            continue
        lo, hi = boot_ci(diffs)
        crosses = "yes" if lo <= 0 <= hi else "no"
        out.append(f"| {a} → {b} | {len(diffs)} | {st.median(diffs):,.0f} | "
                   f"[{lo:,.0f}, {hi:,.0f}] ({'crosses 0' if crosses == 'yes' else 'excludes 0'}) | "
                   f"{st.median(ratios):.2f}× | {oka}/{len(diffs)} → {okb}/{len(diffs)} |")

    # ---- paired ACCURACY contrasts ----
    out += ["", "## Paired accuracy contrasts", "",
            "| contrast | acc a → b | paired Δ | 95% CI | verdict |", "|---|---|---|---|---|"]
    rng = random.Random(SEED)
    all_idx = {(r["model"], r["condition"], r["window"]): r for r in rows}
    for a, b, _lab in pairs:
        pa, pb = [], []
        for (m, c, w), ra in all_idx.items():
            if c != a:
                continue
            rb = all_idx.get((m, b, w))
            if rb is None:
                continue
            pa.append(int(ra["correct"]))
            pb.append(int(rb["correct"]))
        k = len(pa)
        if not k:
            continue
        d = [pb[i] - pa[i] for i in range(k)]
        reps = sorted(st.mean([d[rng.randrange(k)] for _ in range(k)]) for _ in range(10_000))
        lo, hi = reps[250], reps[9750]
        verdict = "excludes 0" if (lo > 0 or hi < 0) else "crosses 0"
        out.append(f"| {a} → {b} | {sum(pa) / k:.3f} → {sum(pb) / k:.3f} | {st.mean(d):+.3f} | "
                   f"[{lo:+.3f}, {hi:+.3f}] | {verdict} |")

    # ---- what the misses look like ----
    out += ["", "## Misses", ""]
    for c in CONDITIONS:
        ms = [r for r in rows if r["condition"] == c and not r["correct"]]
        if not ms:
            out.append(f"- **{c}**: none")
            continue
        out.append(f"- **{c}** ({len(ms)}):")
        for r in ms:
            out.append(f"    - {r['model']} · truth={r['truth']} · pred={r['pred'][:40]!r} "
                       f"· {r['total_tok']:,} tok")

    # ---- per-model, to show whether the direction is consistent ----
    out += ["", "## Per-model median tokens (is the direction consistent?)", "",
            "| model | plain | structured_no_trace | structured | plain→struct |",
            "|---|---|---|---|---|"]
    bm = defaultdict(lambda: defaultdict(list))
    for r in ok_rows:
        bm[r["model"]][r["condition"]].append(r["total_tok"])
    for m in sorted(bm):
        cells = []
        for c in CONDITIONS:
            v = bm[m].get(c)
            cells.append(f"{st.median(v):,.0f}" if v else "—")
        p, s = bm[m].get("plain"), bm[m].get("structured")
        arrow = "—"
        if p and s:
            ratio = st.median(s) / st.median(p)
            arrow = f"{ratio:.2f}× {'cheaper' if ratio < 1 else 'MORE EXPENSIVE'}"
        out.append(f"| {m} | {cells[0]} | {cells[1]} | {cells[2]} | {arrow} |")

    # ---- failures + what tool answered ----
    fails = defaultdict(int)
    for r in rows:
        if r["error"]:
            fails[(r["model"], r["condition"])] += 1
    if fails:
        out += ["", "## Failures (never folded into token means)", ""]
        for (m, c), n in sorted(fails.items()):
            out.append(f"- {m} / {c}: {n}")
    else:
        out += ["", "## Failures", "", "None — every cell answered."]

    ft = defaultdict(lambda: defaultdict(int))
    for r in rows:
        ft[r["condition"]][r["first_tool"] or "(none)"] += 1
    out += ["", "## First tool called", ""]
    for c in CONDITIONS:
        if c in ft:
            out.append(f"- **{c}**: "
                       + ", ".join(f"{k}={v}" for k, v in sorted(ft[c].items(), key=lambda kv: -kv[1])))

    DOC.write_text("\n".join(out) + "\n")
    print("\n".join(out))


if __name__ == "__main__":
    main()
