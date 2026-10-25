import asyncio
import json
import random

from mcp import Client

from referral.mcp_server import create_server
from referral.models import Band
from referral.sim import build_world, run_trials


def payload(result):
    if result.structured_content is not None:
        data = result.structured_content
        return data.get("result", data) if set(data) == {"result"} else data
    return json.loads(result.content[0].text)


def test_buyer_flow_over_mcp():
    world = build_world(seed=5)
    run_trials(world)
    server = create_server(world.service)
    task = world.service.corpus.make_task(random.Random(9), Band.MEDIUM)
    slots = [{"competitor": s.competitor, "attribute": s.attribute} for s in task.slots]

    async def flow():
        async with Client(server) as client:
            names = {t.name for t in (await client.list_tools()).tools}
            assert {"request_match", "hire", "submit_prediction", "submit_delivery", "get_record"} <= names
            me = payload(await client.call_tool("register_agent", {
                "name": "claude-buyer", "role": "buyer", "owner": "ids865", "model": "claude-opus-5-5"}))
            auth = {"agent_id": me["agent_id"], "key": me["key"]}
            match = payload(await client.call_tool("request_match", {
                **auth, "company": "Acme Robotics", "slots": slots}))
            assert match["action"] in ("hire", "bounded_trial")
            assert "score" not in json.dumps(match["candidate"])
            job = payload(await client.call_tool("hire", {**auth, "match_id": match["match_id"]}))
            rec = payload(await client.call_tool("get_record", {**auth, "job_id": job["job_id"]}))
            assert rec["status"] in ("passed", "failed", "timeout")
            assert rec["recommendation"] in ("accept", "reject_and_rematch")
            cred = payload(await client.call_tool("get_credential", {"worker_id": match["candidate"]["agent_id"]}))
            key = payload(await client.call_tool("get_issuer_key", {}))
            assert key["alg"] == "Ed25519" and cred["proof"]["verificationMethod"] == key["jwk"]["kid"]
            check = payload(await client.call_tool("verify_credential", {"credential": cred}))
            assert check == {"valid": True, "reason": "valid"}
            denied = payload(await client.call_tool("get_record", {
                "agent_id": world.buyer_id, "key": world.buyer_key, "job_id": job["job_id"]}))
            assert "error" in denied

    asyncio.run(flow())
