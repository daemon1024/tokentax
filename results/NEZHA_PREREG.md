# Pre-registration — 3-arm matrix on Nezha Train Ticket

**Written before the first cell of the full run.** `WITHDRAWAL.md` withdrew the previous
pre-registration because the committed test was never executed and the headline metric appeared in no
line of Python. This document is written against code that already exists: every quantity below is
computed by `scripts/run_nezha_matrix.py::regen`, and the scorer is
`run_nezha_matrix.py::correct`, both committed before the run.

Harness validated by a 9-cell smoke on 2026-09-11 (1 model x 3 arms x 3 windows). Those cells share
the fixed config below and are retained in the output file rather than deleted.

## Why Nezha Train Ticket

`data/otel_demo` cannot test the hypothesis. `infra/otel-demo/` patches a hand-authored
`logger.error` into each fault origin, so the culprit is the only erroring service in 9 of 9 windows
and `errors_by_service()` argmax scores ~11/12 with no model in the loop. It is a valid **cost
control** and an invalid accuracy test.

Nezha's faults are `return`/`exception` code mutations authored by the dataset's own authors, and the
labels are not in the log text. Measured in `results/NEZHA_REACHABILITY.md`:

| Train Ticket, 24 log-visible windows | |
|---|---|
| window contains any error | 24/24 |
| culprit emits ≥1 ERROR itself | 7/24 |
| **argmax(errors_by_service) is correct** | **5/24 (21%)** |
| culprit reachable by `trace_id` from a foreign error line | 14/24 (58%) |

The digest shortcut is gone. That is the point.

## Design

**Windows.** 24 fault windows (13 `exception`, 11 `return`) + 4 normal control windows, Train Ticket
only (`2023-01-29`, `2023-01-30`). OnlineBoutique is excluded: 5 of its 14 log-visible windows
contain any error at all. Controls are ≥5 minutes from any injection in the same hour.

**Arms.** `plain` / `structured_no_trace` / `structured`, identical tool schemas in all three
(`matched_schemas=True`). `plain → structured_no_trace` isolates `service.name`;
`structured_no_trace → structured` isolates `trace_id`.

**Models.** `gpt-oss:120b`, `qwen3.5:397b`, `kimi-k3`, `glm-5.2` — the four from
`CLOUD_MATRIX_MATCHED.md`, so the two datasets are comparable.

**Fixed before the first cell.** `timeout=240s`, `max_rounds=14`, `max_total_tokens=250,000`,
`num_ctx=32,768`, `concurrency=6`. Changing any of these means a new output file, not a resumed run.

Total: 28 windows × 3 arms × 4 models = **336 cells**.

## Metrics

**Primary — `cost_per_correct`** (answered-cell tokens ÷ correct answers), per arm, pooled across
models. Chosen over raw tokens because an agent that gives up early looks cheap; pricing failure is
the whole point.

**Secondary** — accuracy; median `total_tok` over answered cells; give-up rate; abort rate.

**Reported separately, never pooled** — `median` and `mean` both, because
`FINDING.md` §5 showed this distribution is heavy-tailed and means alone mislead.

## Stratification, committed in advance

Results are reported split by **REACHABLE** vs **NOT REACHABLE** (from
`results/runs/nezha_reach.jsonl`), because trace context *cannot* help a window whose culprit shares
no trace with any erroring service. Pooling the 10 unreachable windows into one mean would dilute the
effect under test and understate it. Both strata are reported; neither is dropped.

Expected cell counts: reachable 14 windows × 3 × 4 = 168 cells; not-reachable 10 × 3 × 4 = 120.

## Scoring rules

- **A give-up is its own outcome.** `unknown` scores `correct=False` even when truth is `none`.
  `NAVIGATION.md` note 2 recorded the old scorer crediting give-ups as `none`, turning a model that
  quit into a model that diagnosed a healthy system. Fixed here.
- **Near-duplicates stay distinct.** `ts-travel-service` and `ts-travel2-service` are different
  answers and both appear as culprits (3 windows each). Normalising to alphanumerics preserves the
  distinction. `RCA_RECOVERABILITY.md` shows models land on the sibling; that must score as wrong.
- **Failures are data.** Timeouts and aborts keep their observed token count and are reported as a
  separate rate, never folded in as `total_tok=0`.

## What would falsify the hypothesis

The hypothesis is that trace context lowers `cost_per_correct` on windows where the culprit is
reachable. It is **refuted** if, on the reachable stratum, `structured` does not beat
`structured_no_trace` on `cost_per_correct` — either costing more, or the same within run-to-run
noise.

**The noise floor is known and is large.** Re-running byte-identical cells on the OTel Demo gave mean
|Δ| of 8,347–39,758 tokens per cell (`FINDING.md` retraction banner). A difference smaller than that
is not a result. With n=14 reachable windows this run is powered to detect a large effect or nothing;
it cannot resolve a small one, and no small effect will be claimed from it.

## Known limitations, stated before seeing results

- **n is small.** 14 reachable windows. Enough for a paired contrast, not for per-model subgroup
  claims. No per-model conclusion will be drawn.
- **Reachable ≠ diagnostic.** In 30 of 45 Train Ticket windows the culprit emits no error of its own,
  so what `lines_for_trace` returns may be ordinary INFO traffic. Reachability is necessary, not
  sufficient.
- **One run per cell.** No within-cell variance estimate; the noise floor above is imported from the
  OTel Demo runs and may not transfer.
- **`cl100k_base` remains a token proxy.** A real-tokenizer cross-check is still outstanding.
