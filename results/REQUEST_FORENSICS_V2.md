# Per-request forensics V2: P / S / T / TI. Result

Pre-registered in `results/REQUEST_FORENSICS_V2_PREREG.md` (final sha256 `9fa22284…` before the first main
cell; one dated procedural amendment). Raw rows: `results/runs/request_forensics_v2.jsonl` (240 cells),
`results/runs/request_forensics_v2_rep2.jsonl` (60-cell replicate). Analysis: 
`scripts/analyze_request_forensics_v2.py` → `results/runs/request_forensics_v2_analysis.json`. Not pooled
with V1.

**Coverage. COMPLETE, not partial:** 2 models × 30 seeds × 4 arms = 240 cells, all observed, 0 transport,
0 unavailable, no usage-limit stop. Complete quadruples: **60** (every model × seed). The beam T/TI
replicate is complete (60/60).

**Cloud tokens:** main run 24,879,150 (beam 1,219,098; minimax-m3.1-flash 23,660,052); replicate 225,934;
probe 640 + smoke 124,085. **Total recorded: 25,229,809.** Not recorded: the one or two cells that were in
flight when the main run was paused at a seed boundary for the replicate (amendment); those wrote no row.

## The task, in one line

Given one error log line from the OTel Demo, return every other line of the same request (scored by line-set
F1; correct := F1 >= 0.8) and the originating service. P = plain lines; S = + `svc=`/`sev=`;
T = + `trace=<8 hex>` on every line and the seed's trace_id; TI = S's lines exactly, the seed's trace_id,
and a live trace index (`lines_for_trace`). Tool schema byte-identical in all arms.

## Results (complete quadruples)

| model | arm | correct | mean F1 | failures (no_answer / timeout) | median tok, answered | mean tok, all observed | **tokens / correct** | median rounds |
|---|---|---|---|---|---|---|---|---|
| beam | P | 5/30 | 0.306 | 0 / 0 | 14,824 | 16,913 | 101,477 | 4 |
| beam | S | 6/30 | 0.314 | 0 / 0 | 12,180 | 15,631 | 78,153 | 3.5 |
| beam | **T** | **30/30** | **1.000** | 0 / 0 | 3,012 | 3,553 | **3,553** | 2 |
| beam | **TI** | **30/30** | **1.000** | 0 / 0 | 2,941 | 4,540 | **4,540** | 2 |
| minimax-m3.1-flash | P | 0/30 | 0.000 | 26 / 4 | — (none answered) | 266,976 | undefined (0 correct) | 10 |
| minimax-m3.1-flash | S | 0/30 | 0.000 | 24 / 6 | — (none answered) | 256,942 | undefined (0 correct) | 10 |
| minimax-m3.1-flash | **T** | **28/30** | **0.931** | 1 / 1 | 96,423 | 116,494 | **124,815** | 6.5 |
| minimax-m3.1-flash | **TI** | **24/30** | **0.799** | 5 / 1 | 122,618 | 148,257 | **185,321** | 8.5 |

Pooled over both models (60 cells per arm): accuracy P 5/60, S 6/60, **T 58/60, TI 54/60**; mean F1
0.153 / 0.157 / **0.965** / 0.900; failure rate P 50%, S 50%, T 3.3%, TI 10%. The no_answer failures are
token-ceiling aborts (250,000) and round-cap aborts; timeouts (12 cells) are censored, their tokens a
lower bound.

Sensitivity (descriptive): F1 >= 0.5: beam 8 / 8 / 30 / 30, minimax 0 / 0 / 28 / 24; F1 = 1: beam
2 / 2 / 30 / 30, minimax 0 / 0 / 24 / 23 (P / S / T / TI). Root service exact match: beam 30/30 in every
arm (uninformative here, as pre-registered: root == seed service in 30/30); minimax 0 / 0 / 28 / 24.

## Pre-registered decisions

| hypothesis | statistic (geometric mean over models of within-model TPC ratio) | 95% cluster-bootstrap CI | mean case-level dF1 | replicate | verdict |
|---|---|---|---|---|---|
| **H1** T pays over S | **0.045** | [0.016, 0.084] | **+0.81** (30+/0-, p = 1.9e-9) | TPC(T, rep) / TPC(S, main) = 0.049 | **PAYS**: no falsification condition fired |
| **H2** TI pays over S | **0.058** | [0.021, 0.108] | **+0.74** (30+/0-, p = 1.9e-9) | TPC(TI, rep) / TPC(S, main) = 0.047 | **PAYS**: no falsification condition fired |
| **H3** TI cheaper than T | **1.377** (TI costs MORE per correct) | [1.094, 1.755] | **-0.066** (2+/5-, p = 0.45) | noise \|ln\| = 0.208 | **NOT SHOWN** |

**Which cells the ratios cover. Read this before quoting 0.045.** minimax-m3.1-flash produced no correct
answer in P or S (0/60), so its TPC(S) is undefined and the H1/H2 geometric means are **beam's ratio
alone** (3,553 / 78,153 and 4,540 / 78,153). minimax's S spent 7.7M tokens for zero correct answers against
T's 124,815 per correct, a ratio the statistic cannot express. The F1 contrasts use both models. The
paired **token** sign tests use answered pairs only, and minimax has none in P or S, so for H1/H2 they are
beam's: S→T ln-ratio median -1.40 (T cheaper in 24 of 30 cases, p = 0.0014); S→TI -1.24 (22 of 30,
p = 0.016).

**H3, in detail.** The prefix tax exists but is small, and at task level it is swamped by a behavioural
cost.

- **beam.** TI was cheaper than T in 26 of 30 answered pairs (p = 6e-5), by a median of 3.3%. The
  tokens-per-correct gap flips sign between runs (main: T 3,553 / TI 4,540; replicate: T 3,843 / TI 3,688),
  so the ~3% sits inside run-to-run noise.
- **minimax.** TI was worse: 24/30 correct against 28/30, 5 vs 1 no_answer, and median rounds 8.5 vs 6.5.
  Without `trace=` on the lines it more often went searching for the id with `grep` (which can find
  nothing in TI's lines) and then re-verified.
- **Both pooled.** TPC ratio TI/T = 1.38 (CI excludes 1). But the pre-registered sign test on case-level
  token ratios is p = 0.58, so the opposite claim ("the printed id is needed") is not established either.
  TI also fails non-inferiority against T (dF1 -0.066 < -0.05).

**Secondary (reported, not decision-bearing).** S vs P (`service.name`): no effect. beam dF1 +0.008
(6+/4-, p = 0.75), token ln-ratio +0.06 (p = 0.58), TPC ratio 0.77 with CI [0.26, 2.00]. minimax 0/30 in
both. P→T and P→TI: TPC ratios 0.035 and 0.045 (beam only, same reason as above).

## What this says

1. **On the per-request task, trace_id pays, by more than an order of magnitude.** Both models found the
   request in T and TI and mostly could not in P and S. beam: 30/30 against 5-6/30, at ~22x fewer tokens
   per correct answer. minimax: 28/30 against 0/30, with P and S burning to the 250k ceiling. This is
   V1's direction (V1 T: 7/7 answered correct on older models) on newer models, with a replicate. It is
   the first pre-registered PAYS in this repository; the culprit-service task remains a null.
2. **Printing the id on every line is not what pays; having the join is.** TI (index only) also passed H2.
   Removing the per-line prefix did not make the task cheaper for these models. One model was
   indifferent within noise, and the other got worse without the visible id.
3. **service.name buys nothing here** (P ≈ S on both models): the join key is the whole effect.

## Limitations

- **The seeds are constructed** (the hand-patched OTel Demo `logger.error`), n = 30 seeds, 2 models, one run
  per cell plus one replicate of one model's T/TI. Strata (9-11 seeds) are too small for claims.
- **The H1/H2 ratios rest on one model** (above). For minimax the contrast is accuracy (0/60 vs 52/60), not
  a finite ratio.
- **num_ctx was not enforced** by the cloud backend: in minimax 56 of 60 P/S cells, and 20 of 60 T/TI
  cells, sent a single-round prompt above 32,768 tokens (recorded per cell in `max_prompt_tok`). Arms were
  treated identically, but the absolute token counts are not those of a 32k-context deployment.
- **Tokens are provider-counted**, so they are comparable within a model only. beam and minimax differ ~32x
  in median tokens for a correct T answer (3,012 vs 96,423).
- **The run was paused once** between minimax seeds to run the replicate first (amendment). No parameter
  changed, and the in-flight cells wrote no row and were re-run.
- Plain-text correlation keys (envoy `x-request-id`, `sessionId=`, `userId=`) remain in every arm, as in V1.
- Free-tier account. The models are served by a third party and may change.
