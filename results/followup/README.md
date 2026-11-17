# Follow-up experiments (2026-11-17)

Three experiments proposed after HW7. All real model calls went through the signed-in claude CLI
(`claude -p`, no tools, JSON schema, effort low), as in HW7. Everything here is reproducible:

```bash
export PYTHONPATH=src REFERRAL_HW7_TAG=followup      # writes to results/followup, runs/followup
python -m referral.hw7 warmup                         # 9 trial jobs per worker, fixed Checker rule
python -m referral.hw7 scale --repeats 3 --per-band 10 --parallel 8
python -m referral.nested --tasks 12 --models haiku,sonnet --modes relay,review,relay-stale,review-stale
python -m referral.followup_analyze                   # summary.md, numbers.json, fig_scale.*, fig_nested.*
```

## What changed in the code

- **Token usage is persisted.** `submit_delivery(..., usage=...)` stores the worker's model usage
  (calls, input/output/cache tokens, list-price $, provider-reported $) in the signed `delivery`
  Notary entry and in `jobs.usage`; the Checker's judge usage goes into the `verdict` entry's
  `semantic_check.usage` and `jobs.usage.checker`. Old ledgers get the column on open.
- `hw7.py`: `REFERRAL_HW7_TAG` output directory, a `scale` step (seed 7005), and each result row
  carries `ledger_usage` read back from the ledger.
- `nested.py`: two-hop chain, real Claude worker (hop 1) subcontracting through Referral to a
  scripted faker (hop 2).

## Reading the results honestly

1. **R vs B0 (scaled up).** With the Checker fix, B0 also ends at 0 errors per 100 requested facts:
   the Checker catches every bad delivery from the overconfident worker and the rematch fixes it.
   R and B0 are identical on errors (0.0 vs 0.0, 30/30 tasks tied), so there is no error gap to
   test in this pool. The gap that does hold up is cost: B0 hires the overclaimer first every
   time, needs a rematch on 46% of requests and costs the buyer $1.04 per request vs $0.31 for R
   (-70%, Wilcoxon p = 2e-17). Without the Checker (B0-raw, B0's first delivery taken as is),
   9.1 errors per 100 facts get through, and R beats that with p = 2e-5. R and B1 (outcomes
   only) tie in this pool: both pick Haiku. In HW7's limit test, an error gap appeared only with
   80% unreliable workers, where B0 ran out of rematches.
2. **Two-hop chain.** 96 runs (Haiku and Sonnet as hop 1; relay and review; fakes that fail the
   rule layer and stale-but-real quotes that pass it). The Checker's attribution matched the
   ground truth in 96/96: every failed relay job was traced to hop 2 only. Stale fakes with real
   quotes were caught by the semantic layer (14) or the hidden check (6). When hop 1's model saw
   hop 2's facts, it replaced every fake itself (48/48), so no fake reached a buyer.
   Not covered: a hop 1 that also makes its own errors (both hops at fault), or a hop 1 that edits
   a fake into a different wrong value; neither occurred.
3. **Real spend.** See `summary.md` section 3. All three experiments together (warm-up, 270
   requests, 96 chains) used about 6.2M tokens and cost $1.43 at list price ($1.63 as reported
   by the CLI).
