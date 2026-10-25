# HW6 MVP: two real agents hire and deliver through Referral

## What runs

`referral mvp` does all of this with one command. No person relays any step.

1. It starts the Referral MCP server over HTTP (`127.0.0.1:8791/mcp`). The market holds five simulated workers, each with 12 trial jobs on record, and one **Claude Haiku 5.5 worker** with no record.
2. It starts the **buyer agent**: Claude Code in headless mode on Claude Sonnet 5.5, named `acme-intel-agent`, Acme Robotics' competitive-intelligence agent.
   - The buyer gets only a goal (five competitor facts for a board brief) and a few rules.
   - Its only tools are Referral's MCP tools. It has no shell and cannot read or write files.
   - It chooses its own calls: register → `request_match` → `hire` → `get_record(wait_seconds)`. If the Checker fails a job, it rematches without that worker.
3. When Referral dispatches the job to the Claude worker, a dispatch hook starts that worker's own Claude Code runtime, the way a webhook wakes a hosted agent. The worker also acts only through Referral's MCP tools: `get_assignment` → `submit_prediction` (it locks a forecast before it reads any document) → `read_document` → `submit_delivery`.
4. The Checker verifies each fact in two layers:
   - **rule layer:** the quote comes from a permitted document about that company and matches it word for word, the value appears in the quote, and one hidden known-answer slot matches the current value;
   - **semantic layer:** Claude Haiku 5.5 reads the facts that passed the rules, together with every permitted document about that company, and fails any fact whose quote does not state the requested attribute or whose value a later document supersedes. String checks alone miss both cases (see `referral check-eval` below).

   The buyer accepts a job only when every fact passes, and builds its brief only from accepted jobs.
5. `referral audit` reads only the ledger and the buyer's final answer, and independently checks:
   - the hash chain and signatures;
   - that the forecast was locked before the delivery;
   - that the hidden-check commitment opens;
   - each Checker verdict against ground truth, including any correct fact the semantic layer failed;
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
- **Semantic layer.** It is on by default and uses Claude Haiku 5.5. `--checker-model none` runs the rule layer only, and `--checker-model sonnet` uses another model. The simulated workers' 60 seeded trial jobs are checked by the rule layer only; every live job in the run goes through both layers.
- **Measure the semantic layer:** `PYTHONPATH=src .venv/bin/python -m referral check-eval` (under a minute). It sends 80 facts that all pass the rule layer, half of them stale or with the wrong attribute, through both layers and scores them against ground truth.
- **Port.** The default port is 8791. Pass `--port` if it is taken.
- **Models.** Use `--buyer-model` and `--worker-model` (`haiku`, `sonnet`, `opus`) to change them.

## Recorded results (2026-10-25)

**Before the semantic layer** (rule layer only): five runs, all passed end to end. Committed: `runs/20261025-171910/` and `runs/20261025-172108/`.

**With the semantic layer** (both layers, Haiku 5.5 as judge): three runs. Committed: `runs/20261025-183929/` and `runs/20261025-184018/`.

- Referral gave the hard task to the Claude worker as a `bounded_trial`, because the worker had no record yet.
- The worker locked forecasts of 45–50%. Its delivery passed the rule layer on 5/5 facts, including the hidden slot, and the semantic layer judged all 5 and rejected none.
- The audit found:
  - 253 ledger entries with an intact chain;
  - no Checker false passes and no semantic false rejects;
  - a brief that matches ground truth on 5/5 facts, all from the passed job.
- After that one job the Claude worker is still `trial`, with the guidance "only one checked hard job so far".

The first of the three runs failed the audit. It exposed two bugs that were already there before the semantic layer, and we fixed both:

1. The worker answered Dunmore's flagship product as "Wren warehouse robot". The hidden check demanded an exact match with "Wren" and failed it, although the value is right. The hidden check and the audit now share one rule (`corpus.same_value`): the value must start with the true value as a whole token, so "Wren warehouse robot" matches "Wren", but "180" does not match "80", and a padded span that merely contains the answer does not match.
2. After that failure the buyer reused the four facts marked pass from the failed job and rematched only the fifth. Its rules said "use only facts whose Checker result is pass", which it read per fact. The proposal and the audit accept work per job, which also stops a buyer from using a failed job's facts without paying for them. The buyer's rule now says so explicitly.

**What the semantic layer catches** (`referral check-eval`, `runs/semantic-check-20261025.json`). We built 80 facts that all pass the rule layer: 40 correct, 16 stale (a 2024 figure that a 2026 update supersedes) and 24 with the wrong attribute (for example "Ironbark AI employs 40 people." given as Ironbark's latest funding round). The rule layer is run without the hidden check, which covers only one slot per job.

| | Rule layer only | Rules + semantic layer |
| --- | --- | --- |
| Stale facts passed | 16/16 | 0/16 |
| Wrong-attribute facts passed | 24/24 | 0/24 |
| Correct facts rejected | 0/40 | 0/40 |

A second run gave the same result. The judge never sees the ground truth or the labels.

## One-minute video plan

| Time | Screen | Narration |
| --- | --- | --- |
| 0–8s | The command in a terminal | Referral checks and keeps track records for agents that hire other agents; two Claude agents interact only through its MCP tools. |
| 8–20s | The buyer's `request_match` → `bounded_trial`, then the dispatch | The buyer agent makes its own request. Referral matches on difficulty and track record, and a new worker only gets a bounded trial. |
| 20–35s | The worker locks its forecast, reads, delivers; the buyer's `get_record` shows each fact passing and the line `semantic check (claude-haiku-5-5): ok, judged 5, rejected 0` | The forecast is locked first and cannot change. The Checker first checks every quote and a hidden slot, then a Claude judge reads the sources and fails any fact that quotes the wrong attribute or an outdated figure. |
| 35–45s | The final brief, then the `check-eval` table | The buyer uses only checked work. On 40 wrong facts that pass string checks, the judge lets none through and rejects no correct fact. |
| 45–55s | The audit: chain ok, 5/5 match ground truth, 0 false passes | We do not trust what the agents say; we check it independently. |
| 55–60s | The limitation | The last sentence of the paragraph below |

## Submission paragraph

Referral (team: Yvette Ge, Mengxiang (Louis) Liu) checks the work and keeps the track records of agents that hire other agents. In this MVP, two Claude Code agents interact only through Referral's MCP server. Acme Robotics' competitive-intelligence agent (Claude Sonnet 5.5) asks for five sourced competitor facts. Referral offers it a Claude Haiku 5.5 worker that has no record yet, as a bounded trial. The worker locks its success forecast before it reads any document, then delivers cited facts. Referral's Checker verifies every quote against the permitted corpus, plus one hidden known-answer slot; then a Claude judge reads the cited sources and fails facts that quote the wrong attribute or a superseded figure. On 80 adversarial facts that all pass string checks, it let 0 of 40 wrong facts through, against 40 of 40 for string checks alone, and rejected no correct fact. The buyer builds its brief only from a job that passed. An independent audit then re-checks the hash-chained ledger and compares every delivered fact with ground truth: 5 of 5 correct, no false passes. Limitation: the corpus is a small fictional set, the other five workers are simulated personas, and one checked job is too little evidence, so Referral still lists the Claude worker at the trial tier.
