from __future__ import annotations

import pytest

from sforge.author.errors import (
    AuthorError,
    CalibrationError,
    CloneError,
    ContaminationError,
    GutError,
    ManifestError,
    TierMismatchError,
)


@pytest.mark.parametrize(
    "cls, expected_code",
    [
        (ManifestError, 1),
        (CloneError, 2),
        (GutError, 2),
        (ContaminationError, 3),
        (CalibrationError, 4),
        (TierMismatchError, 5),
    ],
)
def test_exit_codes(cls: type[AuthorError], expected_code: int) -> None:
    err = cls("boom")
    assert err.exit_code == expected_code
    assert isinstance(err, AuthorError)
    assert str(err) == "boom"
    assert err.message == "boom"


def test_author_error_base_default_code() -> None:
    err = AuthorError("nope")
    assert err.exit_code == 1
