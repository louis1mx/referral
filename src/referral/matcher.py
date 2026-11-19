"""The Matcher: pick a worker for a task and decide hire / bounded trial / no match.

Three strategies share one interface so the evaluation can compare them on identical
histories:

- `success_rate`: past success rate over every job on file (what a public rating gives).
- `outcomes`: per-band outcome profiles that skip self-commissioned jobs, no forecasts.
- `referral`: outcome profiles plus per-band calibrated forecasts, tier-labelled actions and a
  buyer-set success floor that can answer no match.

`self_report` is a baseline outside that comparison: it hires whoever declared the highest
success rate at registration, exact ties going to the cheaper worker. It is what a buyer
does with no record at all, only the workers' own descriptions.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .models import BAND_TIME, Action, Band, TaskSpec, Tier
from .scorer import Profile, band_estimate

STRATEGIES = ("success_rate", "outcomes", "referral")
BASELINES = ("self_report",)

# Below this estimated chance of success Referral answers no_eligible_match. Buyers can
# pass their own `min_success`. 0.35 was picked on seeds 31-60: higher floors save money
# but refuse rematches the buyer would have won (see docs/plan.md, "v1 results").
DEFAULT_MIN_SUCCESS = 0.35
# Candidates within this much of the best estimate compete on price.
PRICE_TIE = 0.05


@dataclass
class Candidate:
    agent: dict
    profile: Profile
    estimate: float


@dataclass
class Decision:
    action: Action
    chosen: Candidate | None
    ranked: list[Candidate]


def feasible(agent: dict, spec: TaskSpec, band: Band) -> bool:
    if agent["price"] is not None and agent["price"] > spec.budget:
        return False
    if agent["typical_seconds"] is not None and agent["typical_seconds"] * BAND_TIME[band] > spec.deadline_s:
        return False
    return True


def estimate(profile: Profile, band: Band, strategy: str, agent: dict | None = None) -> float:
    if strategy == "self_report":
        return (agent or {}).get("declared_success") or 0.0
    if strategy == "success_rate":
        return (profile.raw_successes + 1) / (profile.raw_n + 2)
    return band_estimate(profile, band, use_forecasts=(strategy == "referral"))


def pick(cands: list[Candidate]) -> Candidate | None:
    if not cands:
        return None
    best = cands[0]
    for c in cands[1:]:
        if best.estimate - c.estimate <= PRICE_TIE and (c.agent["price"] or 0) < (best.agent["price"] or 0):
            best = c
    return best


def decide(spec: TaskSpec, band: Band, workers: list[tuple[dict, Profile]], strategy: str,
           exclude: set[str] = frozenset(), min_success: float | None = None) -> Decision:
    if strategy not in STRATEGIES + BASELINES:
        raise ValueError(f"unknown strategy {strategy!r}")
    ranked = sorted(
        (Candidate(a, p, estimate(p, band, strategy, a)) for a, p in workers
         if a["agent_id"] not in exclude and feasible(a, spec, band)),
        key=lambda c: (-c.estimate, c.agent["price"] or 0, c.agent["name"]),
    )
    if strategy == "self_report":
        # The sort already breaks exact ties by price; no PRICE_TIE band, since a declared
        # rate is a claim, not an estimate with error bars.
        chosen = ranked[0] if ranked else None
        return Decision(Action.HIRE if chosen else Action.NO_MATCH, chosen, ranked)
    if strategy != "referral":
        chosen = pick(ranked)
        return Decision(Action.HIRE if chosen else Action.NO_MATCH, chosen, ranked)

    # The tier labels the action but does not filter candidates. An earlier version hired
    # only non-trial workers when it could; on three seed sets it cost more per success
    # without raising the success rate (see docs/plan.md, "v1 results").
    floor = DEFAULT_MIN_SUCCESS if min_success is None else min_success
    chosen = pick([c for c in ranked if c.estimate >= floor])
    if chosen is None:
        return Decision(Action.NO_MATCH, None, ranked)
    action = Action.BOUNDED_TRIAL if chosen.profile.tier == Tier.TRIAL else Action.HIRE
    return Decision(action, chosen, ranked)


def explain_no_match(spec: TaskSpec, band: Band, workers: list[tuple[dict, Profile]], strategy: str,
                     exclude: set[str] = frozenset(), min_success: float | None = None) -> dict:
    """Why no worker was matched, and the smallest change to each buyer setting that would give
    a match with everything else unchanged. Added after the HW9 budget boundary runs, where
    clients told the buyer the wrong budget because `no_eligible_match` gave no reason.
    It reports counts, prices and deadlines only, never estimates or other raw scores."""
    floor = DEFAULT_MIN_SUCCESS if min_success is None else min_success
    pool = [a for a, _ in workers if a["agent_id"] not in exclude]
    est = {a["agent_id"]: estimate(p, band, strategy, a) for a, p in workers}
    fast = lambda a: a["typical_seconds"] is None or a["typical_seconds"] * BAND_TIME[band] <= spec.deadline_s
    cheap = lambda a: a["price"] is None or a["price"] <= spec.budget
    likely = lambda a: est[a["agent_id"]] >= floor
    reasons = {
        "workers_considered": len(pool),
        "excluded_by_you": len(workers) - len(pool),
        "over_budget": sum(not cheap(a) for a in pool),
        "too_slow_for_deadline": sum(not fast(a) for a in pool),
        "below_min_success": sum(not likely(a) for a in pool),
    }
    unblock: dict[str, float] = {}
    prices = [a["price"] or 0.0 for a in pool if fast(a) and likely(a)]
    if prices and min(prices) > spec.budget:
        unblock["budget_usd"] = round(min(prices), 2)
    times = [a["typical_seconds"] * BAND_TIME[band] for a in pool
             if cheap(a) and likely(a) and a["typical_seconds"] is not None]
    if times and min(times) > spec.deadline_s:
        unblock["deadline_seconds"] = float(math.ceil(min(times)))
    if any(cheap(a) and fast(a) for a in pool) and not any(cheap(a) and fast(a) and likely(a) for a in pool):
        unblock["min_success"] = "lower it, or split the task into easier parts"
    return {"reasons": reasons, "smallest_change_that_gives_a_match": unblock}
