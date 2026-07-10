from __future__ import annotations

from typing import Literal

from sforge.author.errors import TierMismatchError


Tier = Literal["toy", "standard", "extreme"]


def classify_tier(loc_gutted: int, tests_covered: int) -> Tier:
    if loc_gutted < 200 and tests_covered < 100:
        return "toy"
    if loc_gutted < 2000 and tests_covered < 500:
        return "standard"
    return "extreme"


def enforce_tier(expected: str, observed: str) -> None:
    if expected != observed:
        raise TierMismatchError(
            f"tier mismatch: expected {expected!r}, observed {observed!r}"
        )
