"""The MVP pieces that do not need Claude: waiting on a record over MCP, and the audit."""

import asyncio
import json

from mcp import Client

from referral.audit import BUYER_NAME, REQUESTED, run_audit
from referral.mcp_server import create_server
from referral.models import LiveClock
from referral.service import ReferralService
from referral.sim import build_world, run_trials

from test_mcp import payload

TASK = {"company": "Acme Robotics", "budget": 2.0, "deadline_s": 300,
        "slots": [{"competitor": c, "attribute": a} for c, a in REQUESTED]}


def test_get_record_waits_for_an_external_worker(corpus, correct_facts):
    service = ReferralService(":memory:", LiveClock(), corpus)
    server = create_server(service)
    buyer = service.register_agent("b", "buyer", "owner-b", "m")
    worker = service.register_agent("w", "worker", "owner-w", "m", price=1.0, typical_seconds=60)
    job_id = service.direct_hire(buyer["agent_id"], buyer["key"], worker["agent_id"], TASK)["job_id"]

    async def deliver_later():
        await asyncio.sleep(1.5)
        service.submit_prediction(worker["agent_id"], worker["key"], job_id, 0.7, 1.0, 60)
        service.submit_delivery(worker["agent_id"], worker["key"], job_id, correct_facts(TASK), 1.0)

    async def flow():
        async with Client(server) as client:
            auth = {"agent_id": buyer["agent_id"], "key": buyer["key"], "job_id": job_id}
            now = payload(await client.call_tool("get_record", auth))
            assert now["recommendation"] == "wait"
            _, rec = await asyncio.gather(deliver_later(), client.call_tool("get_record", {**auth, "wait_seconds": 10}))
            assert payload(rec)["recommendation"] == "accept"

    asyncio.run(flow())


def test_audit_checks_ledger_checker_and_answer(tmp_path):
    world = build_world(4, db_path=str(tmp_path / "referral.sqlite"), live=True)
    run_trials(world)
    s = world.service
    me = s.register_agent(BUYER_NAME, "buyer", "owner-acme", "m")
    match = s.request_match(me["agent_id"], me["key"], TASK, exclude=("nia-newcomer",))
    job = s.hire(me["agent_id"], me["key"], match["match_id"])
    rec = s.get_record(me["agent_id"], me["key"], job["job_id"])
    answer = {"facts": [{**f, "job_id": job["job_id"]} for f in rec["facts"]]}
    (tmp_path / "answer.json").write_text(json.dumps(answer))

    report = run_audit(tmp_path, say=lambda _: None)
    assert report["ledger"]["ok"] and report["checker_false_passes"] == 0
    [j] = report["jobs"]
    assert j["forecast_locked_first"] and j["commitment_ok"]
    assert report["answer_ok"] == (rec["status"] == "passed")

    answer["facts"][0]["value"] = "$999M"            # a brief that misreports one fact fails
    (tmp_path / "answer.json").write_text(json.dumps(answer))
    assert not run_audit(tmp_path, say=lambda _: None)["answer_ok"]
