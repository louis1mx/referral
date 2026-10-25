"""Shared data types for Referral."""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from enum import StrEnum


class Band(StrEnum):
    EASY = "easy"
    MEDIUM = "medium"
    HARD = "hard"


BANDS = (Band.EASY, Band.MEDIUM, Band.HARD)

# Harder successes count more, so easy jobs cannot pad a record.
BAND_WEIGHT = {Band.EASY: 1.0, Band.MEDIUM: 2.0, Band.HARD: 3.0}

# How much longer a task takes relative to a medium one.
BAND_TIME = {Band.EASY: 0.7, Band.MEDIUM: 1.0, Band.HARD: 1.3}


class Tier(StrEnum):
    TRIAL = "trial"
    VERIFIED = "verified"
    TRUSTED = "trusted"


class Action(StrEnum):
    HIRE = "hire"
    BOUNDED_TRIAL = "bounded_trial"
    NO_MATCH = "no_eligible_match"


class Status(StrEnum):
    DISPATCHED = "dispatched"
    PREDICTED = "predicted"
    PASSED = "passed"
    FAILED = "failed"
    TIMEOUT = "timeout"


SETTLED = (Status.PASSED, Status.FAILED, Status.TIMEOUT)

DEFAULT_DOMAIN = "sourced-research"
DEFAULT_ACCEPTANCE = (
    "Each fact must quote, verbatim, a passage from a permitted corpus document "
    "about that competitor, and the passage must contain the stated value. Values must "
    "be current as of the corpus date; some slots are spot-checked against known answers."
)


class ReferralError(Exception):
    """A request Referral refuses. The message is safe to show the caller."""


@dataclass(frozen=True)
class Slot:
    competitor: str
    attribute: str


@dataclass
class TaskSpec:
    company: str
    slots: list[Slot]
    budget: float
    deadline_s: float
    corpus_ids: list[str] | None = None
    acceptance: str = DEFAULT_ACCEPTANCE
    domain: str = DEFAULT_DOMAIN

    def to_dict(self) -> dict:
        d = asdict(self)
        d["slots"] = [asdict(s) for s in self.slots]
        return d

    @classmethod
    def from_dict(cls, d: dict) -> TaskSpec:
        try:
            slots = [Slot(s["competitor"], s["attribute"]) for s in d["slots"]]
            return cls(
                company=d["company"],
                slots=slots,
                budget=float(d["budget"]),
                deadline_s=float(d["deadline_s"]),
                corpus_ids=d.get("corpus_ids"),
                acceptance=d.get("acceptance") or DEFAULT_ACCEPTANCE,
                domain=d.get("domain") or DEFAULT_DOMAIN,
            )
        except (KeyError, TypeError, ValueError) as e:
            raise ReferralError(f"malformed task: {e}") from e


@dataclass
class Fact:
    competitor: str
    attribute: str
    value: str
    doc_id: str
    quote: str
    via_job: str | None = None

    @classmethod
    def from_dict(cls, d: dict) -> Fact:
        try:
            return cls(
                competitor=d["competitor"],
                attribute=d["attribute"],
                value=str(d["value"]),
                doc_id=d["doc_id"],
                quote=d["quote"],
                via_job=d.get("via_job"),
            )
        except (KeyError, TypeError) as e:
            raise ReferralError(f"malformed fact: {e}") from e


@dataclass
class FactVerdict:
    slot: int
    passed: bool
    reason: str
    canary: bool = field(default=False)
    # The semantic layer's view: "pass", "fail" or "unavailable"; None if it did not judge it.
    semantic: str | None = field(default=None)


class SimClock:
    """Clock for simulations: time only moves when a worker spends it."""

    def __init__(self, start: float = 0.0):
        self._t = start

    def now(self) -> float:
        return self._t

    def advance(self, seconds: float) -> None:
        self._t += max(0.0, seconds)


class LiveClock(SimClock):
    """Wall-clock time plus any simulated work, for the MCP server."""

    def __init__(self):
        super().__init__(0.0)

    def now(self) -> float:
        return time.time() + self._t
