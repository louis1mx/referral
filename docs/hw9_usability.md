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
