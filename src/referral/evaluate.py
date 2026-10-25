"""The comparison planned in the proposal.

Every strategy starts from an identical world: same seed, same equal-exposure trial
jobs, same padded record. Profiles are then frozen and each strategy handles the same
test requests in fixed difficulty bands. A worker's outcome on a task depends only on
(seed, worker, task), so differences come from who gets picked, not from luck.

A request succeeds when one hire passes every check within budget and deadline. The
buyer may rematch once after a failure. A no-match counts as a failure.

The second experiment checks chain attribution: on two-hop jobs that fail, does the
blame land on the agent that actually wrote the failing facts?
"""

from __future__ import annotations

import json
import random
import statistics
import time
from pathlib import Path

from .matcher import STRATEGIES
from .models import BANDS, Action, Band, Status
from .sim import build_world, pad_record, run_trials

LABELS = {"success_rate": "Past success rate", "outcomes": "Outcomes-only profile",
          "referral": "Full Referral"}


def run_strategy(seed: int, strategy: str, tests_per_band: int = 10, trials_per_band: int = 4,
                 padding: int = 20, max_attempts: int = 2) -> list[dict]:
    world = build_world(seed)
    run_trials(world, trials_per_band)
    pad_record(world, padding)
    s = world.service
    frozen = {w.agent_id: s.profile(w.agent_id) for w in world.workers.values()}
    rng = random.Random(f"tests|{seed}")
    tests = [s.corpus.make_task(rng, band) for band in BANDS for _ in range(tests_per_band)]

    rows = []
    for spec in tests:
        band = s.corpus.difficulty(spec.slots)
        tried: list[str] = []
        row = {"band": str(band), "success": False, "true_success": False, "spend": 0.0,
               "seconds": 0.0, "attempts": 0, "no_match": False, "match_ms": 0.0, "picked": []}
        for _ in range(max_attempts):
            t0 = time.perf_counter()
            m = s.request_match(world.buyer_id, world.buyer_key, spec.to_dict(), strategy, frozen,
                                exclude=tuple(tried))
            row["match_ms"] += (time.perf_counter() - t0) * 1000
            if m["action"] == Action.NO_MATCH:
                row["no_match"] = row["attempts"] == 0
                break
            job = s.hire(world.buyer_id, world.buyer_key, m["match_id"])
            rec = s.get_record(world.buyer_id, world.buyer_key, job["job_id"])
            worker = world.by_agent(m["candidate"]["agent_id"])
            tried.append(worker.agent_id)
            row["picked"].append(worker.persona.key)
            row["attempts"] += 1
            row["spend"] += rec["cost"] or 0.0
            row["seconds"] += rec["elapsed_s"] or 0.0
            if rec["status"] == Status.PASSED:
                row["success"] = True
                row["true_success"] = worker.truth[job["job_id"]].true_success
                break
        rows.append(row)
    return rows


def summarize(rows: list[dict]) -> dict:
    n = len(rows)
    spend = sum(r["spend"] for r in rows)
    wins = sum(r["success"] for r in rows)
    out = {
        "requests": n,
        "success_rate": wins / n,
        "true_success_rate": sum(r["true_success"] for r in rows) / n,
        "successes_per_dollar": wins / spend if spend else 0.0,
        "spend_per_request": spend / n,
        "attempts_per_request": sum(r["attempts"] for r in rows) / n,
        "seconds_per_request": sum(r["seconds"] for r in rows) / n,
        "match_ms": sum(r["match_ms"] for r in rows) / n,
        "no_match_rate": sum(r["no_match"] for r in rows) / n,
    }
    for b in BANDS:
        sub = [r for r in rows if r["band"] == b]
        out[f"success_{b}"] = sum(r["success"] for r in sub) / len(sub) if sub else None
    picks: dict[str, int] = {}
    for r in rows:
        if r["picked"]:
            picks[r["picked"][0]] = picks.get(r["picked"][0], 0) + 1
    out["first_picks"] = picks
    return out


def attribution_experiment(seed: int, n: int = 30) -> dict:
    """Two-hop jobs: reliable subcontracts the last two slots of each task to weak."""
    world = build_world(seed)
    s = world.service
    rae = world.workers["reliable"]
    rae.subcontract = True
    rng = random.Random(f"attribution|{seed}")
    failed = hop_correct = direct_correct = 0
    for i in range(n):
        spec = s.corpus.make_task(rng, Band.HARD if i % 2 else Band.MEDIUM)
        job = s.direct_hire(world.buyer_id, world.buyer_key, rae.agent_id, spec.to_dict())
        rec = s.get_record(world.buyer_id, world.buyer_key, job["job_id"])
        if rec["status"] == Status.PASSED:
            continue
        failed += 1
        truth = rae.truth[job["job_id"]]
        if rec["status"] == Status.TIMEOUT:
            actual = {rae.persona.key}
        else:
            bad_slots = [k for k, f in enumerate(rec["facts"]) if f["check"] != "pass"]
            actual = {truth.origins[k] for k in bad_slots}
        blamed = {world.by_agent(s.find_agent(name)["agent_id"]).persona.key
                  for name in rec["failure_traced_to"]}
        hop_correct += blamed == actual
        direct_correct += actual == {rae.persona.key}
    return {"chained_jobs": n, "failed": failed,
            "hop_contracts_accuracy": hop_correct / failed if failed else None,
            "direct_contractor_accuracy": direct_correct / failed if failed else None}


def _mean_sd(values: list[float]) -> tuple[float, float]:
    vals = [v for v in values if v is not None]
    if not vals:
        return (float("nan"), 0.0)
    return (statistics.mean(vals), statistics.pstdev(vals) if len(vals) > 1 else 0.0)


def run(seeds: int = 20, out: str | None = None, quiet: bool = False, first_seed: int = 1) -> dict:
    per_strategy = {k: [] for k in STRATEGIES}
    attribution = []
    for seed in range(first_seed, first_seed + seeds):
        for strategy in STRATEGIES:
            per_strategy[strategy].append(summarize(run_strategy(seed, strategy)))
        attribution.append(attribution_experiment(seed))

    metrics = ["success_rate", "true_success_rate", "success_easy", "success_medium", "success_hard",
               "successes_per_dollar", "spend_per_request", "attempts_per_request",
               "seconds_per_request", "match_ms", "no_match_rate"]
    table = {k: {m: _mean_sd([r[m] for r in per_strategy[k]]) for m in metrics} for k in STRATEGIES}
    picks = {k: {} for k in STRATEGIES}
    for k in STRATEGIES:
        for r in per_strategy[k]:
            for who, c in r["first_picks"].items():
                picks[k][who] = picks[k].get(who, 0) + c
    # Seeds are shared, so compare strategies seed by seed (mean difference ± standard error).
    paired = {}
    for base in ("success_rate", "outcomes"):
        for m in ("success_rate", "successes_per_dollar", "spend_per_request"):
            diffs = [r[m] - b[m] for r, b in zip(per_strategy["referral"], per_strategy[base])]
            se = statistics.stdev(diffs) / len(diffs) ** 0.5 if len(diffs) > 1 else 0.0
            paired[f"referral_minus_{base}:{m}"] = (statistics.mean(diffs), se)
    attr = {
        "failed_chained_jobs": sum(a["failed"] for a in attribution),
        "hop_contracts_accuracy": _mean_sd([a["hop_contracts_accuracy"] for a in attribution]),
        "direct_contractor_accuracy": _mean_sd([a["direct_contractor_accuracy"] for a in attribution]),
    }
    result = {"seeds": list(range(first_seed, first_seed + seeds)), "strategies": table, "paired_differences": paired,
              "first_picks": picks, "attribution": attr}

    if not quiet:
        print(f"Comparison over seeds {first_seed}-{first_seed + seeds - 1}; 30 test requests per seed (10 per band); "
              "one rematch allowed; mean ± sd across seeds.\n")
        header = f"{'metric':<24}" + "".join(f"{LABELS[k]:>26}" for k in STRATEGIES)
        print(header)
        print("-" * len(header))
        for m in metrics:
            cells = "".join(f"{table[k][m][0]:>18.3f} ± {table[k][m][1]:<5.3f}" for k in STRATEGIES)
            print(f"{m:<24}{cells}")
        print("\nFull Referral minus each baseline, paired by seed (mean ± standard error):")
        for name, (mean, se) in paired.items():
            base, m = name.removeprefix("referral_minus_").split(":")
            print(f"  vs {LABELS[base]:<22} {m:<22} {mean:+.3f} ± {se:.3f}")
        print("\nFirst pick per request (all seeds):")
        for k in STRATEGIES:
            total = sum(picks[k].values()) or 1
            share = ", ".join(f"{w} {c / total:.0%}" for w, c in sorted(picks[k].items(), key=lambda x: -x[1]))
            print(f"  {LABELS[k]:<24} {share}")
        print(f"\nChain attribution on {attr['failed_chained_jobs']} failed two-hop jobs:")
        print(f"  hop-level contracts (Referral): {attr['hop_contracts_accuracy'][0]:.0%} correct")
        print(f"  blame the direct contractor:    {attr['direct_contractor_accuracy'][0]:.0%} correct")
    if out:
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        Path(out).write_text(json.dumps(result, indent=2))
    return result
