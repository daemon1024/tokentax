# Per-request forensics V3: the printed id, the lookup, and telling the model. Result

Pre-registered in `results/REQUEST_FORENSICS_V3_PREREG.md` (commit 802462f, sha256 of the file `c0640edb…`,
before the first main cell; no amendments). Raw rows: `results/runs/request_forensics_v3.jsonl` (450 cells).
Analysis: `scripts/analyze_request_forensics_v3.py` → `results/runs/request_forensics_v3_analysis.{json,md}`.
Not pooled with V1 or V2.

**Coverage. COMPLETE:** 3 models × 30 seeds × 5 arms = 450 cells, all observed, 0 transport, 0 unavailable,
no spend-cap or usage-limit stop. **Tokens:** 30,641,462 (beam 1,730,581; deepseek-v4-pro:0813 14,686,963;
minimax-m3.1-flash 14,223,918); smoke 136,273. **Estimated spend** at peak list prices, no cache discount:
$24.46 (beam at an assumed rate; it is not on the price list).

## The task, in one line

Given one error log line from the OTel Demo, return every other line of the same request (line-set F1;
right := F1 ≥ 0.8). P plain · S + `svc=`/`sev=` · **Tt** + `trace=<8 hex>` printed on every line, lookup tools
reply "not available" · T + the live lookup · **Th** T + one sentence in the system prompt. Same 8-tool schema,
same prompt otherwise, 250,000-token ceiling, 20 rounds, 300 s.

## Results

Right answers of 30 · tokens per right answer (all observed tokens ÷ right) · median rounds.

| model | P plain | S structured | Tt id printed | T + lookup | Th + told |
|---|---|---|---|---|---|
| beam | 6 · 82,554 · 4.5 | 7 · 73,589 · 4 | 25 · 19,016 · 4 | **30 · 3,566 · 2** | **30 · 4,592 · 2** |
| deepseek-v4-pro:0813 | 2 · 3,275,500 · 14 | 13 · 428,872 · 11 | 29 · 56,424 · 7 | 28 · 27,814 · 3 | **30 · 4,851 · 2** |
| minimax-m3.1-flash | 10 · 650,071 · 10 | 14 · 432,821 · 9 | 30 · 34,102 · 6 | 30 · 14,111 · 4 | **30 · 7,244 · 2** |

Failures (no_answer = the 250k token ceiling in every case; no round-cap aborts): beam none; deepseek
P 20, S 11, T 2, Tt 1 timeout (censored); minimax P 16, S 11. Every failure keeps its tokens in the
tokens-per-right numerator.

**Did the run point a tool at the request's own trace id** (pre-registered `grep_trace` / `lookup_trace`)?
In Tt every run of every model first called `lines_for_trace` (reply "not available"); the run then
grepped the id in beam 26/30, deepseek 30/30, minimax 30/30. In T and Th, 30/30 runs of every model called
the lookup first.

## Decisions (per model, exact two-sided sign tests; rules from the PREREG)

| contrast | beam | deepseek-v4-pro | minimax-m3.1-flash |
|---|---|---|---|
| S → Tt, id printed (no lookup) | **supported**: 7→25 right (p 7.6e-6), TPC ×0.26 | **supported**: 13→29 (p 1.5e-4), ×0.13 | **supported**: 14→30 (p 3.1e-5), ×0.08 |
| Tt → T, the lookup | **supported**: ×0.19, tokens p 1.9e-9 | **supported**: ×0.49, p 4.2e-7, rounds 7→3 | **supported**: ×0.41, p 5.8e-8, rounds 6→4 |
| T → Th, tell it (rounds) | **not shown**: 2→2 rounds; tokens ×1.29 (the sentence cost it) | **supported**: rounds 3→2 (p 2.2e-4); TPC ×0.17; 28→30 right | **supported**: rounds 4→2 (p 1.5e-3); TPC ×0.51 |
| S → T, id printed + lookup | **supported**: ×0.048 (21×) | **supported**: ×0.065 (15×) | **supported**: ×0.033 (31×) |
| P → S, service.name | not shown | **supported**: 2→13 (p 9.8e-4), ×0.13 | not shown |

**What this adds to V2.** V2's T beat S but changed two things at once. V3 separates them: printing the id
alone (Tt) already pays for every model, because every model greps it once the lookup says "not available";
the live lookup then pays again on top (2–5× fewer tokens per right answer, fewer rounds). Telling the
model what the field is for cuts rounds for the two models that kept re-checking (deepseek, minimax) and
costs beam, which did not need it, a little.

## Drift against V2 (not decision-bearing)

beam reproduces V2 closely: P 5→6, S 6→7, T 30→30 right; T tokens per right 3,553 → 3,566. **minimax-m3.1-flash
does not:** V2 P 0/30, S 0/30, T 28/30 at 124,815 per right; V3 P 10/30, S 14/30, T 30/30 at 14,111. Same model
name, same configuration, temperature 0 and seed 0; the differences are the provider's serving (free tier at
concurrency 1 with 2 workers in V2, Pro at concurrency 3 with 3 workers in V3 — queueing can only cause
timeouts, and V3 had none for minimax, so it cannot explain the token difference) and whatever changed in the
model behind the name in five days. The V3 numbers are the ones to cite; V2's minimax numbers describe that day.

## Limitations

All of V1's and V2's (constructed seeds from hand-patched `logger.error` lines; n = 30 per model; one capture;
plain-text correlation keys in every arm; one run per cell), plus: many tests without multiplicity correction
(exact p reported; claims name their model); dollar figures are estimates at peak list price without the
provider's cache discount; beam has no list price.
