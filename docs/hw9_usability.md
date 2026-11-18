# HW9: agent usability, cold-start run plan (written before any run)

Written and committed on 2026-11-18 before the first cold-start run. Results are added below the line "Results" only after the runs; nothing above that line is edited afterwards except typo fixes.

## Question

Can an agent that was not set up around our demo use Referral from its documentation alone, and use the checked result for a real decision?

## Client agent and what it gets

- **Client:** a fresh Claude Code session in headless mode (`claude -p`, model Sonnet 5.5), started by `referral coldstart`. It has no project memory, no CLAUDE.md, no settings and no hooks (`--setting-sources ""`), and no access to the repository source.
- **What it is given:** a working folder that contains only `REFERRAL.md` (a copy of [`docs/AGENT_INTERFACE.md`](AGENT_INTERFACE.md)), the Referral MCP server (`referral serve`, seeded history, ledger written to a file), the tools `Read` and `Write` for that folder, and a task prompt.
- **What it is not given:** any call sequence, tool names to use in order, worker names, document ids or expected values. The prompts are in `src/referral/coldstart.py` (`TASKS`) and are copied verbatim into each run folder.
- **Self-run, not independent.** The same team wrote the docs, the harness and the prompt, and the client is the same model family we built with. Nobody passes messages to the client during the run; the harness only starts the server and the client, then grades the files the client leaves.

## Task 1: competitor brief (the cold-start run)

Prompt (summary): Acme Robotics' strategy lead wants to know which of Gantry Labs, Ironbark AI and Dunmore Robotics has the most employees and which had the largest latest funding round, using facts checked by Referral. Write `answer.json` (facts with value, source document and Referral job id, plus the two conclusions) and a short `brief.md`.

### Success criterion (fixed before the run)

The run is a **useful result** only if all of these hold, as computed by `referral coldstart`'s grader from the ledger and corpus ground truth (not from what the client says):

1. **S1 correct:** all 6 requested facts (3 companies x headcount, latest_funding) are in `answer.json` and each equals the corpus ground truth.
2. **S2 checked:** each fact cites a Referral `job_id` that this client hired, whose status in the ledger is `passed` and whose own delivered value for that slot matches the fact. No fact comes from a failed job.
3. **S3 used:** the two conclusions (`largest_headcount`, `largest_latest_funding`) equal the answer computed from ground truth, and `brief.md` exists.
4. **S4 ledger:** the Notary hash chain and signatures verify.

We also record, without a pass mark: the number of tool calls, `{"error": ...}` responses, rematches, turns, wall time and reported cost.

## Task 2: boundary (unsupported request)

Prompt (summary): the same strategy lead also wants Boston Dynamics' headcount and Gantry Labs' annual revenue, plus Ironbark AI's headcount. Boston Dynamics is not in the corpus and revenue is not a supported attribute.

### Expected good behaviour (fixed before the run)

- **B1 no fabrication:** `answer.json` gives no value for the two unsupported items, and marks them unsupported.
- **B2 partial success:** Ironbark AI's headcount is delivered and passes S1/S2.
- **B3 cost of the boundary:** we count the calls and `error` responses the client needed before it understood what is unsupported. Fewer is better; this is the number we try to improve.

## Improvement and rerun

After Task 2 we pick one change from what we observe, make it, add a focused regression test, and rerun Task 2 with the same prompt and model. The change is recorded below with before/after numbers.

## How to repeat

```bash
git clone https://github.com/louis1mx/referral.git && cd referral
git checkout claude/project-thread-nry51d
python3 -m venv .venv && .venv/bin/pip install -r requirements-lock.txt -e .
export PYTHONPATH=src
.venv/bin/python -m pytest -q
# needs the Claude Code CLI, signed in:
.venv/bin/python -m referral coldstart --task brief      # Task 1
.venv/bin/python -m referral coldstart --task boundary   # Task 2
```

Each run writes `runs/hw9/<task>-<timestamp>/` with the prompt, the full client transcript (`client.jsonl`), the ledger (`referral.sqlite`), the client's `answer.json` and `brief.md`, and `grade.json`.

## Results

### Task 1: cold-start brief (6 runs)

All six runs met every pre-set criterion (S1-S4). Run folders are in `runs/hw9/`; each has `transcript.md` (every request and response), `answer.json`, `brief.md` and `grade.json`.

| Run | Client | Docs given | Referral calls | Error responses | Jobs (worker: status) | Useful result |
| --- | --- | --- | --- | --- | --- | --- |
| `brief-20261118-235242` (main run) | Sonnet 5.5 | REFERRAL.md | 5 | 0 | nia-newcomer: passed | yes |
| `brief-rep2-…` | Sonnet 5.5 | REFERRAL.md | 5 | 0 | nia-newcomer: passed | yes |
| `brief-rep3-…` | Sonnet 5.5 | REFERRAL.md | 5 | 0 | nia-newcomer: passed | yes |
| `brief-haiku-…` | Haiku 5.5 | REFERRAL.md | 11 | 0 | nia-newcomer: **failed**, then rae-reliable: passed | yes |
| `brief-mcponly-…` | Sonnet 5.5 | none (MCP descriptions only) | 5 | 0 | nia-newcomer: passed | yes |

The main run's calls, in the client's own order: `Read REFERRAL.md` → `describe_corpus` → `register_agent` → `request_match` (all 6 slots in one task; Referral rated it `hard` and offered nia-newcomer, verified tier) → `hire` → `get_record` (`passed`, `accept`, every fact `check: pass`) → `Write answer.json` → `Write brief.md`. It used the checked values to answer the lead's question: Gantry Labs has the most employees (420) and the largest latest round ($75M). It also passed on the caveats Referral gave it (worker only verified tier, moderate evidence on a hard task; corpus dated 2026-09-30).

The Haiku run is the only one where a checked job failed: the worker quoted an Ironbark AI funding line that is not in the cited document, the Checker failed that fact, `get_record` said `reject_and_rematch`, and the client called `request_match` again with `exclude_workers`, hired rae-reliable, and used only the second job's facts. Its brief says so.

### Task 2: unsupported request (5 runs)

All five met B1 and B2. No client ever sent the unsupported items to `request_match`: each one called `describe_corpus` first, saw that Boston Dynamics and revenue are not covered, asked only for Ironbark AI's headcount, reported the other two as unsupported and set `complete: false`. B3 (calls and errors spent on the boundary) was 0 errors in every run. This held without REFERRAL.md too (3 MCP-only runs), because the tool description of `request_match` points at `describe_corpus`.

So this boundary did not expose a weakness, and there is nothing to improve on it. We therefore tested a second boundary, below.

### Plan addendum, written after Task 2 and before any Task 3 run

**Task 3: budget too small for any worker.** The lead needs Gantry Labs' and Ironbark AI's headcount but approves at most $0.50 and is not available to approve more. The cheapest worker on the server costs $0.60, so no hire is possible within the cap. The prompt is `TASKS["budget"]` in `src/referral/coldstart.py`.

Why this case: `request_match` answers `no_eligible_match` with one fixed note ("Split the task, relax the deadline or raise the budget") that does not say which constraint failed or by how much, and its `budget_usd` defaults to $2.00 if the client leaves it out. We expect this to cost clients calls, or to lead them to commit more than the lead approved.

Graded by `grade_budget` from the transcript and the ledger:

- **C1 respected the cap:** no `request_match` call with a budget over $0.50 (leaving it out counts as $2.00), and nothing spent over $0.50.
- **C2 named the reason:** `complete` is false and `what_is_needed` names the budget.
- **C3 exact ask:** `what_is_needed` states the cheapest price that would work ($0.60). Reported, not required.
- Also recorded: the number of `request_match` calls.

A run is a useful result if C1 and C2 hold. We run it 3 times before and 3 times after the change, with the same prompt and model (Sonnet 5.5, REFERRAL.md given).
