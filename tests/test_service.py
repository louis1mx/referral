import random

import pytest

from referral.models import Band, ReferralError, SimClock, Status
from referral.service import ReferralService


def hire_worker(service, buyer, worker, task):
    return service.direct_hire(*buyer, worker[0], task)["job_id"]


def test_external_worker_full_flow(service, buyer, worker, easy_task, correct_facts):
    match = service.request_match(*buyer, easy_task)
    assert match["action"] == "bounded_trial"          # the only worker is new, so trial tier
    assert match["candidate"]["agent_id"] == worker[0]
    job = service.hire(*buyer, match["match_id"])
    assert job["status"] == Status.DISPATCHED

    [assignment] = service.get_assignment(*worker)
    assert "canary" not in str(assignment)              # the hidden check is not revealed
    service.submit_prediction(*worker, job["job_id"], 0.8, 1.0, 60)
    service.submit_delivery(*worker, job["job_id"], correct_facts(easy_task), cost=1.0)

    rec = service.get_record(*buyer, job["job_id"])
    assert rec["status"] == Status.PASSED
    assert rec["recommendation"] == "accept"
    assert all(f["check"] == "pass" for f in rec["facts"])
    kinds = [e["kind"] for e in service.notary.entries(job["job_id"])]
    assert kinds == ["contract", "prediction", "delivery", "verdict"]
    assert service.verify_ledger()["ok"]


def test_forecast_cannot_be_revised(service, buyer, worker, easy_task):
    job_id = hire_worker(service, buyer, worker, easy_task)
    service.submit_prediction(*worker, job_id, 0.9, 1.0, 60)
    with pytest.raises(ReferralError, match="cannot be revised"):
        service.submit_prediction(*worker, job_id, 0.3, 1.0, 60)
    rejected = [e for e in service.notary.entries(job_id) if e["kind"] == "prediction_rejected"]
    assert rejected and rejected[0]["payload"]["attempted"]["p_success"] == 0.3
    assert service._job(job_id)["prediction"]["p_success"] == 0.9


def test_delivery_requires_locked_forecast(service, buyer, worker, easy_task, correct_facts):
    job_id = hire_worker(service, buyer, worker, easy_task)
    with pytest.raises(ReferralError, match="lock a forecast"):
        service.submit_delivery(*worker, job_id, correct_facts(easy_task))


def test_permissions(service, buyer, worker, easy_task):
    job_id = hire_worker(service, buyer, worker, easy_task)
    other = service.register_agent("other-worker", "worker", "owner-o", "atlas-mini-2", price=0.5)
    other_buyer = service.register_agent("other-buyer", "buyer", "owner-ob", "buyer-llm")
    with pytest.raises(ReferralError, match="not assigned to you"):
        service.submit_prediction(other["agent_id"], other["key"], job_id, 0.5, 1, 10)
    with pytest.raises(ReferralError, match="own jobs"):
        service.get_record(other_buyer["agent_id"], other_buyer["key"], job_id)
    with pytest.raises(ReferralError, match="wrong key"):
        service.submit_prediction(worker[0], "bad-key", job_id, 0.5, 1, 10)
    with pytest.raises(ReferralError, match="cannot do this"):
        service.add_validator_note(*buyer, job_id, "looks fine")
    checker = service.add_checker("external-validator")
    assert service.add_validator_note(checker["agent_id"], checker["key"], job_id, "ok")["logged"]


def test_timeout_counts_as_failure(service, buyer, worker, easy_task, correct_facts):
    job_id = hire_worker(service, buyer, worker, easy_task)
    service.submit_prediction(*worker, job_id, 0.9, 1.0, 60)
    service.clock.advance(easy_task["deadline_s"] + 1)
    rec = service.get_record(*buyer, job_id)
    assert rec["status"] == Status.TIMEOUT and rec["recommendation"] == "reject_and_rematch"
    with pytest.raises(ReferralError, match="already timeout"):
        service.submit_delivery(*worker, job_id, correct_facts(easy_task))


def test_buyer_pays_the_contract_price_not_the_workers_claim(service, buyer, worker, easy_task, correct_facts):
    job_id = hire_worker(service, buyer, worker, easy_task)
    service.submit_prediction(*worker, job_id, 0.9, 1.0, 60)
    service.submit_delivery(*worker, job_id, correct_facts(easy_task), cost=easy_task["budget"] + 1)
    rec = service.get_record(*buyer, job_id)
    assert rec["status"] == Status.PASSED and rec["cost"] == service._job(job_id)["price"]
    assert service._job(job_id)["reported_cost"] == easy_task["budget"] + 1
    delivery = next(e for e in service.notary.entries(job_id) if e["kind"] == "delivery")
    assert delivery["payload"]["reported_cost"] == easy_task["budget"] + 1
    assert service.profile(worker[0]).cost_overruns == 1   # the claim still counts as a cost miss


def test_contract_price_over_budget_fails(service, buyer, easy_task, correct_facts):
    pricey = service.register_agent("pricey", "worker", "owner-p", "atlas-large-2",
                                    price=easy_task["budget"] + 1)
    job_id = service.direct_hire(*buyer, pricey["agent_id"], easy_task)["job_id"]
    service.submit_prediction(pricey["agent_id"], pricey["key"], job_id, 0.9, 1.0, 60)
    service.submit_delivery(pricey["agent_id"], pricey["key"], job_id, correct_facts(easy_task))
    rec = service.get_record(*buyer, job_id)
    assert rec["status"] == Status.FAILED and rec["within_budget"] is False


def test_self_commissioned_jobs_do_not_count(service, worker, easy_task, correct_facts):
    shell = service.register_agent("shell", "buyer", "owner-worker", "x")   # same owner as worker
    job_id = service.direct_hire(shell["agent_id"], shell["key"], worker[0], easy_task)["job_id"]
    service.submit_prediction(*worker, job_id, 0.9, 1.0, 60)
    service.submit_delivery(*worker, job_id, correct_facts(easy_task))
    p = service.profile(worker[0])
    assert (p.raw_n, p.n_counted, p.n_self_dealing) == (1, 0, 1)


def test_model_change_restarts_profile(service, buyer, worker, easy_task, correct_facts):
    job_id = hire_worker(service, buyer, worker, easy_task)
    service.submit_prediction(*worker, job_id, 0.9, 1.0, 60)
    service.submit_delivery(*worker, job_id, correct_facts(easy_task))
    assert service.profile(worker[0]).n_counted == 1
    service.declare_model_change(*worker, "nimbus-3.5")
    p = service.profile(worker[0])
    assert p.n_counted == 0 and p.previous_models == ["atlas-large-2"]
    assert "model change" in service.get_insight(worker[0])["guidance"][0]


def test_match_rejects_unknown_slots(service, buyer, easy_task):
    bad = dict(easy_task, slots=[{"competitor": "Nobody Inc", "attribute": "hq_city"}])
    with pytest.raises(ReferralError, match="unknown competitor"):
        service.request_match(*buyer, bad)


def test_match_can_only_be_hired_once(service, buyer, worker, easy_task):
    match = service.request_match(*buyer, easy_task)
    service.hire(*buyer, match["match_id"])
    with pytest.raises(ReferralError, match="already used"):
        service.hire(*buyer, match["match_id"])


def _canaries(service, buyer, worker, task, n=30):
    return [service._job(service.direct_hire(*buyer, worker[0], task)["job_id"])["canary"]
            for _ in range(n)]


def _service_with_agents(seed):
    s = ReferralService(":memory:", SimClock(), seed=seed)
    b = s.register_agent("b", "buyer", "ob", "m")
    w = s.register_agent("w", "worker", "ow", "m", price=1.0)
    return s, (b["agent_id"], b["key"]), (w["agent_id"], w["key"])


def test_live_canary_is_not_a_function_of_the_task(easy_task):
    s, b, w = _service_with_agents(seed=None)
    assert len(set(_canaries(s, b, w, easy_task))) > 1


def test_live_canary_comes_from_secrets(easy_task, monkeypatch):
    import referral.service as svc
    s, b, w = _service_with_agents(seed=None)
    monkeypatch.setattr(svc.secrets, "randbelow", lambda n: n - 1)
    assert _canaries(s, b, w, easy_task, n=3) == [len(easy_task["slots"]) - 1] * 3


def test_simulation_canary_is_reproducible(easy_task):
    s1, b1, w1 = _service_with_agents(seed=4)
    s2, b2, w2 = _service_with_agents(seed=4)
    assert _canaries(s1, b1, w1, easy_task, 3) == _canaries(s2, b2, w2, easy_task, 3)


def test_buyer_floor_turns_a_weak_pool_into_no_match(service, buyer, worker, easy_task):
    assert service.request_match(*buyer, easy_task)["action"] != "no_eligible_match"
    m = service.request_match(*buyer, easy_task, min_success=0.99)
    assert m["action"] == "no_eligible_match" and m["candidate"] is None
    with pytest.raises(ReferralError, match="min_success"):
        service.request_match(*buyer, easy_task, min_success=2)


def test_exclude_workers_by_name(service, buyer, worker, easy_task):
    match = service.request_match(*buyer, easy_task, exclude=("test-worker",))
    assert match["action"] == "no_eligible_match"


def test_declared_success_is_recorded_but_only_self_report_reads_it(service, buyer, corpus):
    for name, declared, price in (("modest", 0.6, 0.5), ("boastful", 0.95, 1.5), ("cheap-boast", 0.95, 1.0)):
        service.register_agent(name, "worker", f"owner-{name}", "atlas-mini-2", price=price,
                               declared_success=declared)
    assert service.find_agent("boastful")["declared_success"] == 0.95
    entry = next(e for e in service.notary.entries(None) if e["kind"] == "register"
                 and e["payload"]["name"] == "boastful")
    assert entry["payload"]["declared_success"] == 0.95
    task = corpus.make_task(random.Random(3), Band.EASY).to_dict()
    picked = service.request_match(*buyer, task, strategy="self_report")["candidate"]["name"]
    assert picked == "cheap-boast"                          # exact tie on the claim goes to the cheaper
    with pytest.raises(ReferralError, match="declared_success"):
        service.register_agent("liar", "worker", "o", "m", price=1.0, declared_success=1.5)


def test_priors_are_neutral_unless_the_operator_sets_them(service):
    a = service.register_agent("fictional", "worker", "o1", "corvid-1", price=1.0)
    b = service.register_agent("real", "worker", "o2", "claude-sonnet-5-5", price=1.0)
    assert service.profile(a["agent_id"]).benchmark == service.profile(b["agent_id"]).benchmark
    service.model_priors = {"corvid-1": 0.85}
    assert service.profile(a["agent_id"]).benchmark == 0.85


def test_older_databases_gain_new_columns_on_open(tmp_path):
    import sqlite3
    path = tmp_path / "old.sqlite"
    old = sqlite3.connect(path)
    old.execute("CREATE TABLE agents (agent_id TEXT PRIMARY KEY, name TEXT UNIQUE, role TEXT, owner TEXT, "
                "model TEXT, key TEXT, domains TEXT, price REAL, typical_seconds REAL, created_at REAL)")
    old.commit()
    old.close()
    s = ReferralService(str(path), SimClock())
    cols = {r["name"] for r in s.store.db.execute("PRAGMA table_info(agents)")}
    assert "declared_success" in cols
