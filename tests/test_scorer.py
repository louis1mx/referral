import re

from referral.models import Band, Tier
from referral.scorer import band_estimate, build_profile, forecasts_trusted, insights

AGENT = {"agent_id": "agt-x", "name": "x", "model": "atlas-large-2"}


def job(band, outcome, p, self_dealing=False, status=None, attributed=None):
    return {"band": band, "outcome": outcome, "self_dealing": int(self_dealing), "elapsed": 50.0,
            "cost": 1.0, "status": status or ("passed" if outcome else "failed"),
            "prediction": {"p_success": p, "cost": 1.0, "finish_s": 60.0},
            "attributed": attributed if attributed is not None else ([] if outcome else ["agt-x"])}


OUTCOMES = [("easy", 1), ("easy", 1), ("medium", 1), ("medium", 0), ("hard", 1), ("hard", 0)]


def test_honest_forecasts_score_better_than_overconfident():
    honest = build_profile(AGENT, [job(b, o, {"easy": 0.9, "medium": 0.6, "hard": 0.5}[b]) for b, o in OUTCOMES])
    overconfident = build_profile(AGENT, [job(b, o, 0.95) for b, o in OUTCOMES])
    assert honest.brier < overconfident.brier
    assert abs(honest.bias) < overconfident.bias


def test_hard_successes_weigh_more():
    easy_only = build_profile(AGENT, [job("easy", 1, 0.9)] * 3 + [job("hard", 0, 0.5)] * 3)
    hard_only = build_profile(AGENT, [job("easy", 0, 0.9)] * 3 + [job("hard", 1, 0.5)] * 3)
    assert hard_only.weighted_quality > easy_only.weighted_quality


def test_tiers():
    assert build_profile(AGENT, [job("easy", 1, 0.9)] * 3).tier == Tier.TRIAL          # too few jobs
    solid = [job(b, 1, 0.9) for b in ("easy", "medium", "hard")] * 5
    assert build_profile(AGENT, solid).tier == Tier.TRUSTED
    flaky = [job("hard", i % 2, 0.95) for i in range(10)]
    assert build_profile(AGENT, flaky).tier == Tier.TRIAL                                # overconfident


def test_forecasts_sharpen_estimate_only_when_calibrated():
    calibrated = build_profile(AGENT, [job("hard", o, 0.3) for o in (1, 0, 0, 0)] +
                               [job("easy", 1, 0.95)] * 4)
    with_f = band_estimate(calibrated, Band.HARD, use_forecasts=True)
    without = band_estimate(calibrated, Band.HARD, use_forecasts=False)
    assert with_f != without
    biased = build_profile(AGENT, [job("hard", 0, 0.95)] * 4 + [job("easy", 0, 0.95)] * 4)
    assert band_estimate(biased, Band.HARD, True) == band_estimate(biased, Band.HARD, False)


def test_insights_contain_no_numbers():
    p = build_profile(AGENT, [job(b, o, 0.95) for b, o in OUTCOMES * 2] + [job("easy", 1, 0.9, True)])
    notes = insights(p, Band.HARD)
    assert notes and not any(re.search(r"\d", n) for n in notes)
    assert any("overstate" in n for n in notes)
    assert any("self-commissioned" in n for n in notes)


def test_failures_traced_to_subcontractor_are_not_own_fault():
    p = build_profile(AGENT, [job("hard", 0, 0.5, attributed=["agt-sub"]), job("hard", 0, 0.5)])
    assert (p.own_fault_failures, p.traced_to_subcontractors) == (1, 1)


def test_band_gaming_does_not_buy_trust_on_hard_tasks():
    # Under-report easy jobs, over-report hard ones: overall bias is near zero.
    jobs = ([job("easy", 1, 0.8)] * 4 + [job("medium", o, 0.75) for o in (1, 1, 0, 1)]
            + [job("hard", o, 0.55) for o in (1, 0, 0, 0)])
    p = build_profile(AGENT, jobs)
    assert abs(p.bias) < 0.05
    assert p.bands[Band.HARD].bias > 0.25
    assert not forecasts_trusted(p, Band.HARD)
    assert band_estimate(p, Band.HARD, True) <= band_estimate(p, Band.HARD, False) + 0.01
    assert any("overstate its chances on hard" in n for n in insights(p))
