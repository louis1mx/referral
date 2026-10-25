# HW6 MVP: two real agents hire and deliver through Referral

## What runs

`referral mvp` does all of this with one command. No person relays any step.

1. It starts the Referral MCP server over HTTP (`127.0.0.1:8791/mcp`). The market holds five simulated workers, each with 12 trial jobs on record, and one **Claude Haiku 5.5 worker** with no record.
2. It starts the **buyer agent**: Claude Code in headless mode on Claude Sonnet 5.5, named `acme-intel-agent`, Acme Robotics' competitive-intelligence agent.
   - The buyer gets only a goal (five competitor facts for a board brief) and a few rules.
   - Its only tools are Referral's MCP tools. It has no shell and cannot read or write files.
   - It chooses its own calls: register → `request_match` → `hire` → `get_record(wait_seconds)`. If the Checker fails a job, it rematches without that worker.
3. When Referral dispatches the job to the Claude worker, a dispatch hook starts that worker's own Claude Code runtime, the way a webhook wakes a hosted agent. The worker also acts only through Referral's MCP tools: `get_assignment` → `submit_prediction` (it locks a forecast before it reads any document) → `read_document` → `submit_delivery`.
4. The Checker verifies each fact:
   - the quote comes from a permitted document and matches it word for word;
   - the value appears in the quote;
   - one hidden known-answer slot matches the current value.

   The buyer builds its brief only from facts that passed.
5. `referral audit` reads only the ledger and the buyer's final answer, and independently checks:
   - the hash chain and signatures;
   - that the forecast was locked before the delivery;
   - that the hidden-check commitment opens;
   - each Checker verdict against ground truth;
   - that every fact in the brief is correct and comes from a passed job.

Child agents load no user or project settings and run no hooks, so local Claude Code plugins cannot add context to them.

## How to run it

From the repository root, after the setup in the README:

```bash
PYTHONPATH=src .venv/bin/python -m referral mvp
```

- **Time and cost.** One run takes about 40 seconds. It uses the account your local `claude` CLI is signed in to; both agents together cost about $0.04 per run.
- **Run folder.** Each run creates `runs/<timestamp>/`, containing:
  - `transcript.txt`: the readable trace;
  - `buyer.jsonl` and `worker-job-*.jsonl`: the agents' raw Claude Code stream-json;
  - `referral.sqlite`: the ledger;
  - `answer.json`: the buyer's brief;
  - `audit.json`: the audit result.
- **Re-run only the audit:** `PYTHONPATH=src .venv/bin/python -m referral audit runs/<timestamp>`.
- **Port.** The default port is 8791. Pass `--port` if it is taken.
- **Models.** Use `--buyer-model` and `--worker-model` (`haiku`, `sonnet`, `opus`) to change them.

## Recorded results (2026-10-25)

We ran it five times, and every run passed end to end. Two runs are committed as evidence: `runs/20261025-171910/` and `runs/20261025-172108/`.

- Referral gave the hard task to the Claude worker as a `bounded_trial`, because the worker had no record yet.
- The worker locked forecasts of 50–60%. Its delivery passed the Checker on 5/5 facts, including the hidden slot.
- The audit found:
  - 253 ledger entries with an intact chain;
  - no Checker false passes;
  - a brief that matches ground truth on 5/5 facts, all from the passed job.
- After that one job the Claude worker is still `trial`, with the guidance "only one checked hard job so far".

Every run passed on the first hire, so no rematch happened. The Checker's rejection of wrong deliveries (stale citations, look-alike firms, invented quotes) is covered by the simulated `referral demo` and the unit tests.

## One-minute video plan

| Time | Screen | Narration |
| --- | --- | --- |
| 0–8s | The command in a terminal | Referral checks and keeps track records for agents that hire other agents; two Claude agents interact only through its MCP tools. |
| 8–20s | The buyer's `request_match` → `bounded_trial`, then the dispatch | The buyer agent makes its own request. Referral matches on difficulty and track record, and a new worker only gets a bounded trial. |
| 20–35s | The worker locks its forecast, reads, delivers; the Checker passes it | The forecast is locked first and cannot change. The Checker checks every quote and the hidden slot. |
| 35–45s | The buyer's `get_record` with each fact passing, then the final brief | The buyer uses only checked facts. |
| 45–55s | The audit: chain ok, 5/5 match ground truth, 0 false passes | We do not trust what the agents say; we check it independently. |
| 55–60s | The limitation | The last sentence of the paragraph below |

## Submission paragraph

Referral (team: Yvette Ge, Mengxiang (Louis) Liu) checks the work and keeps the track records of agents that hire other agents. In this MVP, two Claude Code agents interact only through Referral's MCP server. Acme Robotics' competitive-intelligence agent (Claude Sonnet 5.5) asks for five sourced competitor facts. Referral offers it a Claude Haiku 5.5 worker that has no record yet, as a bounded trial. The worker locks its success forecast before it reads any document, then delivers cited facts. Referral's Checker verifies every quote against the permitted corpus, plus one hidden known-answer slot. The buyer builds its brief only from facts that passed. An independent audit then re-checks the hash-chained ledger and compares every delivered fact with ground truth: 5 of 5 correct, no false passes. Limitation: the corpus is a small fictional set, the other five workers are simulated personas, and one checked job is too little evidence, so Referral still lists the Claude worker at the trial tier.
