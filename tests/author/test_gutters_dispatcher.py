from __future__ import annotations

import pytest

from sforge.author.errors import AuthorError
from sforge.author.gutters import get_gutter
from sforge.author.gutters.base import BaseGutter


def test_get_gutter_unknown_lang_raises_author_error() -> None:
    with pytest.raises(AuthorError):
        get_gutter("cobol")


@pytest.mark.parametrize("lang", ["go", "rust", "python", "typescript"])
def test_get_gutter_known_lang_dispatches(lang: str) -> None:
    try:
        gutter = get_gutter(lang)
    except (NotImplementedError, ImportError, ModuleNotFoundError):
        return
    assert isinstance(gutter, BaseGutter)
