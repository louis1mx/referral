import random

from referral.evaluate import attribution_experiment, run_strategy, summarize
from referral.models import Band
from referral.sim import build_world, pad_record, run_demo, run_trials


def test_padding_leaves_tier_and_counted_jobs_unchanged():
    world = build_world(seed=3)
    run_trials(world)
    pat = world.workers["padder"]
    before = world.service.profile(pat.agent_id)
    pad_record(world, 20)
    after = world.service.profile(pat.agent_id)
    assert after.raw_n == before.raw_n + 20
    assert after.n_counted == before.n_counted
    assert after.tier == before.tier


def test_revision_attempt_is_rejected_and_logged():
    world = build_world(seed=3)
    s = world.service
    olu = world.workers["overconfident"]
    olu.revise_next = True
    task = s.corpus.make_task(random.Random(1), Band.HARD)
    job = s.direct_hire(world.buyer_id, world.buyer_key, olu.agent_id, task.to_dict())
    assert olu.rejections and "cannot be revised" in olu.rejections[0]
    kinds = [e["kind"] for e in s.notary.entries(job["job_id"])]
    assert "prediction_rejected" in kinds and kinds[-1] == "verdict"


def test_strategies_see_identical_worker_outcomes():
    # Common random numbers: the same worker on the same task gets the same result in any world.
    a = summarize(run_strategy(2, "outcomes", tests_per_band=3))
    b = summarize(run_strategy(2, "outcomes", tests_per_band=3))
    a.pop("match_ms"), b.pop("match_ms")   # wall-clock time is the only thing allowed to differ
    assert a == b


def test_hop_contracts_attribute_failures_correctly():
    r = attribution_experiment(seed=1, n=20)
    assert r["failed"] > 0
    assert r["hop_contracts_accuracy"] == 1.0


def test_demo_runs(capsys):
    run_demo(seed=7)
    out = capsys.readouterr().out
    assert "cannot be revised" in out and "chain ok=True" in out and "ok=False" in out
