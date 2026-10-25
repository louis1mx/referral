import random

import pytest

from referral.corpus import Corpus
from referral.models import Band, SimClock, Slot
from referral.service import ReferralService


@pytest.fixture
def corpus():
    return Corpus.default()


@pytest.fixture
def service(corpus):
    return ReferralService(":memory:", SimClock(), corpus, seed=1)


@pytest.fixture
def buyer(service):
    creds = service.register_agent("test-buyer", "buyer", "owner-buyer", "buyer-llm")
    return creds["agent_id"], creds["key"]


@pytest.fixture
def worker(service):
    creds = service.register_agent("test-worker", "worker", "owner-worker", "atlas-large-2",
                                   price=1.0, typical_seconds=60)
    return creds["agent_id"], creds["key"]


@pytest.fixture
def easy_task(corpus):
    return corpus.make_task(random.Random(0), Band.EASY).to_dict()


@pytest.fixture
def correct_facts(corpus):
    """Function that returns a fully correct delivery for a task dict."""
    def make(task):
        facts = []
        for s in task["slots"]:
            slot = Slot(s["competitor"], s["attribute"])
            doc = corpus.source_doc(slot)
            value = corpus.truth[slot]
            facts.append({"competitor": slot.competitor, "attribute": slot.attribute, "value": value,
                          "doc_id": doc.doc_id, "quote": corpus.sentence_with(doc, value)})
        return facts
    return make
