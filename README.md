# Referral: verified track records for agents that hire agents

MIT IDS.865 final project, Yvette Ge and Mengxiang (Louis) Liu. This is the v1 prototype described in our HW5 proposal.

Before a job, the worker agent locks its forecast of success, cost and time. After it delivers, Referral checks the result and scores how far the delivery fell from the promise, adjusting for task difficulty and tracing failures to the subcontractor that caused them. Hiring agents call Referral as an MCP server. They get back a tier and short guidance, never raw scores. Referral can also issue a signed credential, so registries such as ERC-8004 or NANDA AgentFacts can carry a checked track record instead of open ratings.

## Team

- Yvette Ge (Harvard GSD): protocol, Notary, insight wording
- Mengxiang (Louis) Liu (Harvard HSPH): MCP integration, Checker, evaluation

## Status

- **Proposal:** HW5.
- **v1 prototype:** done (2026-10-22).
- **HW6 MVP:** done (2026-10-25). Two real Claude Code agents hire and deliver through Referral's MCP server, and an independent audit checks the result.
- **Checker semantic layer:** done (2026-10-25). A language model judges whether each cited quote states the requested attribute and is still current; `referral check-eval` measures it.
- **Next:** see the roadmap in `docs/design.md`. Demo day is the final deliverable.

## Setup

You need:

- Python 3.11 or later (we use 3.14 on macOS);
- for `referral mvp` and `referral check-eval` only: the [Claude Code](https://claude.com/claude-code) CLI on your `PATH`, signed in (`claude` then `/login`);
- for `live-eval` only: an `ANTHROPIC_API_KEY`.

```bash
git clone https://github.com/louis1mx/referral.git && cd referral
python3 -m venv .venv
.venv/bin/pip install -r requirements-lock.txt -e .     # exact versions we tested
# or: .venv/bin/pip install -e ".[dev,llm]"             # latest compatible versions
export PYTHONPATH=src
```

Always set `PYTHONPATH=src`. On macOS with Python 3.13 or later, the editable install's `.pth` file can get the hidden flag, and Python then skips it. The commands below assume you are in the repository root with `PYTHONPATH=src` set.

## Check that it works

Each command below should produce the result shown. The first three need no network, no API key and no Claude account.

| Command | What you should see |
| --- | --- |
| `.venv/bin/python -m pytest -q` | `66 passed` in a few seconds |
| `.venv/bin/python -m referral demo` | eight narrated scenes in about a second. Scene 3: nia-newcomer fails one fact, then rae-reliable passes on the rematch. Scene 8: `chain ok=True`, and the tampered copy shows `ok=False`. |
| `.venv/bin/python -m referral eval --seeds 30` | the table in "v1 results" below, written to `results/eval.json` |
| `.venv/bin/python -m referral check-eval` | `stale facts passed 16/16 → 0/16`, `wrong_attribute facts passed 24/24 → 0/24`, `correct facts rejected 0/40` (needs Claude Code; under a minute) |
| `.venv/bin/python -m referral mvp` | two Claude agents hire and deliver through Referral, the semantic layer judges each delivery, then `RESULT: all checks pass` (needs Claude Code; one to a few minutes) |

`demo` and `eval` are deterministic: the same seed gives the same output on any machine, because simulations use the Checker's rule layer only. `check-eval` and `mvp` use real models, so its wording and forecasts change from run to run. Compare yours with the committed runs in `runs/`.

The demo defaults to seed 4. We picked it because every beat of the story shows up, and each beat is typical across 50 seeds:

- The overconfident worker is flagged as overstating its chances in 50 of 50 seeds and stays at the trial tier in 42.
- The first hard hire passes in 25 of 50 seeds; with one rematch, 36 of 50 pass.
- Seed 4 shows the rematch path.

Every seed runs the same code; `--seed N` shows others.

## Commands

| Command | What it does |
| --- | --- |
| `referral demo [--seed N]` | narrated simulation of hires, misuse and a two-hop chain |
| `referral eval --seeds N` | compares three ways of picking workers on identical histories |
| `referral serve` | Referral as an MCP server over stdio. `--history none` starts with no simulated workers (the Nanda Town integration uses this). Add `--transport http --port 8791` for HTTP, `--claude-worker haiku` to add a Claude worker that Claude Code runs on dispatch, and `--semantic-checker haiku` to turn on the semantic layer for live jobs. |
| `referral mvp [--checker-model haiku\|none]` | the HW6 run: a Claude buyer agent hires through Referral, then the run is audited |
| `referral check-eval [--model haiku]` | 80 rule-passing facts (half stale or wrong-attribute) through the rule layer vs. both layers |
| `referral audit runs/<timestamp>` | re-checks a saved run from its ledger and answer alone |
| `referral live-eval --n 30` | measures real Claude workers' calibration; prints a plan and needs `--yes` |

Run each one as `.venv/bin/python -m referral ...`.

### Use it from Claude Code or another MCP client

`referral serve` runs a stdio MCP server. At startup it seeds a history: five simulated workers, each with 12 trial jobs.

1. Copy `.mcp.json.example` to `.mcp.json` in the folder you open Claude Code in. Make its paths absolute if that folder is not this repository.
2. Ask the agent to register as a buyer and hire someone for a task, for example: "Get the latest funding and headcount for three Acme Robotics competitors through Referral."

### HW6 MVP: two Claude agents through Referral

```bash
.venv/bin/python -m referral mvp      # about 40 seconds, about $0.04 of Claude usage
.venv/bin/python -m referral audit runs/<timestamp>
```

`mvp` serves Referral over HTTP (`serve --transport http --claude-worker haiku`). It then starts a buyer agent: Claude Code in headless mode on Sonnet 5.5, whose only tools are Referral's MCP tools. When Referral dispatches a job to the Claude Haiku worker, a dispatch hook starts that worker's own Claude Code runtime. The worker also acts only through the MCP tools. The buyer waits for the verdict with `get_record(wait_seconds=...)`.

`audit` re-checks the run from the SQLite ledger and the buyer's answer alone:

- the hash chain and signatures;
- that each forecast was locked before its delivery;
- that each hidden-check commitment opens;
- each Checker verdict against ground truth;
- that every fact in the brief is correct and comes from a passed job.

Run folders, the recorded results, the video plan and the submission paragraph are in `docs/hw6_mvp.md`.

## How a hire works

1. The buyer calls `request_match` with the task (competitor/attribute slots from a permitted corpus), the acceptance criteria, a budget and a deadline. It can also pass `min_success`, the lowest chance of success worth paying for. Referral assigns a difficulty band. It returns a candidate with a tier, an evidence-strength label, guidance, and an action: `hire`, `bounded_trial` or `no_eligible_match`.
2. `hire` locks a contract in the Notary and dispatches the task, without the hidden canary slot.
3. The worker calls `submit_prediction` to lock its success probability, cost and finish time. A second call is rejected and logged. A delivery without a locked forecast is also rejected.
4. The worker calls `submit_delivery`. The Checker verifies each fact in two layers. **Rules:** the cited document is permitted and is about that competitor, the quote appears in it verbatim, and the value appears in the quote. One hidden known-answer slot also has to match the current value. **Semantics** (when on): a language model reads the rule-passing facts with every permitted document about that company and fails any fact whose quote does not state the requested attribute, or whose value a later document supersedes. A timeout or a cost over budget counts as a failure.
5. The buyer calls `get_record`. Each fact has a pass/fail reason, and the record ends in `accept` or `reject_and_rematch`. For a rematch, the buyer calls `request_match` again with `exclude_workers`.

A worker can `subcontract` part of a job. Each hop gets its own contract and its own check, so a failure is traced to the agent whose output caused it.

| Tool | Caller | Purpose |
| --- | --- | --- |
| `register_agent` | any | first call; returns `agent_id` and a key used to authenticate and sign log entries |
| `declare_model_change` | worker | a new model starts a new trial profile |
| `describe_corpus`, `read_document` | any | the permitted, dated source corpus |
| `request_match`, `hire`, `get_record` | buyer | find, hire and check |
| `get_assignment`, `submit_prediction`, `submit_delivery`, `subcontract` | worker | do the work |
| `get_insight` | any | a worker's tier and guidance |
| `get_credential`, `get_issuer_key`, `verify_credential` | any | signed tier attestation, and the public key to verify it |

## Design

One service (`service.py`) and one SQLite database hold five components:

- **Matcher** (`matcher.py`) estimates each candidate's chance of passing a task in the requested band and hires the most likely one. If candidates are within 5 points, it hires the cheapest. It returns `no_eligible_match` when no candidate clears the buyer's `min_success` (default 0.35). The tier decides between `hire` and `bounded_trial`; it does not filter candidates.
- **Notary** (`notary.py`) keeps an append-only, hash-chained log of contracts, forecasts, deliveries, verdicts, refused attempts and issued credentials. SQLite triggers block updates and deletes, and each entry carries an HMAC made with the acting agent's key. Each contract commits to the hidden canary with a salted hash; the verdict reveals it afterwards so an auditor can check it. A live service draws the canary with `secrets`. Only simulations, which pass a seed, derive it from (seed, task) so that strategies can be compared on identical draws.
- **Checker** (`checker.py`, `semantic.py`) runs deterministic citation checks, the hidden canary and chain attribution, then the semantic layer: an LLM judge that reads only trusted corpus text and never sees ground truth. Tiers and scores stay deterministic. See `docs/design.md` §4 for why, and for the `check-eval` numbers.
- **Scorer** (`scorer.py`) rebuilds each profile from settled jobs under the worker's current model. v1 scores three of the proposal's six signals:
  - Calibration, judged per difficulty band: Brier score and bias in each band.
  - Difficulty-weighted quality, with weights 1/2/3.
  - Chain attribution.

  Stability/trend and cost/time overruns are computed but do not affect tiers yet. Self-commissioned jobs, where the buyer and worker share an owner, are logged but not counted.
- **Issuer** (`credentials.py`) signs credentials with Ed25519. Anyone can verify them offline with the public key from `get_issuer_key`.

Tiers:

- `trial`: fewer than 4 counted jobs, or the profile fails the verified thresholds.
- `verified`: overall Brier score ≤ 0.25 and weighted quality ≥ 0.4.
- `trusted`: at least 15 jobs, Brier score ≤ 0.18, weighted quality ≥ 0.65, and few failures that are the worker's own fault.

The Brier score is a proper scoring rule, so the overall score cannot be gamed by shifting forecasts between bands.

The Matcher's estimate starts from a Beta prior based on the model's public benchmark. Fictional sim models have illustrative values; real models get a placeholder (0.75) until we source one. The prior is updated with per-band outcomes. Forecasts in a band count as extra evidence only when that band's own bias is small (at least 3 forecasts, |bias| < 0.25), and their weight falls as that bias grows. A worker that under-reports easy jobs and over-reports hard ones therefore gains nothing on hard tasks, and its guidance says it overstates its chances there.

### Credentials

`get_credential(worker_id)` returns a credential shaped like a W3C Verifiable Credential, the format AgentFacts documents are signed as. It has `issuer`, `validFrom`/`validUntil` (7 days), and a `credentialSubject` with the agent id, name, model, domain, tier, evidence label and the Notary chain head at issue time. The `proof` is an Ed25519 signature over the canonical JSON of the rest. This is our own simple scheme, not a conforming Data Integrity cryptosuite. A credential never contains raw scores. Changing any field breaks the signature.

## Simulation

`workers.py` has five instrumented personas with fictional models:

| Persona | Behavior |
| --- | --- |
| `rae-reliable` | strong, honest forecasts, $1.60 per job |
| `hal-honest-weak` | weak on hard tasks, honest forecasts, $0.60 |
| `olu-overconfident` | forecasts at least 90% on every job |
| `nia-newcomer` | strong, but starts with no record |
| `pat-padder` | weak; pads its record with self-commissioned easy jobs |

The corpus (`corpus.py`) is fictional: 8 competitors of "Acme Robotics", each with a 2024 profile and a 2026 update. Three competitors also share a name with an unrelated look-alike firm. When a persona gets a fact wrong, it produces a real wrong delivery for the Checker to catch: a stale citation, a look-alike firm, an invented quote, a value missing from its quote, or no fact at all. Ground truth is kept only for evaluation.

## Live Claude workers

`LLMWorker` (`workers.py`) is a worker backed by a real Claude model. It uses the same service API as any other agent:

1. Read the permitted documents.
2. Lock a forecast in one request.
3. Produce the facts in a second request.

Both requests use structured outputs (`output_config.format`), with the corpus in a cached system block. Three workers are defined, `claude-opus-5-5`, `claude-sonnet-5-5` and `claude-haiku-5-5`, with illustrative per-job fees. Server-side refusal fallbacks are deliberately off: a fallback would silently answer with a different model and spoil the per-model calibration. A refusal is recorded as an API error instead.

`referral live-eval --n 30` gives every model the same 30 tasks, balanced across bands. For each model and band it reports the mean locked forecast, the checked pass rate, the Brier score, the bias, the latency and the token cost. It also prints the tier and guidance Referral would show buyers. The run needs `ANTHROPIC_API_KEY` (or `--use-profile`), prints a plan, and only starts with `--yes`. The default run makes 180 requests. The report is labelled as measured, with the date. Unit tests use a fake client and never call the API.

We have not run `live-eval` yet, so there are no measured results in this README.

## v1 results (simulation, `referral eval --seeds 30`)

The protocol follows the proposal. Each strategy starts from an identical history: 12 equal trial jobs per worker, plus 20 self-commissioned jobs for the padder. Profiles are frozen, then each strategy handles 30 requests per seed, 10 per band, with one rematch allowed. A worker's outcome depends only on (seed, worker, task), so the strategies can be compared seed by seed. A no-match counts as a failure.

| Seeds 1–30 | Past success rate | Outcomes-only profile | Full Referral |
| --- | --- | --- | --- |
| Success rate | 0.827 | 0.867 | 0.878 |
| Hard-band success | 0.630 | 0.723 | 0.760 |
| Successes per dollar | 0.570 | 0.667 | 0.658 |
| Spend per request | $1.49 | $1.33 | $1.37 |

Paired differences by seed (mean ± standard error):

- **Full Referral vs. past success rate.** On seeds 1–30, success rate is +5.1 ± 1.5 points, successes per dollar are +0.089 ± 0.020, and spend is $0.12 less per request. On seeds 61–90, success rate is +1.6 ± 1.3 points and successes per dollar are +0.086 ± 0.016.
- **Full Referral vs. outcomes-only profiles.** Success rate is +1.1 ± 0.6 points on seeds 1–30, +0.9 ± 0.4 on seeds 31–60, and +0.2 ± 0.3 on seeds 61–90. Successes per dollar are about 0.01 lower on each set, which is not significant. In practice the two are tied.
- **Chain attribution.** On failed two-hop jobs, hop-level contracts trace the failure to the right agent 100% of the time. Blaming the direct contractor is right 51–54% of the time.

The success floor is a buyer's risk preference, so it is now the `min_success` parameter. We picked the default on seeds 31–60 and checked it on the other two sets:

| Floor (seeds 31–60) | Success vs. outcomes-only | Successes per dollar | No-match rate |
| --- | --- | --- | --- |
| 0.55 (previous default) | −8.2 points | +0.037 | 7.8% |
| 0.45 | −2.0 | −0.004 | 1.1% |
| 0.35 (default) | +0.9 | −0.011 | 0% |

Two caveats apply. First, we wrote the personas and their parameters, so these numbers test the mechanism, not real agents. Second, the open assumption in our proposal is still open. Earlier, forecasts raised success by 1–2 points over outcome history, but that gain came partly from pooling calibration across bands, which a worker could game. With calibration judged per band, forecasts mainly do three things: they set the tier through the Brier score, they produce the "overstates its chances on hard tasks" guidance, and they leave a record of commitments. They no longer add much to picking. `live-eval` is the next test.

## Not in v1

- Measured live results. `live-eval` exists but has not been run.
- Stability/trend, cost and time overruns, and delegator quality in tiers.
- Agent-held asymmetric keys for log entries. Agents still use a server-issued HMAC key; only the credential issuer uses Ed25519.
- Equal-exposure paired trials for newcomers.
- Sybil buyers with different owners. v1 only catches self-dealing by shared owner.

## Repository layout

```
src/referral/
  models.py         data types: bands, tiers, tasks, facts, clocks
  notary.py         SQLite store, hash-chained log, HMAC signatures
  corpus.py         the fictional dated corpus, ground truth, task generation
  checker.py        citation checks, the hidden check, chain attribution, semantic review
  semantic.py       the semantic layer's LLM judge (Claude Code, structured output)
  check_eval.py     rule layer vs. rules + semantic layer on adversarial facts
  scorer.py         profiles, tiers and descriptive insights
  matcher.py        picking a worker and the action
  service.py        ReferralService: all business rules and permissions
  credentials.py    Ed25519-signed tier credentials
  mcp_server.py     the MCP tools
  workers.py        simulated personas and LLMWorker (Claude through the API)
  claude_agents.py  Claude Code buyer and worker runtimes for the MVP
  mvp.py, trace.py  the HW6 run and its live trace
  audit.py          independent check of a saved run
  sim.py            demo scenes
  evaluate.py       strategy comparison
  live_eval.py      real-model calibration
  cli.py            the `referral` command
tests/              unit and scenario tests (no network)
docs/design.md      design notes, results history, roadmap, ownership
docs/hw6_mvp.md     the HW6 MVP: what runs, recorded results, video plan
runs/               committed MVP runs and the check-eval result (evidence)
results/            eval output (git-ignored; regenerate with `referral eval`)
```

## Working on it together

- Branch from `main` (for example `yvette/insight-wording`), open a pull request, and ask the other person to review it.
- Run `.venv/bin/python -m pytest -q` before you push. A change to scoring or matching should also re-run `referral eval --seeds 30` and update the results tables if they move.
- Keep the black-box rule: no MCP tool returns raw scores.
- Commit an `mvp` run folder only when it is evidence for a writeup.
- Write code, comments and docs in English.

