"""The Checker: verification of a delivery against the permitted corpus, in two layers.

Rule layer, for every fact: the cited document is permitted and is about that competitor,
the quote appears in it verbatim, and the value appears in the quote. One slot per job is
a hidden canary whose answer Referral already knows; it also has to match that answer.
Workers cannot tell which slot is the canary.

Semantic layer (semantic.py), when a judge is configured: a language model reads the facts
that passed the rules and fails any whose quote does not state the requested attribute or
whose value a later document supersedes. Without it, those facts pass unless they happen
to sit in the canary slot.
"""

from __future__ import annotations

import re
from dataclasses import replace

from .corpus import Corpus, norm, same_value
from .models import Fact, FactVerdict, Slot, TaskSpec
from .semantic import Claim, Judge, JudgeError


def core_value(value: str) -> str:
    """The value without a qualifier the worker added: "$36M (May 2026)" and "$48M funding round"
    become "$36M" and "$48M". A number or amount is its first token; other values only lose a
    trailing parenthetical, so "Wren warehouse robot" stays whole."""
    v = re.sub(r"\s*\([^)]*\)\s*$", "", value.strip())
    first = v.split()[0] if v.split() else v
    return first if first[:1] in "$0123456789" else v


def supported(value: str, quote: str, strict: bool = False) -> bool:
    """The value, or under the default rule its core, appears in the quote as whole words."""
    if norm(value) in norm(quote):
        return True
    if strict:
        return False
    core = norm(core_value(value))
    return bool(core) and re.search(rf"(?<![\w.$]){re.escape(core)}(?![\w.])", norm(quote)) is not None


def check_fact(fact: Fact | None, slot: Slot, index: int, corpus: Corpus,
               permitted: set[str], is_canary: bool, strict_values: bool = False) -> FactVerdict:
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
    if not fact.value or not supported(fact.value, fact.quote, strict_values):
        return fail("value is not supported by the quoted passage")
    if is_canary and not same_value(fact.value, corpus.truth[slot]):
        return fail("value is not current as of the corpus date")
    return FactVerdict(index, True, "verified", is_canary)


def check_delivery(spec: TaskSpec, canary: int | None, facts: list[Fact],
                   corpus: Corpus, strict_values: bool = False) -> list[FactVerdict]:
    by_slot = {}
    for f in facts:
        by_slot.setdefault(Slot(f.competitor, f.attribute), f)
    permitted = corpus.permitted(spec)
    return [check_fact(by_slot.get(slot), slot, i, corpus, permitted, i == canary, strict_values)
            for i, slot in enumerate(spec.slots)]


def review_semantics(verdicts: list[FactVerdict], spec: TaskSpec, facts: list[Fact], corpus: Corpus,
                     judge: Judge) -> tuple[list[FactVerdict], dict]:
    """Send the rule-passing facts to the judge and fail the ones it rejects. If the judge is
    unavailable the rule verdicts stand, and the summary records that the layer did not run."""
    by_slot = {}
    for f in facts:
        by_slot.setdefault(Slot(f.competitor, f.attribute), f)
    claims = []
    for v in verdicts:
        if v.passed:
            slot = spec.slots[v.slot]
            f = by_slot[slot]
            claims.append(Claim(v.slot, slot, f.value, f.doc_id, f.quote))
    summary = {"model": judge.model, "status": "ok", "judged": len(claims), "rejected": 0}
    try:
        judgments = {j.index: j for j in judge.judge(claims, corpus)}
    except JudgeError as e:
        summary.update(status="unavailable", error=str(e)[:300])
        judged = {c.index for c in claims}
        return [replace(v, semantic="unavailable") if v.slot in judged else v for v in verdicts], summary
    out = []
    for v in verdicts:
        j = judgments.get(v.slot)
        if j is None:
            out.append(v)
        elif j.passed:
            out.append(replace(v, semantic="pass"))
        else:
            summary["rejected"] += 1
            problem = "quote does not state this attribute" if not j.states_attribute else "a later document supersedes it"
            out.append(replace(v, passed=False, semantic="fail", reason=f"semantic check: {problem} ({j.reason})"))
    return out, summary


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
