# The one change, and why (written before the retest, 2026-11-04)

## What the limit test (tuning competitors) showed

| Pool | B0 errors per 100 requested facts | R errors per 100 requested facts | What failed |
|---|---|---|---|
| 0% unreliable | 0.0 | 0.0 | B0 hard-1: the Checker failed Haiku's two funding facts, both correct and quoted verbatim, then a paid rematch to Sonnet |
| 40% (main pool) | 0.0 | 0.0 | B0 rematched after `olu` on 4 of 6 tasks |
| 80% unreliable | 50.0 | 0.0 | B0 hired `olu` then `olu-2` (both declare 0.95), both failed on 3 of 6 tasks, empty briefs |
| 40% + newcomer | 0.0 | 0.0 | `claude-sonnet-newcomer` hired 0 of 16 times |

Three limits: self-report stops working once overclaimers outnumber the rematch; Referral never gives a worker with no record a job; and the Checker's rule layer rejects a correct value the worker annotated.

## The change

**Checker rule layer: a value is supported when its core appears in the quote.** Haiku writes values such as `$48M funding round (May 2026)` while quoting `Everline Systems announced a $48M funding round in May 2026.` The rule required the whole value string inside the quote, so a correct, verbatim-cited fact failed and the buyer paid for a rematch. The rule now drops a trailing parenthetical and, for a number or amount, keeps its first token (`$48M`), which must appear in the quote as whole words. Text values (a product name) must still appear whole. The semantic layer and the hidden known-answer check are unchanged, and ground truth still uses `same_value`.

Why this one and not cold start: it is a defect in Referral's own verification that cost money in the limit test and can drop facts from a brief, and its effect can be measured on cost, rematches and errors with the same pool. Cold start for newcomers is a market-design question (who pays for a trial) and is left as an open limit.

Disclosure: the main-run results were already visible when this was written, and they show the same failure (9 false rejects, all on annotated funding values). The rule was not tuned on any fresh competitor; it has no parameter.

## Retest

R (the condition under test) and B0, before (`strict_values=True`, the old rule) and after (the new rule), on 6 new tasks from the fresh competitors (seed 7004, 2 per band), same pool, warm-up, budget and Checker model. `python -m referral.hw7 retest --variant before|after`.
