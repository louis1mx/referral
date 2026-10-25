"""Calibration of real Claude models as Referral workers (live Anthropic API calls).

Every model gets the same tasks, balanced across difficulty bands. For each band we
report the mean locked forecast, the checked pass rate, the Brier score and the bias
(mean forecast minus outcome). These numbers are measured, not simulated; the report
says so and records the date, the models and the token cost.
"""

from __future__ import annotations

import json
import os
import random
import statistics
from datetime import date
from pathlib import Path

from .corpus import Corpus
from .models import BANDS, SimClock, Status
from .service import ReferralService
from .workers import LLM_WORKERS, LLMWorker

CALLS_PER_JOB = 2


def has_credentials() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"))


def plan(n: int, models: list[str]) -> str:
    per_band = [n // 3 + (1 if i < n % 3 else 0) for i in range(3)]
    return (f"{n} tasks per model ({', '.join(f'{b}: {k}' for b, k in zip(BANDS, per_band))}), "
            f"{len(models)} models ({', '.join(LLM_WORKERS[m][1] for m in models)}), "
            f"{n * len(models) * CALLS_PER_JOB} API requests")


def run_live(n: int, models: list[str], client=None, seed: int = 0, effort: str = "medium") -> dict:
    corpus = Corpus.default()
    service = ReferralService(":memory:", SimClock(), corpus, seed=None)
    buyer = service.register_agent("live-eval-buyer", "buyer", "owner-live-eval", "harness")
    workers = [LLMWorker(m, corpus, client=client, effort=effort) for m in models]
    for w in workers:
        w.register(service)
    rng = random.Random(f"live|{seed}")
    tasks = [corpus.make_task(rng, BANDS[i % 3]) for i in range(n)]

    rows = []
    for spec in tasks:
        for w in workers:
            job = service.direct_hire(buyer["agent_id"], buyer["key"], w.agent_id, spec.to_dict())
            rec = service.get_record(buyer["agent_id"], buyer["key"], job["job_id"])
            calls = [c for c in w.calls if c.job_id == job["job_id"]]
            rows.append({
                "model": w.model, "band": job["difficulty_band"], "job_id": job["job_id"],
                "status": rec["status"], "error": w.errors.get(job["job_id"]),
                "forecast": (rec["locked_forecast"] or {}).get("p_success"),
                "outcome": int(rec["status"] == Status.PASSED),
                "failed_checks": [f["check"] for f in rec["facts"] if f["check"] not in (None, "pass")],
                "seconds": sum(c.seconds for c in calls), "usd": sum(c.usd for c in calls),
            })
    return {"date": date.today().isoformat(), "source": "live Anthropic API calls",
            "effort": effort, "seed": seed, "rows": rows,
            "summary": summarize(rows),
            "insights": {w.model: service.get_insight(w.agent_id) for w in workers}}


def _stats(rows: list[dict]) -> dict:
    scored = [r for r in rows if r["error"] is None and r["forecast"] is not None]
    out = {"jobs": len(rows), "api_errors": len(rows) - len(scored), "usd": sum(r["usd"] for r in rows)}
    if scored:
        f = [r["forecast"] for r in scored]
        o = [r["outcome"] for r in scored]
        out.update({
            "mean_forecast": statistics.mean(f), "pass_rate": statistics.mean(o),
            "brier": statistics.mean((a - b) ** 2 for a, b in zip(f, o)),
            "bias": statistics.mean(a - b for a, b in zip(f, o)),
            "mean_seconds": statistics.mean(r["seconds"] for r in scored),
        })
    return out


def summarize(rows: list[dict]) -> dict:
    models = sorted({r["model"] for r in rows})
    return {m: {"all": _stats([r for r in rows if r["model"] == m]),
                **{str(b): _stats([r for r in rows if r["model"] == m and r["band"] == b]) for b in BANDS}}
            for m in models}


def print_report(result: dict) -> None:
    print(f"Measured with {result['source']} on {result['date']} (effort={result['effort']}). "
          "Not simulated.\n")
    print(f"{'model':<20}{'band':<8}{'jobs':>5}{'forecast':>10}{'passed':>8}{'brier':>8}{'bias':>8}"
          f"{'sec':>7}{'usd':>8}{'errors':>8}")
    for model, by_band in result["summary"].items():
        for band, st in by_band.items():
            if "pass_rate" in st:
                print(f"{model:<20}{band:<8}{st['jobs']:>5}{st['mean_forecast']:>10.2f}{st['pass_rate']:>8.2f}"
                      f"{st['brier']:>8.3f}{st['bias']:>+8.2f}{st['mean_seconds']:>7.1f}{st['usd']:>8.2f}"
                      f"{st['api_errors']:>8}")
            else:
                print(f"{model:<20}{band:<8}{st['jobs']:>5}{'-':>10}{'-':>8}{'-':>8}{'-':>8}{'-':>7}"
                      f"{st['usd']:>8.2f}{st['api_errors']:>8}")
    print("\nWhat Referral tells buyers about each model (tier and guidance only):")
    for model, ins in result["insights"].items():
        print(f"  {model:<20} [{ins['tier']}] " + "; ".join(ins["guidance"]))


def main(n: int, models: list[str], out: str, yes: bool, use_profile: bool, effort: str) -> int:
    try:
        import anthropic  # noqa: F401
    except ImportError:
        print("live-eval needs the Anthropic SDK: pip install -e '.[llm]'")
        return 2
    if not (has_credentials() or use_profile):
        print("Set ANTHROPIC_API_KEY (or ANTHROPIC_AUTH_TOKEN), or pass --use-profile to use an "
              "`ant auth login` profile.")
        return 2
    print(f"Plan: {plan(n, models)}.")
    if not yes:
        print("This spends real API credit. Re-run with --yes to start.")
        return 1
    result = run_live(n, models, effort=effort)
    print_report(result)
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    Path(out).write_text(json.dumps(result, indent=2, default=str))
    print(f"\nPer-job rows written to {out}")
    return 0
