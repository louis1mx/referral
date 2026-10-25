"""A small, dated corpus with known answers, for one domain: sourced competitor research.

Everything here is fictional. Each competitor of Acme Robotics has a 2024 profile and a
2026 update. Funding and headcount changed between the two, so a worker that cites the
old profile gives a well-cited but stale answer. Three competitors also share a name
prefix with an unrelated firm, which makes their slots harder.
"""

from __future__ import annotations

import random
import re
from dataclasses import dataclass

from .models import Band, ReferralError, Slot, TaskSpec

TARGET_COMPANY = "Acme Robotics"
AS_OF = "2026-09-30"

STATIC_ATTRS = ("hq_city", "founded_year", "flagship_product")
DYNAMIC_ATTRS = ("latest_funding", "headcount")
ATTRIBUTES = STATIC_ATTRS + DYNAMIC_ATTRS


@dataclass(frozen=True)
class Doc:
    doc_id: str
    subject: str
    date: str
    text: str


# name, hq, founded, product, (old funding, old headcount), (new funding, new headcount),
# and an optional look-alike firm: (name, city, funding, headcount).
_COMPETITORS = [
    ("Borealis Automation", "Oslo", "2015", "Tern", ("$18M", "120"), ("$62M", "340"),
     ("Borealis Analytics", "Bergen", "$9M", "45")),
    ("Cobalt Dynamics", "Pittsburgh", "2012", "Forge", ("$40M", "260"), ("$110M", "610"), None),
    ("Dunmore Robotics", "Leeds", "2018", "Wren", ("$7M", "55"), ("$31M", "190"),
     ("Dunmore Robotic Toys", "York", "$3M", "22")),
    ("Everline Systems", "Austin", "2016", "Atlas Picker", ("$25M", "150"), ("$48M", "290"), None),
    ("Fathom Mechatronics", "Rotterdam", "2014", "Keel", ("$12M", "95"), ("$27M", "175"), None),
    ("Gantry Labs", "Shenzhen", "2019", "Span", ("$15M", "80"), ("$75M", "420"),
     ("Gantry Lab Supply", "Dongguan", "$4M", "30")),
    ("Halcyon Motion", "Montreal", "2017", "Drift", ("$20M", "130"), ("$36M", "210"), None),
    ("Ironbark AI", "Melbourne", "2020", "Canopy", ("$6M", "40"), ("$22M", "115"), None),
]


def norm(s: str) -> str:
    return re.sub(r"[\s,]+", " ", s.lower()).strip()


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


class Corpus:
    def __init__(self, docs: list[Doc], truth: dict[Slot, str], stale: dict[Slot, str],
                 lookalikes: dict[str, str]):
        self.docs = {d.doc_id: d for d in docs}
        self.truth = truth
        self.stale = stale
        self.lookalikes = lookalikes  # competitor -> look-alike firm's doc_id
        self.competitors = sorted({s.competitor for s in truth})

    @classmethod
    def default(cls) -> Corpus:
        docs, truth, stale, lookalikes = [], {}, {}, {}
        for name, hq, founded, product, old, new, twin in _COMPETITORS:
            s = slug(name)
            docs.append(Doc(
                f"{s}-profile-2024", name, "2024-02-15",
                f"{name} was founded in {founded} and is headquartered in {hq}. "
                f"Its flagship product is the {product} warehouse robot. "
                f"The company most recently raised a {old[0]} round. "
                f"{name} employs {old[1]} people.",
            ))
            docs.append(Doc(
                f"{s}-update-2026", name, "2026-06-10",
                f"{name} announced a {new[0]} funding round in May 2026. "
                f"After the round, {name} has {new[1]} employees.",
            ))
            truth.update({
                Slot(name, "hq_city"): hq,
                Slot(name, "founded_year"): founded,
                Slot(name, "flagship_product"): product,
                Slot(name, "latest_funding"): new[0],
                Slot(name, "headcount"): new[1],
            })
            stale.update({Slot(name, "latest_funding"): old[0], Slot(name, "headcount"): old[1]})
            if twin:
                tname, tcity, tfund, thead = twin
                tid = f"{slug(tname)}-news-2026"
                docs.append(Doc(
                    tid, tname, "2026-04-02",
                    f"{tname}, based in {tcity} and unrelated to {name}, "
                    f"announced a {tfund} round. {tname} has {thead} employees.",
                ))
                lookalikes[name] = tid
        return cls(docs, truth, stale, lookalikes)

    # --- lookups -------------------------------------------------------------------

    def source_doc(self, slot: Slot) -> Doc:
        kind = "update-2026" if slot.attribute in DYNAMIC_ATTRS else "profile-2024"
        return self.docs[f"{slug(slot.competitor)}-{kind}"]

    def stale_doc(self, slot: Slot) -> Doc | None:
        if slot not in self.stale:
            return None
        return self.docs[f"{slug(slot.competitor)}-profile-2024"]

    def sentence_with(self, doc: Doc, value: str) -> str:
        for sentence in re.split(r"(?<=\.)\s+", doc.text):
            if norm(value) in norm(sentence):
                return sentence
        raise KeyError(f"{value!r} not in {doc.doc_id}")

    def validate(self, spec: TaskSpec) -> None:
        if not spec.slots:
            raise ReferralError("task has no slots")
        for s in spec.slots:
            if s.competitor not in self.competitors:
                raise ReferralError(f"unknown competitor {s.competitor!r}")
            if s.attribute not in ATTRIBUTES:
                raise ReferralError(f"unknown attribute {s.attribute!r}; use one of {ATTRIBUTES}")
        if len(set(spec.slots)) != len(spec.slots):
            raise ReferralError("duplicate slots in task")
        for doc_id in spec.corpus_ids or []:
            if doc_id not in self.docs:
                raise ReferralError(f"unknown document {doc_id!r}")

    def permitted(self, spec: TaskSpec) -> set[str]:
        return set(spec.corpus_ids) if spec.corpus_ids else set(self.docs)

    # --- difficulty ----------------------------------------------------------------

    def slot_difficulty(self, slot: Slot) -> int:
        """0: stated once. 1: an older document disagrees. 2: also a look-alike firm."""
        if slot.attribute not in DYNAMIC_ATTRS:
            return 0
        return 2 if slot.competitor in self.lookalikes else 1

    def difficulty(self, slots: list[Slot]) -> Band:
        scores = [self.slot_difficulty(s) for s in slots]
        if sum(1 for x in scores if x == 2) >= 2:
            return Band.HARD
        if any(scores):
            return Band.MEDIUM
        return Band.EASY

    # --- task generation -----------------------------------------------------------

    def make_task(self, rng: random.Random, band: Band, n: int = 5, budget: float = 2.0,
                  deadline_s: float = 120.0) -> TaskSpec:
        static = [Slot(c, a) for c in self.competitors for a in STATIC_ATTRS]
        plain_dynamic = [Slot(c, a) for c in self.competitors if c not in self.lookalikes
                         for a in DYNAMIC_ATTRS]
        twin_dynamic = [Slot(c, a) for c in self.lookalikes for a in DYNAMIC_ATTRS]
        if band == Band.EASY:
            slots = rng.sample(static, n)
        elif band == Band.MEDIUM:
            k = rng.randint(2, 3)
            slots = rng.sample(plain_dynamic, k) + rng.sample(static, n - k)
        else:
            k = rng.randint(2, 3)
            slots = rng.sample(twin_dynamic, k) + rng.sample(plain_dynamic, 1)
            slots += rng.sample(static, n - len(slots))
        rng.shuffle(slots)
        spec = TaskSpec(TARGET_COMPANY, slots, budget, deadline_s)
        assert self.difficulty(spec.slots) == band
        return spec

    def describe(self) -> dict:
        return {
            "company": TARGET_COMPANY,
            "as_of": AS_OF,
            "competitors": self.competitors,
            "attributes": list(ATTRIBUTES),
            "documents": [{"doc_id": d.doc_id, "subject": d.subject, "date": d.date}
                          for d in self.docs.values()],
        }
