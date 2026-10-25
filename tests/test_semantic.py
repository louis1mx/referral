"""The semantic layer of the Checker, with stand-in judges (the real one needs the claude CLI)."""

import json

import pytest

from referral.checker import check_delivery, review_semantics
from referral.models import Fact, Slot, Status, TaskSpec
from referral.semantic import Claim, ClaudeJudge, JudgeError, Judgment, judge_prompt, parse_judgments

IRONBARK_FUNDING = Slot("Ironbark AI", "latest_funding")
IRONBARK_HQ = Slot("Ironbark AI", "hq_city")


def correct(corpus, slot):
    doc = corpus.source_doc(slot)
    value = corpus.truth[slot]
    return Fact(slot.competitor, slot.attribute, value, doc.doc_id, corpus.sentence_with(doc, value))


def headcount_as_funding(corpus):
    """Passes every rule: the quote is real, about Ironbark, and contains the value."""
    doc = corpus.docs["ironbark-ai-profile-2024"]
    return Fact("Ironbark AI", "latest_funding", "40", doc.doc_id, corpus.sentence_with(doc, "40 people"))


class ScriptedJudge:
    """Rejects the claims whose index is listed; records what it was asked."""

    model = "scripted"

    def __init__(self, reject=(), error=None):
        self.reject, self.error, self.seen = set(reject), error, []

    def judge(self, claims, corpus):
        self.seen.append(claims)
        if self.error:
            raise JudgeError(self.error)
        return [Judgment(c.index, c.index not in self.reject, True, "scripted") for c in claims]


def test_rules_alone_pass_a_headcount_passed_off_as_funding(corpus):
    spec = TaskSpec("Acme Robotics", [IRONBARK_FUNDING], 2.0, 120.0)
    [v] = check_delivery(spec, None, [headcount_as_funding(corpus)], corpus)
    assert v.passed  # the gap the semantic layer exists to close


def test_judge_sees_only_rule_passing_facts_and_can_fail_them(corpus):
    spec = TaskSpec("Acme Robotics", [IRONBARK_FUNDING, IRONBARK_HQ], 2.0, 120.0)
    bad_hq = Fact("Ironbark AI", "hq_city", "Sydney", "ironbark-ai-profile-2024", "made up")
    facts = [headcount_as_funding(corpus), bad_hq]
    judge = ScriptedJudge(reject={0})
    verdicts, summary = review_semantics(check_delivery(spec, None, facts, corpus), spec, facts, corpus, judge)
    [claims] = judge.seen
    assert [c.index for c in claims] == [0]           # the invented quote never reaches the judge
    assert not verdicts[0].passed and verdicts[0].reason.startswith("semantic check:")
    assert verdicts[0].semantic == "fail"
    assert not verdicts[1].passed and verdicts[1].semantic is None
    assert summary == {"model": "scripted", "status": "ok", "judged": 1, "rejected": 1}


def test_unavailable_judge_keeps_rule_verdicts_and_says_so(corpus):
    spec = TaskSpec("Acme Robotics", [IRONBARK_FUNDING], 2.0, 120.0)
    facts = [correct(corpus, IRONBARK_FUNDING)]
    verdicts, summary = review_semantics(check_delivery(spec, None, facts, corpus), spec, facts, corpus,
                                         ScriptedJudge(error="cli missing"))
    assert verdicts[0].passed and verdicts[0].semantic == "unavailable"
    assert summary["status"] == "unavailable" and "cli missing" in summary["error"]


def test_prompt_holds_corpus_text_but_never_the_answer_key(corpus):
    prompt = judge_prompt([Claim(0, IRONBARK_FUNDING, "40", "ironbark-ai-profile-2024",
                                 "Ironbark AI employs 40 people.")], corpus)
    data = json.loads(prompt[prompt.index("{"):])
    assert {d["company"] for d in data["documents"]} == {"Ironbark AI"}
    assert {d["doc_id"] for d in data["documents"]} == {"ironbark-ai-profile-2024", "ironbark-ai-update-2026"}
    assert "truth" not in prompt and data["corpus_date"] == "2026-09-30"


def test_judgments_must_cover_every_claim_once():
    claims = [Claim(0, IRONBARK_FUNDING, "v", "d", "q"), Claim(3, IRONBARK_HQ, "v", "d", "q")]
    ok = {"judgments": [{"index": 3, "states_attribute": True, "current": True, "reason": "r"},
                        {"index": 0, "states_attribute": False, "current": True, "reason": "r"}]}
    assert [j.index for j in parse_judgments(ok, claims)] == [0, 3]
    with pytest.raises(JudgeError):
        parse_judgments({"judgments": ok["judgments"][:1]}, claims)
    with pytest.raises(JudgeError):
        parse_judgments({"judgments": [{"index": 0}]}, claims)


def test_claude_judge_retries_once_then_gives_up():
    calls = []
    answer = {"judgments": [{"index": 0, "states_attribute": True, "current": False, "reason": "older"}]}

    def flaky(prompt, model, timeout):
        calls.append(model)
        if len(calls) == 1:
            raise JudgeError("transient")
        return answer

    claim = [Claim(0, IRONBARK_FUNDING, "$6M", "ironbark-ai-profile-2024", "q")]
    from referral.corpus import Corpus
    [j] = ClaudeJudge("m", runner=flaky).judge(claim, Corpus.default())
    assert not j.passed and calls == ["m", "m"]

    def broken(prompt, model, timeout):
        raise JudgeError("down")
    with pytest.raises(JudgeError):
        ClaudeJudge("m", runner=broken).judge(claim, Corpus.default())


def test_service_fails_a_job_the_judge_rejects_and_notarizes_it(service, buyer, worker, corpus):
    # The judge rejects everything it sees; the hidden check may catch the bad slot first,
    # so whichever slots pass the rules must still be failed by the judge.
    service.judge = ScriptedJudge(reject={0, 1, 2})
    founded = Slot("Ironbark AI", "founded_year")
    task = {"company": "Acme Robotics", "budget": 2.0, "deadline_s": 300,
            "slots": [{"competitor": s.competitor, "attribute": s.attribute}
                      for s in (IRONBARK_FUNDING, IRONBARK_HQ, founded)]}
    job_id = service.direct_hire(*buyer, worker[0], task)["job_id"]
    service.submit_prediction(*worker, job_id, 0.8, 1.0, 60)
    facts = [headcount_as_funding(corpus).__dict__, correct(corpus, IRONBARK_HQ).__dict__,
             correct(corpus, founded).__dict__]
    assert service.submit_delivery(*worker, job_id, facts, 1.0)["status"] == Status.FAILED
    rec = service.get_record(*buyer, job_id)
    assert sum(f["check"].startswith("fail: semantic check:") for f in rec["facts"]) >= 2
    verdict = next(e for e in service.notary.entries(job_id) if e["kind"] == "verdict")["payload"]
    assert verdict["semantic_check"]["rejected"] >= 2
    assert service.verify_ledger()["ok"]


def test_check_eval_suite_passes_the_rules_and_is_half_wrong(corpus):
    from referral.check_eval import build_cases
    cases = build_cases(corpus)
    assert len(cases) == 80 and sum(not c["correct"] for c in cases) == 40
    from referral.checker import check_fact
    assert all(check_fact(c["fact"], c["slot"], 0, corpus, set(corpus.docs), False).passed for c in cases)
