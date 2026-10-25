# Referral v1 design notes

Sources: our HW5 proposal (`Referral_Proposal.pdf`), the 10.21 meeting notes, and the team's Working List. The aim of v1 was an end-to-end prototype that runs live on demo day. Real LLM workers and fuller scoring would then replace its simulated parts, one step at a time.

## 1. What v1 had to show

Section 4 of the proposal ("Prototype and checks") was the acceptance test for v1:

| Proposal requirement | Where v1 does it |
| --- | --- |
| One buyer and four instrumented workers: reliable, honest-but-weak, overconfident, newcomer | four personas in `workers.py`, plus a padder for the record-padding misuse |
| A dated corpus with known answers | `corpus.py`: 8 fictional competitors of "Acme Robotics". Each has a 2024 profile and a 2026 update; the 2024 funding and headcount values are stale. |
| A two-hop chain where the reliable worker subcontracts a lookup to the weak one | the two-hop chain scene in `sim.py`. Each hop has its own contract and its own check. |
| Equal trial jobs first, then frozen profiles, then new tasks in fixed difficulty bands | the two-phase protocol in `evaluate.py` |
| Success means all 5 facts pass the Checker within budget and deadline; a no-match or a timeout is a failure | job settlement in `service.py` |
| Compare past success rate, outcomes-only profiles and full Referral on successes per dollar, added latency and attribution accuracy | the comparison table from `evaluate.py` |
| Misuse #1: an overconfident worker revises its forecast after dispatch. The Notary refuses, and hard tasks go elsewhere. | `sim.py`, scene 4 |
| Misuse #2: a worker pads its record with self-commissioned easy jobs. Its tier does not change. | `sim.py`, scene 5 |

## 2. Architecture: one service and one SQLite database

```
buyer agent  ──MCP──▶ ReferralService ──▶ Matcher  (picks a worker; returns tier, evidence, guidance, action)
worker agent ──MCP──▶        │         ──▶ Notary   (append-only, hash-chained log; locks forecasts)
                             │         ──▶ Checker  (rule layer: citations + hidden known-answer slot;
                             │                       semantic layer: an LLM judges meaning)
                             │         ──▶ Scorer   (log → profile → tier → descriptive insight)
                             ▼
                          SQLite (agents / matches / jobs / notary_log)
```

- **The Notary is the only source of truth.** Contracts, forecasts, deliveries and verdicts are all written to `notary_log`. Each entry carries `prev_hash` and `hash` and an HMAC by the acting agent's key, and `verify_chain()` detects any later edit.
- **Profiles are never stored.** They are rebuilt from the log every time, so only outcomes attached to locked, checked contracts count.
- **The output is a black box.** MCP tools never return raw scores or formulas; they return a tier, an evidence-strength label and plain-language guidance.

## 3. Scoring: v1 covers the three signals the proposal committed to

1. **Calibration, per difficulty band.** Each band has its own Brier score and bias (mean overstatement). With a single pooled bias, a worker could under-report easy jobs and over-report hard ones until the pooled bias is near zero, and look trustworthy. Tiers still use the overall Brier score. Brier is a proper scoring rule, so moving forecasts between bands cannot improve it.
2. **Difficulty-weighted quality.** Easy, medium and hard weigh 1, 2 and 3. Self-commissioned jobs, where buyer and worker share an owner, are logged but not counted.
3. **Chain attribution.** When a parent job fails, `via_job` leads to the hop that produced the bad fact. If the subcontract's own check also failed, the subcontractor is blamed; otherwise the upstream worker is.

The other three signals (stability and trend, cost and time overruns, delegator quality) are logged and computed but do not affect tiers in v1.

**Tiers** (v1 thresholds, to be tuned with data):

- `trial`: fewer than 4 counted jobs, or a model change was just declared. New agents start from a Beta prior based on their model's public benchmark.
- `verified`: at least 4 counted jobs, Brier ≤ 0.25, weighted quality ≥ 0.4.
- `trusted`: at least 15 counted jobs, Brier ≤ 0.18, weighted quality ≥ 0.65, and few failures that are the worker's own fault. Each worker gets 12 trial jobs, so after the trial phase a worker can reach `verified` at most.

**How the Matcher estimates success.** It uses a Beta posterior of outcomes in each band. A band's forecasts count as extra evidence only when the band has at least 3 forecasts and its own |bias| < 0.25, and their weight falls as that bias grows. The correction uses the band's bias, shrunk toward the overall bias (worth 4 jobs of overall bias). Inflated forecasts on hard tasks therefore cannot raise the hard-band estimate, and the insight says "tends to overstate its chances on hard tasks". A real model that is not in the benchmark table gets a placeholder prior of 0.75.

**How the Matcher picks.** Among candidates whose estimate is at least `min_success` (set by the buyer, default 0.35), it picks the most likely to pass; within 5 points it picks the cheaper one. The tier only decides between `hire` and `bounded_trial` and never filters candidates. If no candidate clears the floor, the answer is `no_eligible_match`.

**The hidden check (canary).** The live service draws the canary slot with `secrets`, so it cannot be predicted even from the public code. Only simulations, which pass a seed, derive it from (seed, task), so that strategies face identical draws. Every contract still commits to the canary with a salted hash.

**Credentials.** `get_credential` returns JSON shaped like a W3C Verifiable Credential, the format AgentFacts documents are signed in. It has an issuer, `validFrom`/`validUntil` (7 days), and a `credentialSubject` with the agent id, name, model, domain, tier, evidence label and the Notary chain head at issue time. The `proof` is an Ed25519 signature over the canonical JSON of the rest. This is our own simple scheme, not a standard Data Integrity cryptosuite. A credential carries no raw scores, and changing any field breaks the signature.

## 4. Simplifications in the v1 workers and Checker

- **Simulated workers, real deliveries.** Each persona has a per-fact accuracy for each band. When it gets a fact wrong it produces a real wrong delivery: a stale citation, an invented quote, a value missing from its quote, or a missing fact. The Checker runs its real, deterministic checks on these deliveries. The simulation is reproducible, free and offline.
- **Real agents connect directly.** The MCP server works over stdio or HTTP. Claude Code (or any MCP client) can act as a buyer and call `request_match` → `hire` → `get_record`. Any agent can also register as a worker and work through `get_assignment` / `submit_*`. `referral mvp` runs both sides with Claude Code (see `docs/hw6_mvp.md`).
- **`LLMWorker`, a real Claude worker inside the service.** It uses the same service API. It reads the corpus, locks its forecast in one request and delivers the facts in a second, both with structured outputs and the corpus in a cached system block. Three are defined: Opus 5.5, Sonnet 5.5 and Haiku 5.5. Server-side refusal fallbacks are deliberately off, because a fallback would answer with a different model and spoil the per-model calibration; a refusal is recorded as an API error. `referral live-eval --n 30` gives each model the same 30 tasks and reports, per band, the mean forecast, the checked pass rate, the Brier score, the bias, the latency and the token cost. It needs `ANTHROPIC_API_KEY`, prints a plan, and starts only with `--yes` (180 requests by default). Unit tests use a fake client and never call the API.
- **The Checker has two layers.**
  - **Rule layer** (`checker.py`, every job): the quote appears verbatim in a permitted corpus document, the value appears in the quote, and the document is about that company. **The hidden check:** one random slot per task is the canary. The Checker knows its current value, which catches stale citations in that slot. The simulator also records ground truth, used only to measure the Checker's own miss rate and never shown to Referral.
  - **Semantic layer** (`semantic.py`, live jobs). String checks cannot tell whether a quote *states* the requested attribute (the value "40" with the quote "Ironbark AI employs 40 people." passes as Ironbark's latest funding round), or whether a later document supersedes it (a 2024 round cited as the latest). Outside the canary slot, both pass the rule layer. The semantic layer sends the facts that passed the rules to a language model (Claude Haiku 5.5 by default, through `claude -p` with no tools and a JSON schema). The model gets each claim and every permitted document about that company with its date. It answers two questions: does the quote state this attribute, and is the value still current? A "no" fails the fact with the model's reason, and the verdict and the model's name go into the Notary.
  - **Why this split.** The judge only reads facts that passed the rules, so its whole input is trusted corpus text: a worker chooses which sentence to cite but cannot write prose or instructions into the judge's input. The judge never sees ground truth. The canary and the audit keep measuring it against the truth. If the model call fails twice, the rule verdicts stand and the verdict records `semantic_check.status = "unavailable"`. Tiers and scores stay deterministic: an LLM judges facts, never workers' reputations.
  - **Measured (`referral check-eval`, 2026-10-25, Haiku 5.5).** 80 facts that all pass the rule layer: 40 correct, 16 stale, 24 with the wrong attribute. With the rule layer alone, 40 of 40 wrong facts pass. With both layers, 0 of 40 pass and 0 of 40 correct facts are rejected. A second run gave the same result. Evidence: `runs/semantic-check-20261025.json`.
  - Simulations (`demo`, `eval`) and the seeded history in `serve` use the rule layer only, so they stay offline and reproducible.
- **Signatures.** Log entries are signed with HMAC keys that the server issues to each agent. Public credentials are signed with Referral's own Ed25519 key. Agent-held private keys come in v2.
- **Time.** Simulations use `SimClock`, which advances as workers spend time, and deadlines follow that clock. The live MCP flow uses the wall clock.

## 5. v1 results (simulation, 2026-10-22)

The protocol and the results table are in the README. Here is how we got there:

1. **Tiers stopped filtering candidates.** The first Matcher preferred non-trial workers. An ablation showed this added no success and cost more per job, so the tier now only picks the action.
2. **Calibration moved from pooled to per band.** The first version decided whether to trust forecasts from one pooled bias. Forecasts then beat outcome history by 1–2 points, but part of that gain came from calibration pooled across bands, which is exactly the loophole a worker could exploit.
3. **The per-band change exposed the old success floor.** After the change, an honest worker with only 4 trial jobs per band has about ±0.2 of noise in each band's bias. Forecast weights shrank and hard-band estimates fell back toward 0.5. The old 0.55 floor then often returned no-match, and hard-band success dropped from 0.72 to 0.38.
4. **The floor became a buyer parameter.** It is really the buyer's risk preference, so it is now `min_success`, default 0.35.

**Conclusion.** Every mechanism works, and Referral clearly beats a public-rating-style past success rate. With per-band calibration, forecasts roughly tie outcome history for picking workers. Their value is in three places:

- setting the tier through the Brier score;
- producing guidance such as "overstates its chances on hard tasks";
- leaving a record of commitments.

The proposal's open assumption is still open; `live-eval` on real models is the next test. Another option is to ask candidates for a forecast on this specific job before dispatch, making the forecast a per-job signal.

## 6. Roadmap

Done after v1:

- per-band calibration;
- unpredictable live canaries;
- `LLMWorker` and `live-eval`;
- `get_credential`;
- the HW6 MVP, in which two Claude Code agents hire and work through Referral, followed by an independent audit;
- the Checker's semantic layer and `check-eval` (2026-10-25).

Not done yet:

1. Run `live-eval` to get calibration data for real models (needs an API key and costs credit).
2. Bring stability and trend, cost overruns and delegator quality into tiers.
3. A demo-day page showing one hire's timeline, profile changes, the strategy comparison and real-model calibration.
4. Agent-held private keys for log entries, external validators' verdicts as extra evidence, and standard VC Data Integrity credentials.
5. Cold start: equal-exposure paired trials (from the Working List).
6. Pre-dispatch quotes: candidates give a job-specific forecast before they are hired.

## 7. Suggested ownership (from the proposal)

- **Yvette:**
  - protocol, Notary and the insight wording;
  - `notary.py`, `insights()` in `scorer.py`, and the tier thresholds.
- **Louis:**
  - MCP integration, the Checker and evaluation;
  - `mcp_server.py`, `checker.py` and `evaluate.py`.
