# Navigation vs reading: the result that survives

**This is the only empirical claim in this repository that is orders of magnitude outside the noise
floor.** Everything else measured here — every plain-vs-structured contrast — is smaller than the
run-to-run variance of the models themselves (see the retraction banner on `FINDING.md`).

Raw: `runs/incontext_baseline.jsonl` (8 cells, 2 excluded as 429 rate-limited, never zero-filled)
against `runs/cloud_matrix.jsonl`. Bounded on purpose: 2 models × plain × 4 windows. The cap is stated
rather than implied — reading 12 windows on 8 models would be ~100M input tokens for a ratio already
visible at n=6.

## The measurement

Paired: same model, same window, same condition (`plain`). In-context reads the whole window in 110k
chunks and majority-votes; RLM navigates with `overview`/`grep`/`peek`/`errors_by_cluster`.

| model | truth | in-context | RLM | ratio | IC | RLM |
|---|---|---|---|---|---|---|
| gpt-oss:120b | product-catalog | 1,099,796 | 2,317 | 475× | MISS | ok |
| gpt-oss:120b | cart | 1,122,007 | 5,595 | 201× | MISS | ok |
| gpt-oss:120b | none | 1,095,107 | 2,375 | 461× | MISS | ok |
| gpt-oss:120b | ad | 1,132,837 | 1,207 | 939× | MISS | ok |
| qwen3.5:397b | product-catalog | 1,384,129 | 187,108 | 7× | ok | ok |
| qwen3.5:397b | none | 1,375,558 | 13,976 | 98× | ok | ok |

```
median tokens    in-context 1,127,422   RLM 3,985     ->  331x cheaper
accuracy                     2/6                6/6
                        (1/6 strict)
median calls     10-11 chunks           2-4 rounds
```

**Navigation is 331× cheaper AND more accurate.** Range 7×–939×.

## Three things worth noting

**1. Reading everything does not just cost more — it reasons worse.** `gpt-oss:120b` scored **0/4**
after reading 1.1M tokens per window, and its errors are systematic, not random:

```
product-catalog -> recommendation    (downstream symptom)
cart            -> flagservice
ad              -> frontend
none            -> flagservice       (false positive on a healthy window)
```

It lands on symptom or unrelated services every time. Chunked reading destroys exactly the
cross-chunk context needed to separate cause from symptom: no single 110k chunk contains the whole
picture, and the majority vote over chunks has no way to weight the originating error above the
downstream noise. RLM on the same model and windows was 12/12.

**2. `2/6` is generous.** `qwen3.5:397b` answered `unknown` on a healthy window and scored correct,
because `correct()` credits `unknown` as `none`. A model that gives up is credited with diagnosing a
healthy system. Strict accuracy is **1/6**. The scorer should treat give-ups as their own outcome.

**3. The one 7× cell is the exception that confirms the mechanism.** `qwen3.5:397b` on
plain/product-catalog spent 187,108 RLM tokens — it found the answer via the digest and then kept
navigating anyway. Navigation's win is not guaranteed per-cell; it is a distributional property, and
its failure mode is a model that will not stop.

## Why this is the real finding, and what it is not

The project's thesis was *"OpenTelemetry trace context is free input compression."* Split that in two:

- **"Reading the whole window is the wrong baseline"** — overwhelmingly true. 331×, and more accurate.
- **"Trace context is what provides the compression"** — not supported. The compression comes from
  navigating instead of reading. Within navigation, structure is inside the noise, and `trace_id`
  specifically was never on the critical path for this task (trace tools called in 17% of cells).

So the headline survives, with a different mechanism than the one claimed. It is a result about
**agentic retrieval**, not about OpenTelemetry.

## What this does not settle

Whether `trace_id` earns its keep on a task that actually requires correlation. It plausibly does, and
there is a mechanical lower bound measured over 250 failing traces with no model involved:

| | tokens |
|---|---|
| `lines_for_trace(tid)` — exactly that request's lines across services | **898** |
| positional read of the index range containing those lines | **4,783** |
| full window | 1,172,567 |

**5× median, 56× worst case** — and the positional baseline is an *oracle* that already knows the range,
which plain logs cannot know. Failing traces here span **3–10 services** and 4–27 lines, so the
cross-service chain is real; the root-cause task simply never asked anyone to reconstruct it.

That is the experiment worth running next: retrieval, scored over line sets, on windows where several
services error and the top-ranked one is sometimes the symptom.
