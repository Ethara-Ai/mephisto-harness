from __future__ import annotations

import pytest

from sforge.author.errors import TierMismatchError
from sforge.author.tier import classify_tier, enforce_tier


@pytest.mark.parametrize(
    "loc, tests, expected",
    [
        (100, 50, "toy"),
        (1000, 200, "standard"),
        (5000, 1000, "extreme"),
    ],
)
def test_classify_tier(loc: int, tests: int, expected: str) -> None:
    assert classify_tier(loc, tests) == expected


def test_enforce_tier_match_is_silent() -> None:
    enforce_tier("toy", "toy")
    enforce_tier("standard", "standard")


def test_enforce_tier_mismatch_raises() -> None:
    with pytest.raises(TierMismatchError):
        enforce_tier("toy", "standard")
    with pytest.raises(TierMismatchError):
        enforce_tier("extreme", "standard")
