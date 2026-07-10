from __future__ import annotations

import pytest

from sforge.author.gutters import get_gutter
from sforge.author.gutters.base import GutSpec
from sforge.author.gutters.rust import RustGutter
from sforge.author.gutters.typescript import TypeScriptGutter


STUB_CLASSES = [
    ("rust", RustGutter),
    ("typescript", TypeScriptGutter),
]


@pytest.mark.parametrize("lang,cls", STUB_CLASSES)
def test_dispatcher_returns_stub_instance(lang: str, cls: type) -> None:
    gutter = get_gutter(lang)
    assert isinstance(gutter, cls)


@pytest.mark.parametrize("lang,cls", STUB_CLASSES)
def test_stub_parse_functions_raises_not_implemented(lang: str, cls: type) -> None:
    gutter = get_gutter(lang)
    with pytest.raises(NotImplementedError):
        gutter.parse_functions("some source")


@pytest.mark.parametrize("lang,cls", STUB_CLASSES)
def test_stub_gut_raises_not_implemented(lang: str, cls: type) -> None:
    gutter = get_gutter(lang)
    with pytest.raises(NotImplementedError):
        gutter.gut("some source", GutSpec(rel_path="x", funcs=["y"]))
