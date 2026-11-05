# HW7 notes

## What maps to which code

| Brief name | Code |
|---|---|
| Scripted hiring policy | `hw7.run_request` (one buyer request: `request_match` with a frozen profile set, `hire`, `get_record`, one rematch excluding tried workers), modelled on `evaluate.run_strategy` |
| B0 self-report | Matcher strategy `self_report` (`matcher.py`), reading `declared_success` from registration |
| B1 outcomes only | Matcher strategy `outcomes` |
| R full Referral | Matcher strategy `referral`, default `min_success` 0.35 |
| `LLMWorker` | `workers.LLMWorker`, with `hw7.CliMessages` as its client |
| Personas | `workers.PERSONAS["overconfident"]` (`olu-overconfident`), `["padder"]` (`pat-padder`), as `SimWorker` |
| Checker | `checker.check_delivery` (rules) + `semantic.ClaudeJudge(runner=ApiRunner(client=CliMessages()))` on Haiku 5.5 |
| Ground-truth audit | `hw7.judge_facts` (evaluation code, `corpus.truth` + `same_value`); per-request ledgers verified with `verify_ledger` |
| `corpus.make_task` | `Corpus.make_task(..., competitors=)`, added for the split |

## Decisions and changes made before any main-run result

- **Workers through the claude CLI, not the API.** No `ANTHROPIC_API_KEY` was available tonight. `hw7.CliMessages` gives `LLMWorker` and the judge the same `messages.create` interface over `claude -p` (headless, no tools, JSON schema, `--effort low`). Token cost is computed from the CLI's reported usage at list prices.
- **Warm-up raised from 6 to 9 jobs (3 per band).** With 2 per band the Scorer never trusts any band's forecasts (`MIN_FORECASTS_FOR_TRUST = 3`), so R would rank exactly like B1. The 6-job warm-up (`discarded/warmup-6jobs.json`) was discarded before the pilot.
- **Frozen profiles.** Each buyer request runs in a fresh service with its own ledger, and every condition uses the same frozen warm-up profiles, so requests are independent and can run in parallel.
- **Deadline 300 s** instead of the corpus default 120 s, to leave room for CLI latency.
- **Effort `low`** for workers and judge, to fit the time available.

## What broke

(filled in after the runs)
