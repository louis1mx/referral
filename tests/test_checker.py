from referral.checker import attribute_failures, check_delivery, check_fact
from referral.models import Fact, Slot, TaskSpec

BOREALIS_FUNDING = Slot("Borealis Automation", "latest_funding")


def fact_for(corpus, slot, **override):
    doc = corpus.source_doc(slot)
    value = corpus.truth[slot]
    base = dict(competitor=slot.competitor, attribute=slot.attribute, value=value,
                doc_id=doc.doc_id, quote=corpus.sentence_with(doc, value))
    base.update(override)
    return Fact(**base)


def check(corpus, fact, slot=BOREALIS_FUNDING, canary=False):
    return check_fact(fact, slot, 0, corpus, set(corpus.docs), canary)


def test_correct_fact_passes(corpus):
    assert check(corpus, fact_for(corpus, BOREALIS_FUNDING)).passed


def test_invented_quote_fails(corpus):
    v = check(corpus, fact_for(corpus, BOREALIS_FUNDING, quote="Borealis raised $62M."))
    assert not v.passed and "does not appear" in v.reason


def test_value_must_be_in_quote(corpus):
    v = check(corpus, fact_for(corpus, BOREALIS_FUNDING, value="$99M"))
    assert not v.passed and "not supported" in v.reason


def test_lookalike_firm_fails(corpus):
    twin = corpus.docs[corpus.lookalikes["Borealis Automation"]]
    f = fact_for(corpus, BOREALIS_FUNDING, doc_id=twin.doc_id, value="$9M",
                 quote=twin.text.split(". ")[0])
    v = check(corpus, f)
    assert not v.passed and "about Borealis Analytics" in v.reason


def test_stale_citation_only_caught_by_canary(corpus):
    old = corpus.stale_doc(BOREALIS_FUNDING)
    stale = fact_for(corpus, BOREALIS_FUNDING, doc_id=old.doc_id, value="$18M",
                     quote=corpus.sentence_with(old, "$18M"))
    assert check(corpus, stale, canary=False).passed
    v = check(corpus, stale, canary=True)
    assert not v.passed and "not current" in v.reason


def test_unpermitted_document_fails(corpus):
    f = fact_for(corpus, BOREALIS_FUNDING)
    v = check_fact(f, BOREALIS_FUNDING, 0, corpus, {"other-doc"}, False)
    assert not v.passed and "permitted" in v.reason


def test_missing_fact_fails(corpus):
    spec = TaskSpec("Acme Robotics", [BOREALIS_FUNDING], 2.0, 120.0)
    [v] = check_delivery(spec, None, [], corpus)
    assert not v.passed and v.reason == "missing"


def _sub_job(slot, passed, fact):
    return {"job_id": "job-sub", "worker_id": "agt-sub", "status": "passed" if passed else "failed",
            "spec": {"slots": [{"competitor": slot.competitor, "attribute": slot.attribute}]},
            "verdict": {"facts": [{"slot": 0, "passed": passed, "reason": ""}]},
            "delivery": {"facts": [fact]}}


def test_failure_traced_to_subcontractor(corpus):
    spec = TaskSpec("Acme Robotics", [BOREALIS_FUNDING], 2.0, 120.0)
    bad = fact_for(corpus, BOREALIS_FUNDING, quote="made up", via_job="job-sub")
    verdicts = check_delivery(spec, None, [bad], corpus)
    sub = _sub_job(BOREALIS_FUNDING, False, bad.__dict__)
    assert attribute_failures("agt-parent", spec, [bad], verdicts, {"job-sub": sub}) == ["agt-sub"]


def test_parent_blamed_when_it_changes_a_passing_subcontract(corpus):
    spec = TaskSpec("Acme Robotics", [BOREALIS_FUNDING], 2.0, 120.0)
    good = fact_for(corpus, BOREALIS_FUNDING, via_job="job-sub")
    changed = fact_for(corpus, BOREALIS_FUNDING, value="$63M", via_job="job-sub")
    verdicts = check_delivery(spec, None, [changed], corpus)
    sub = _sub_job(BOREALIS_FUNDING, True, good.__dict__)
    assert attribute_failures("agt-parent", spec, [changed], verdicts, {"job-sub": sub}) == ["agt-parent"]


def test_hidden_check_accepts_the_value_as_a_whole_token(corpus):
    from referral.corpus import same_value
    assert same_value("Wren warehouse robot", "Wren") and same_value("$22M", "$22M")
    assert not same_value("180", "80") and not same_value("$122M", "$22M") and not same_value("", "80")
    assert not same_value("$22M funding round in May 2026. After the round, Ironbark AI has 115", "115")
    slot = Slot("Dunmore Robotics", "flagship_product")
    doc = corpus.source_doc(slot)
    f = Fact(slot.competitor, slot.attribute, "Wren warehouse robot", doc.doc_id,
             corpus.sentence_with(doc, "Wren"))
    assert check_fact(f, slot, 0, corpus, set(corpus.docs), True).passed


def test_a_qualified_value_passes_when_its_core_is_in_the_quote():
    from referral.checker import core_value, supported
    quote = "Halcyon Motion announced a $36M funding round in May 2026."
    assert core_value("$36M (May 2026)") == "$36M" and core_value("$48M funding round") == "$48M"
    assert core_value("Wren warehouse robot") == "Wren warehouse robot"
    assert supported("$36M (May 2026)", quote)
    assert not supported("$36M (May 2026)", quote, strict=True)      # the rule before HW7
    assert not supported("$3M", quote)                               # no partial-number match
    assert not supported("$360M round", quote)
    assert not supported("1200", "Gantry Labs employs 120 people.")  # the padder's appended digit
    assert not supported("Tern robot", "Its flagship product is the Wren warehouse robot.")
