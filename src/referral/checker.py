"""The Checker: deterministic verification of a delivery against the permitted corpus.

Public checks apply to every fact: the cited document is permitted and is about that
competitor, the quote appears in it verbatim, and the value appears in the quote.
One slot per job is a hidden canary whose answer Referral already knows; it also has
to match that answer, which catches well-cited but stale facts. Workers cannot tell
which slot is the canary.
"""

from __future__ import annotations

from .corpus import Corpus, norm
from .models import Fact, FactVerdict, Slot, TaskSpec


def check_fact(fact: Fact | None, slot: Slot, index: int, corpus: Corpus,
               permitted: set[str], is_canary: bool) -> FactVerdict:
    def fail(reason: str) -> FactVerdict:
        return FactVerdict(index, False, reason, is_canary)

    if fact is None:
        return fail("missing")
    doc = corpus.docs.get(fact.doc_id)
    if doc is None or fact.doc_id not in permitted:
        return fail("cited document is not in the permitted corpus")
    if doc.subject != slot.competitor:
        return fail(f"cited document is about {doc.subject}, not {slot.competitor}")
    if norm(fact.quote) not in norm(doc.text):
        return fail("quote does not appear in the cited document")
    if not fact.value or norm(fact.value) not in norm(fact.quote):
        return fail("value is not supported by the quoted passage")
    if is_canary and norm(fact.value) != norm(corpus.truth[slot]):
        return fail("value is not current as of the corpus date")
    return FactVerdict(index, True, "verified", is_canary)


def check_delivery(spec: TaskSpec, canary: int | None, facts: list[Fact],
                   corpus: Corpus) -> list[FactVerdict]:
    by_slot = {}
    for f in facts:
        by_slot.setdefault(Slot(f.competitor, f.attribute), f)
    permitted = corpus.permitted(spec)
    return [check_fact(by_slot.get(slot), slot, i, corpus, permitted, i == canary)
            for i, slot in enumerate(spec.slots)]


def attribute_failures(worker_id: str, spec: TaskSpec, facts: list[Fact],
                       verdicts: list[FactVerdict], sub_jobs: dict[str, dict]) -> list[str]:
    """Return the agents whose output caused the failed facts.

    A failed fact that came through a subcontract is traced to the subcontractor when
    the subcontract's own check also failed that slot; if the subcontractor's fact
    passed and the parent changed it, the parent is to blame.
    """
    by_slot = {Slot(f.competitor, f.attribute): f for f in facts}
    culprits: list[str] = []
    for v in verdicts:
        if v.passed:
            continue
        slot = spec.slots[v.slot]
        fact = by_slot.get(slot)
        culprit = worker_id
        sub = _covering_sub(slot, fact, sub_jobs)
        if sub is not None:
            sub_slots = [Slot(**s) for s in sub["spec"]["slots"]]
            sub_verdicts = {sv["slot"]: sv for sv in (sub["verdict"] or {}).get("facts", [])}
            sv = sub_verdicts.get(sub_slots.index(slot))
            if sub["status"] == "timeout" or (sv is not None and not sv["passed"]):
                culprit = sub["worker_id"]
            # Otherwise the subcontractor's fact passed, so the parent dropped or changed it.
        if culprit not in culprits:
            culprits.append(culprit)
    return culprits


def _covering_sub(slot: Slot, fact: Fact | None, sub_jobs: dict[str, dict]) -> dict | None:
    if fact is not None and fact.via_job:
        sub = sub_jobs.get(fact.via_job)
        return sub if sub and slot in [Slot(**s) for s in sub["spec"]["slots"]] else None
    if fact is None:
        for sub in sub_jobs.values():
            if slot in [Slot(**s) for s in sub["spec"]["slots"]]:
                return sub
    return None
