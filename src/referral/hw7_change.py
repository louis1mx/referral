"""The one change made after the limit test (see results/hw7/change.md)."""

from .hw7 import POOLS

POOL = POOLS["main"]


def options(variant: str) -> dict:
    """`before` runs the Checker's rule layer as it was; `after` accepts a value whose core
    (the number or amount, without a qualifier the worker added) appears in the quote."""
    if variant not in ("before", "after"):
        raise SystemExit("--variant must be before or after")
    return {"strict_values": variant == "before"}
