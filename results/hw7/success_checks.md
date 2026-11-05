# HW7 success checks (committed before the first main run, 2026-11-04; not edited after)

1. A fact is correct when `same_value(value, truth)` holds against the 2026 ground truth and its cited document exists in the permitted corpus. A missing fact is an error.
2. The final brief is the facts of the job the Checker passed. If no job passed after one rematch, or the Matcher answered no match, the brief is empty and all 5 facts count as missing.
3. A task succeeds when all five facts in the final brief are correct.
4. Main metric: errors (wrong or missing) per 100 requested facts, per condition, over all tasks and repeats.
5. **Supported** if all hold: R's error rate is lower than B0's; a paired bootstrap 95% interval over the 12 main tasks (repeats averaged within a task, 10,000 resamples) for R minus B0 excludes zero; R's coverage is not more than 5 points below B0's; R's cost per correct fact (contract price, rematches included) is at most 10% above B0's.
6. **Not supported** otherwise, reported as it is.
7. R vs B1 is reported separately. A tie bears on the open assumption that forecasts add little to picking; it is not a failure of the main claim.
8. Checker errors are counted against ground truth: a false accept is a Checker pass on a wrong value; a false reject is a Checker fail on a correct value whose quote appears verbatim in a document about the right firm.
