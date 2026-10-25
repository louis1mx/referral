"""LLMWorker and live-eval with a fake Anthropic client: no network, no API credit."""
import json
import re
from types import SimpleNamespace

import pytest

from referral import live_eval
from referral.models import Slot, Status
from referral.workers import LLMWorker

SLOT_LINE = re.compile(r"^\d+\. (.+) \| (\w+)$", re.M)


class FakeMessages:
    def __init__(self, corpus, p=0.7, mode="good"):
        self.corpus, self.p, self.mode, self.requests = corpus, p, mode, []

    def _facts(self, prompt):
        facts = []
        for competitor, attribute in SLOT_LINE.findall(prompt):
            slot = Slot(competitor, attribute)
            doc = self.corpus.source_doc(slot)
            value = self.corpus.truth[slot]
            quote = self.corpus.sentence_with(doc, value)
            if self.mode == "invented":
                quote = f"{competitor} says {value}."
            facts.append({"competitor": competitor, "attribute": attribute, "value": value,
                          "doc_id": doc.doc_id, "quote": quote})
        return {"facts": facts}

    def create(self, **kw):
        self.requests.append(kw)
        if self.mode == "refuse":
            return SimpleNamespace(stop_reason="refusal", content=[], usage=self._usage())
        schema = kw["output_config"]["format"]["schema"]
        if "p_success" in schema["properties"]:
            payload = {"p_success": self.p, "finish_seconds": 30}
        else:
            payload = self._facts(kw["messages"][0]["content"])
        content = [SimpleNamespace(type="thinking", thinking=""),
                   SimpleNamespace(type="text", text=json.dumps(payload))]
        return SimpleNamespace(stop_reason="end_turn", content=content, usage=self._usage())

    @staticmethod
    def _usage():
        return SimpleNamespace(input_tokens=1000, output_tokens=200, cache_read_input_tokens=0,
                               cache_creation_input_tokens=0)


def fake_client(corpus, **kw):
    return SimpleNamespace(messages=FakeMessages(corpus, **kw))


def test_llm_worker_locks_forecast_then_delivers(service, buyer, corpus, easy_task):
    client = fake_client(corpus, p=0.7)
    w = LLMWorker("haiku", corpus, client=client)
    w.register(service)
    job = service.direct_hire(*buyer, w.agent_id, easy_task)
    rec = service.get_record(*buyer, job["job_id"])
    assert rec["status"] == Status.PASSED
    assert rec["locked_forecast"]["p_success"] == 0.7
    kinds = [e["kind"] for e in service.notary.entries(job["job_id"])]
    assert kinds == ["contract", "prediction", "delivery", "verdict"]
    assert [c.stage for c in w.calls] == ["forecast", "delivery"]

    req = client.messages.requests[0]
    assert req["model"] == "claude-haiku-5-5"
    assert "temperature" not in req and "thinking" not in req
    assert req["output_config"]["effort"] == "medium"
    assert req["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert "borealis-automation-update-2026" in req["system"][0]["text"]


def test_invented_quotes_fail_the_checker(service, buyer, corpus, easy_task):
    w = LLMWorker("sonnet", corpus, client=fake_client(corpus, mode="invented"))
    w.register(service)
    rec = service.get_record(*buyer, service.direct_hire(*buyer, w.agent_id, easy_task)["job_id"])
    assert rec["status"] == Status.FAILED
    assert all(f["check"].startswith("fail") for f in rec["facts"])


def test_refusal_before_forecast_is_an_error_not_a_forecast(service, buyer, corpus, easy_task):
    w = LLMWorker("opus", corpus, client=fake_client(corpus, mode="refuse"))
    w.register(service)
    job_id = service.direct_hire(*buyer, w.agent_id, easy_task)["job_id"]
    assert "refusal" in w.errors[job_id]
    assert service._job(job_id)["prediction"] is None
    service.clock.advance(easy_task["deadline_s"] + 1)
    assert service.get_record(*buyer, job_id)["status"] == Status.TIMEOUT


def test_live_eval_report_with_fake_client(corpus, capsys):
    result = live_eval.run_live(6, ["opus", "haiku"], client=fake_client(corpus, p=0.9))
    assert len(result["rows"]) == 12
    s = result["summary"]["claude-opus-5-5"]
    assert s["all"]["pass_rate"] == 1.0 and s["all"]["bias"] == pytest.approx(-0.1)
    assert {"easy", "medium", "hard"} <= set(s)
    live_eval.print_report(result)
    assert "Not simulated" in capsys.readouterr().out


def test_live_eval_needs_confirmation(monkeypatch, tmp_path):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-used")
    called = []
    monkeypatch.setattr(live_eval, "run_live", lambda *a, **k: called.append(1))
    assert live_eval.main(3, ["haiku"], str(tmp_path / "x.json"), yes=False, use_profile=False,
                          effort="medium") == 1
    assert not called
