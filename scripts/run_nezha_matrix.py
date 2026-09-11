"""3-arm matrix on Nezha Train Ticket — the first run on a dataset that did not author its own labels.

WHY THIS DATASET, AND WHAT CHANGES vs `run_cloud_matrix.py`:

`data/otel_demo` is a control, not a test: `infra/otel-demo/` patches a hand-written `logger.error`
into each fault origin, so the culprit is the only erroring service in 9 of 9 windows and
`errors_by_service()` argmax scores ~11/12 with no model in the loop. Nezha's faults are injected as
code-level `return`/`exception` mutations by the dataset's authors, and the culprit is the noisiest
service in only 5 of 24 Train Ticket windows (`results/NEZHA_REACHABILITY.md`). The digest shortcut
is therefore gone, which is the whole point.

PRE-REGISTERED BEFORE THE FIRST CELL (see `results/NEZHA_PREREG.md`):
  primary    cost_per_correct, per arm, pooled across models. Computed in `regen()` below.
  secondary  accuracy; median total_tok on ANSWERED cells; abort rate reported separately.
  contrasts  plain -> structured_no_trace   isolates service.name
             structured_no_trace -> structured   isolates trace_id
  strata     REACHABLE vs NOT (from results/runs/nezha_reach.jsonl). Trace context cannot help a
             window whose culprit shares no trace with any erroring service; folding those into one
             mean would dilute the effect being measured. Reported separately, never pooled away.

FIXED BEFORE THE FIRST CELL. Changing any of these means a NEW output file, not a resumed run.

Usage:
    .venv/bin/python scripts/run_nezha_matrix.py --smoke      # 1 model x 3 arms x 3 windows
    .venv/bin/python scripts/run_nezha_matrix.py              # full pre-registered matrix
    .venv/bin/python scripts/run_nezha_matrix.py --regen      # rebuild the doc from the jsonl
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from tokentax.methods.ollama_client import OllamaClient  # noqa: E402
from tokentax.methods.rlm import RLMMethod  # noqa: E402
from tokentax.nezha import (  # noqa: E402
    LOG_VISIBLE_TYPES,
    episodes_by_window,
    load_windows,
)

RAW = ROOT / "data/raw/Nezha/rca_data"
REACH = ROOT / "results/runs/nezha_reach.jsonl"
OUT = ROOT / "results/runs/nezha_matrix.jsonl"
DOC = ROOT / "results/NEZHA_MATRIX.md"


def _retag(tag: str) -> None:
    """A prompt change means a NEW run and a NEW file (hard rule), never a resumed one."""
    global OUT, DOC
    if tag:
        OUT = ROOT / f"results/runs/nezha_matrix_{tag}.jsonl"
        DOC = ROOT / f"results/NEZHA_MATRIX_{tag.upper()}.md"

TT_DATES = ["2023-01-29", "2023-01-30"]          # Train Ticket only; OnlineBoutique is out (5/14
                                                 # log-visible windows carry any error at all)
CONDITIONS = ("plain", "structured_no_trace", "structured")

# --- fixed before the first cell ---
CELL_TIMEOUT_S = 240.0
MAX_ROUNDS = 14
MAX_TOTAL_TOKENS = 250_000
NUM_CTX = 32_768
CONCURRENCY = 6
RETRY_CONCURRENCY = 2   # 429s on kimi-k3/glm-5.2 at 6; retries go slower, not differently
MATCHED_SCHEMAS = True                            # hard rule: identical tool schemas in every arm
N_NORMAL = 6                                      # control windows, >=5 min from any injection

MODELS = ["gpt-oss:120b", "qwen3.5:397b", "kimi-k3", "glm-5.2"]

START = time.time()


def log(m):
    print(f"[{time.time() - START:7.0f}s] {m}", flush=True)


def correct(pred: str, truth: str) -> bool:
    """Scorer, pre-registered. Normalises punctuation then requires the truth token to appear.

    Train Ticket has near-duplicate service names (`ts-travel-service` vs `ts-travel2-service`) that
    are genuinely different answers, and `RCA_RECOVERABILITY.md` shows models land on the sibling.
    Normalising to alphanumerics keeps them distinct: 'tstravelservice' is NOT a substring of
    'tstravel2service'. A give-up is scored as its own outcome, never credited as 'none'.
    """
    n = re.sub(r"[^a-z0-9]", "", str(pred).lower())
    if n in ("", "unknown", "unsure", "cannotdetermine"):
        return False
    if truth == "none":
        return n == "none" or n.startswith("no")
    return re.sub(r"[^a-z0-9]", "", truth) in n


def gave_up(pred: str) -> bool:
    return re.sub(r"[^a-z0-9]", "", str(pred).lower()) in ("", "unknown", "unsure", "cannotdetermine")


def load_cases() -> list[dict]:
    """Fault windows (log-visible types only) + normal control windows, Train Ticket only."""
    eps = episodes_by_window(RAW)
    reach = {}
    if REACH.exists():
        for line in REACH.read_text().splitlines():
            if line.strip():
                r = json.loads(line)
                reach[(r["window"], r["culprit"])] = r["reachable_via_trace"]

    cases, normals = [], []
    for date in TT_DATES:
        inject_minutes = {k.split("/")[1] for k in eps if k.startswith(date)}
        for w in load_windows(RAW / date):
            key = w.key
            these = eps.get(key, [])
            if these:
                ep = these[0]
                if ep["inject_type"] not in LOG_VISIBLE_TYPES:
                    continue
                cases.append({
                    "window": w, "key": key, "truth": ep["service"],
                    "fault_type": ep["inject_type"], "n_episodes": len(these),
                    "reachable": reach.get((key, ep["service"])),
                })
            else:
                # control: >=5 minutes from any injection in the same hour
                hh, mm = w.minute.split("_")
                far = all(abs(int(mm) - int(m.split("_")[1])) >= 5
                          for m in inject_minutes if m.split("_")[0] == hh)
                if far:
                    normals.append({"window": w, "key": key, "truth": "none",
                                    "fault_type": "normal", "n_episodes": 0, "reachable": None})
    step = max(1, len(normals) // N_NORMAL) if normals else 1
    return cases + normals[::step][:N_NORMAL]


def _raw_rows() -> list[dict]:
    if not OUT.exists():
        return []
    return [json.loads(x) for x in OUT.read_text().splitlines() if x.strip()]


# A transport failure is NOT an observation. A 429 means the model never ran, so the cell is still
# owed — unlike a timeout or a token-ceiling abort, which ARE observations of the model's behaviour
# and keep their measured cost. Retrying a 429 is resuming an unfinished run, not re-rolling a
# result that came out unfavourably; the distinction is what keeps this from being outcome-dependent
# stopping (WITHDRAWAL.md defect 2).
RETRYABLE = ("429", "Timeout", "ConnectError", "ReadError", "RemoteProtocolError")


def _is_retryable(err: str) -> bool:
    return bool(err) and any(t in err for t in RETRYABLE) and "timeout" != err


def done_keys() -> set:
    """Cells that need no further work: answered, or failed in a way that IS an observation."""
    return {(r["model"], r["condition"], r["window"])
            for r in _raw_rows() if not _is_retryable(r["error"])}


def dedupe(rows: list[dict]) -> list[dict]:
    """One row per cell. A retried cell appends a second row; prefer the answered one, else the last.

    Without this, a 429 row and its successful retry would both reach the means and the cell would
    be counted twice — once as a failure with total_tok=0.
    """
    best: dict[tuple, dict] = {}
    for r in rows:
        k = (r["model"], r["condition"], r["window"])
        prev = best.get(k)
        if prev is None or (prev["error"] and not r["error"]):
            best[k] = r
    return list(best.values())


async def run_cell(sem, model, cond, case):
    async with sem:
        client = OllamaClient(model=model, timeout=CELL_TIMEOUT_S, max_retries=2)
        method = RLMMethod(client, max_rounds=MAX_ROUNDS, max_total_tokens=MAX_TOTAL_TOKENS,
                           num_ctx=NUM_CTX, matched_schemas=MATCHED_SCHEMAS)
        w, truth = case["window"], case["truth"]
        t0 = time.perf_counter()
        err, res = "", None
        try:
            res = await asyncio.wait_for(
                method.apredict(w.records, cond, "root_cause"), timeout=CELL_TIMEOUT_S)
        except TimeoutError:
            err = "timeout"
        except Exception as e:  # noqa: BLE001 — record, never crash the matrix
            err = f"{type(e).__name__}: {e}"[:200]
        latency = time.perf_counter() - t0

        tools = [t["tool"] for t in (res.raw_trace or []) if "tool" in t] if res else []
        pred = res.prediction if res else ""
        row = {
            "model": model, "condition": cond, "window": case["key"], "truth": truth,
            "fault_type": case["fault_type"], "reachable": case["reachable"],
            "n_records": len(w.records),
            "pred": pred,
            "correct": bool(res and correct(pred, truth)),
            "gave_up": bool(res and gave_up(pred)),
            "in_tok": res.input_tokens if res else 0,
            "out_tok": res.output_tokens if res else 0,
            "total_tok": res.total_tokens if res else 0,
            "rounds": res.rlm_rounds if res else 0,
            "tools_used": tools, "first_tool": tools[0] if tools else "",
            "aborted": bool(res and res.aborted),
            "abort_reason": res.abort_reason if res else "",
            "latency_s": round(latency, 1), "error": err,
            "cfg": {"timeout": CELL_TIMEOUT_S, "max_rounds": MAX_ROUNDS, "num_ctx": NUM_CTX,
                    "matched_schemas": MATCHED_SCHEMAS},
        }
        with OUT.open("a") as f:
            f.write(json.dumps(row) + "\n")
        flag = "ok " if row["correct"] else ("ERR" if err else ("GAVE_UP" if row["gave_up"] else "MISS"))
        log(f"  {flag:7s} {model:16s} {cond:20s} {truth:24s} -> {pred[:24]:24s} "
            f"tok={row['total_tok']:<7,} r={row['rounds']} via={row['first_tool']}")
        return row


def regen():
    rows = dedupe(_raw_rows())
    if not rows:
        print("no rows yet")
        return
    import statistics as st

    def block(sub, title):
        out = ["", f"### {title} — {len(sub)} cells", "",
               "| condition | n | acc | gave_up | median_tok | mean_tok | fail | cost_per_correct |",
               "|---|---|---|---|---|---|---|---|"]
        for c in CONDITIONS:
            g = [r for r in sub if r["condition"] == c]
            if not g:
                continue
            ans = [r for r in g if not r["error"]]
            ok = sum(r["correct"] for r in g)
            toks = [r["total_tok"] for r in ans]
            med = f"{st.median(toks):,.0f}" if toks else "—"
            mean = f"{st.mean(toks):,.0f}" if toks else "—"
            cpc = f"{sum(toks) // ok:,}" if ok else "—"
            out.append(f"| {c} | {len(g)} | {ok / len(g):.2f} | {sum(r['gave_up'] for r in g)} "
                       f"| {med} | {mean} | {sum(1 for r in g if r['error'])} | {cpc} |")
        return out

    doc = [
        "# 3-arm matrix on Nezha Train Ticket",
        "",
        "Pre-registered in `results/NEZHA_PREREG.md` before the first cell. Raw: "
        "`results/runs/nezha_matrix.jsonl`. Harness: `scripts/run_nezha_matrix.py`.",
        "",
        f"Fixed config: timeout={CELL_TIMEOUT_S:.0f}s, max_rounds={MAX_ROUNDS}, "
        f"num_ctx={NUM_CTX:,}, matched_schemas={MATCHED_SCHEMAS}. {len(rows)} cells.",
        "",
        "`median_tok`/`mean_tok` cover ANSWERED cells only. `fail` is reported separately and is "
        "never folded in as a zero. A give-up (`unknown`) is scored as its own outcome and is NOT "
        "credited as a correct `none`.",
    ]
    doc += block(rows, "All cells")
    faults = [r for r in rows if r["truth"] != "none"]
    doc += block([r for r in faults if r["reachable"] is True], "Fault windows — culprit REACHABLE by trace_id")
    doc += block([r for r in faults if r["reachable"] is False], "Fault windows — culprit NOT reachable")
    doc += block([r for r in rows if r["truth"] == "none"], "Normal control windows")

    doc += ["", "## Per model", "",
            "| model | condition | n | acc | median_tok | fail |", "|---|---|---|---|---|---|"]
    agg = defaultdict(list)
    for r in rows:
        agg[(r["model"], r["condition"])].append(r)
    for (m, c), g in sorted(agg.items()):
        ans = [r for r in g if not r["error"]]
        toks = [r["total_tok"] for r in ans]
        med = f"{st.median(toks):,.0f}" if toks else "—"
        doc.append(f"| {m} | {c} | {len(g)} | {sum(r['correct'] for r in g) / len(g):.2f} | {med} "
                   f"| {sum(1 for r in g if r['error'])} |")

    ft = defaultdict(lambda: defaultdict(int))
    for r in rows:
        ft[r["condition"]][r["first_tool"] or "(none)"] += 1
    doc += ["", "## First tool called", ""]
    for c in CONDITIONS:
        if c in ft:
            doc.append(f"- **{c}**: " + ", ".join(f"{k}={v}" for k, v in
                                                  sorted(ft[c].items(), key=lambda kv: -kv[1])))
    DOC.write_text("\n".join(doc) + "\n")
    print(f"wrote {DOC}")


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true", help="1 model x 3 arms x 3 windows")
    ap.add_argument("--regen", action="store_true")
    ap.add_argument("--models", default="")
    ap.add_argument("--tag", default="", help="output suffix; a prompt/config change needs a new tag")
    ap.add_argument("--concurrency", type=int, default=0)
    ap.add_argument("--retry", action="store_true",
                    help="re-run only cells whose failure was a transport error (429/connect)")
    a = ap.parse_args()
    _retag(a.tag)

    if a.regen:
        regen()
        return 0
    local = "localhost" in os.getenv("OLLAMA_HOST", "") or "127.0.0.1" in os.getenv("OLLAMA_HOST", "")
    if not local and not os.getenv("OLLAMA_API_KEY"):
        print("OLLAMA_API_KEY not set (set -a; . ./.env; set +a)", file=sys.stderr)
        return 2

    cases = load_cases()
    models = [m.strip() for m in a.models.split(",") if m.strip()] or MODELS
    if a.smoke:
        models, cases = models[:1], cases[:2] + [c for c in cases if c["truth"] == "none"][:1]

    OUT.parent.mkdir(parents=True, exist_ok=True)
    done = done_keys()
    todo = [(m, c, case) for m in models for c in CONDITIONS for case in cases
            if (m, c, case["key"]) not in done]
    nf = sum(1 for c in cases if c["truth"] != "none")
    log(f"{len(cases)} windows ({nf} fault, {len(cases) - nf} normal) x {len(CONDITIONS)} arms "
        f"x {len(models)} models = {len(models) * len(CONDITIONS) * len(cases)} cells; "
        f"{len(done)} already done, {len(todo)} to run")

    sem = asyncio.Semaphore(a.concurrency or (RETRY_CONCURRENCY if a.retry else CONCURRENCY))
    await asyncio.gather(*(run_cell(sem, m, c, case) for m, c, case in todo))
    regen()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
