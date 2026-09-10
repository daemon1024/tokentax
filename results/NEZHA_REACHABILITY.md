# Is the culprit reachable by trace_id? — the precondition nobody measured

**Script:** `scripts/check_nezha_trace_reach.py` · **Raw:** `results/runs/nezha_reach.jsonl` (101 rows)
**Data:** `data/raw/Nezha` @ `IntelligentDDS/Nezha` (MIT, cloned 2026-09-11, unchanged upstream since
2023-08-20). No model in the loop; nothing here cost a token.

`RCA_RECOVERABILITY.md` established that Nezha's labels are usually not in the log text. That is a
statement about what logs *say*. It leaves the load-bearing question untouched: when the erroring
service is not the culprit, does following `trace_id` off that error line actually **reach** the
culprit? If not, trace context cannot help at any price — `lines_for_trace` would return lines that
do not contain the answer.

## First: `RCA_RECOVERABILITY.md` reproduces

Re-measured independently from the raw CSVs, same 38 exception/return windows:

| | doc | this run |
|---|---|---|
| culprit emits ≥1 ERROR itself | 12/38 | **12/38** |
| culprit is the noisiest service | 8/38 | **8/38** |
| culprit named in some error's text | 2/38 | **3/38** |

The one gap is `named in error text`, and it is a definition difference, not a discrepancy: this run
counts a plain substring match of the service name anywhere in any error line. The document's finding
stands as written. A 2026-09 claim that these numbers were undercounted because the severity parser
missed Train Ticket's logback `%-5level` token is **false** — `nezha._parse_log_field` reads the
Online Boutique JSON `severity` key and the Train Ticket level token in one code path, and the
reproduction above confirms it.

## The new measurement

**reachable** := ≥1 `trace_id` carried by an error line from a *non-culprit* service also carries ≥1
line (any severity) from the culprit. That is what an agent doing grep-for-errors → pivot-on-trace
would actually land on.

38 log-visible (exception/return) episodes:

| | all | TrainTicket | OnlineBoutique |
|---|---|---|---|
| episodes | 38 | 24 | 14 |
| window contains any error | 29 (76%) | **24 (100%)** | 5 (36%) |
| argmax(errors_by_service) correct | 8 (21%) | 5 (21%) | 3 (21%) |
| **reachable via trace_id** | 16 (42%) | **14 (58%)** | 2 (14%) |
| **usable cells** (error exists ∧ argmax wrong ∧ reachable) | **12/21 (57%)** | **10/19 (53%)** | 2/2 |

Across all 101 injected episodes (including cpu/network types the document excluded), TrainTicket
holds up better than its label suggests: **45/45 windows contain an error**, 20/45 are reachable, and
16/39 cause≠symptom cells are reachable.

**Compression on the reachable path:** median `reach_chars / window_chars` = **0.1414**, i.e. the
lines of the reaching traces are ~7× smaller than the window. On OnlineBoutique's two cells it is
0.0101 (~99×), but n=2.

## What this means

**The experiment is viable on Nezha TrainTicket, and small.** Roughly **10–16 usable cells** —
windows where an error exists, the naive digest points at the wrong service, and trace context
actually reaches the right one. That is enough for a paired contrast, not enough for per-model
subgroup claims. Pre-register it as such.

**The remaining 43% is the honest headline.** In 9 of 21 cause≠symptom cells the culprit is *not*
reachable from any erroring trace. Trace context cannot rescue those, and a successor experiment must
report them as a separate outcome rather than folding them into an accuracy denominator.

**OnlineBoutique is out.** 5 of 14 log-visible windows contain any error at all; 2 are usable. The
36% error-bearing rate is the same wall `RCA_RECOVERABILITY.md` hit.

**7× is not 331×.** The navigation-vs-reading result in `NAVIGATION.md` compares against reading a
1.07M-token window. Nezha's per-minute TrainTicket windows are ~4.5 MB (~1.1M tokens) but the
*reaching subset* is only 7× smaller, not 300×. These measure different things and must not be
compared: 331× is navigate-vs-read, 7× is trace-scoped-vs-whole-window.

## Caveats

- **Window = one minute**, Nezha's own granularity. A fault spanning minutes is counted at its
  injection minute only; a wider window would raise both error counts and reachability.
- **reachable is necessary, not sufficient.** It says the culprit's lines share a trace with an error
  line. It does not say those lines are *diagnostic* — in 30 of 45 TrainTicket windows the culprit
  emits no error of its own, so what the agent retrieves is ordinary INFO traffic. Whether that
  suffices is a question for a model, not for this script.
- **`trace_id` is also in the message body.** Nezha's logback pattern is
  `... TraceID: %X{trace_id} SpanID: %X{span_id} %msg%n`, so the plain and `structured_no_trace` arms
  must scrub the body, not merely drop the column, or the ID leaks into the arms that are supposed to
  lack it. `SOURCE_DECISION.md:45` flagged this; it is still true and still unimplemented.
- **101 vs 38.** The dataset carries 101 labelled injections (OnlineBoutique 56, TrainTicket 45).
  38 is the exception/return subset. `CLAUDE.md`'s "12/38 windows" phrasing is about that subset.
