from __future__ import annotations

import textwrap

import pytest
import tree_sitter_python
from tree_sitter import Language, Parser

from sforge.author.errors import GutError
from sforge.author.gutters import get_gutter
from sforge.author.gutters.base import GutSpec
from sforge.author.gutters.python import PythonGutter


_LANG = Language(tree_sitter_python.language())
_PARSER = Parser(_LANG)


def _gut(src: str, funcs: list[str]) -> str:
    g = PythonGutter()
    return g.gut(src, GutSpec(rel_path="x.py", funcs=funcs)).gutted_source


def _parses_clean(src: str) -> bool:
    tree = _PARSER.parse(src.encode("utf-8"))
    return not tree.root_node.has_error


def test_gutter_dispatcher_returns_PythonGutter() -> None:
    g = get_gutter("python")
    assert isinstance(g, PythonGutter)


def test_gut_single_function() -> None:
    src = textwrap.dedent("""\
        def foo():
            return 1
    """)
    out = _gut(src, ["foo"])
    assert "return 1" not in out
    assert 'raise NotImplementedError("foo: not implemented")' in out
    assert "def foo():" in out
    assert _parses_clean(out)


def test_gut_multiple_functions_same_file() -> None:
    src = textwrap.dedent("""\
        def a():
            return 111

        def b():
            return 222

        def c():
            return 333
    """)
    out = _gut(src, ["a", "c"])
    assert "return 111" not in out
    assert "return 222" in out
    assert "return 333" not in out
    assert 'raise NotImplementedError("a: not implemented")' in out
    assert 'raise NotImplementedError("c: not implemented")' in out
    assert _parses_clean(out)


def test_gut_method_in_class() -> None:
    src = textwrap.dedent("""\
        class Foo:
            def double(self, x):
                return x * 2
    """)
    out = _gut(src, ["double"])
    assert "return x * 2" not in out
    assert 'raise NotImplementedError("double: not implemented")' in out
    assert "class Foo:" in out
    assert "def double(self, x):" in out
    assert _parses_clean(out)


def test_gut_async_function() -> None:
    src = textwrap.dedent("""\
        async def fetch(url):
            return await get(url)
    """)
    out = _gut(src, ["fetch"])
    assert "await get(url)" not in out
    assert 'raise NotImplementedError("fetch: not implemented")' in out
    assert "async def fetch(url):" in out
    assert _parses_clean(out)


def test_gut_same_named_methods_across_classes() -> None:
    src = textwrap.dedent("""\
        class A:
            def m(self):
                return "A"

        class B:
            def m(self):
                return "B"
    """)
    out = _gut(src, ["m"])
    assert 'return "A"' not in out
    assert 'return "B"' not in out
    assert out.count('raise NotImplementedError("m: not implemented")') == 2
    assert _parses_clean(out)


def test_gut_preserves_other_content() -> None:
    src = textwrap.dedent('''\
        import os
        import sys

        CONSTANT = 42

        def keep_me():
            """This docstring stays."""
            return CONSTANT

        def gut_me():
            return 999
    ''')
    out = _gut(src, ["gut_me"])
    assert "import os" in out
    assert "import sys" in out
    assert "CONSTANT = 42" in out
    assert '"""This docstring stays."""' in out
    assert "def keep_me():" in out
    assert "return CONSTANT" in out
    assert "return 999" not in out
    assert _parses_clean(out)


def test_gut_preserves_type_annotations() -> None:
    src = textwrap.dedent("""\
        def foo(x: int, y: str = "z") -> bool:
            return True
    """)
    out = _gut(src, ["foo"])
    assert 'def foo(x: int, y: str = "z") -> bool:' in out
    assert "return True" not in out
    assert 'raise NotImplementedError("foo: not implemented")' in out
    assert _parses_clean(out)


def test_gut_preserves_decorators() -> None:
    src = textwrap.dedent("""\
        class C:
            @staticmethod
            def foo():
                return 1

            @classmethod
            def bar(cls):
                return 2
    """)
    out = _gut(src, ["foo"])
    assert "@staticmethod" in out
    assert "@classmethod" in out
    assert "def foo():" in out
    assert "return 1" not in out
    assert "return 2" in out
    assert _parses_clean(out)


def test_gut_deeply_indented_method() -> None:
    src = textwrap.dedent("""\
        class Outer:
            class Inner:
                def deep(self):
                    return 42
    """)
    out = _gut(src, ["deep"])
    assert "return 42" not in out
    assert 'raise NotImplementedError("deep: not implemented")' in out
    assert "class Outer:" in out
    assert "class Inner:" in out
    assert _parses_clean(out)


def test_gut_multiline_signature() -> None:
    src = textwrap.dedent("""\
        def foo(
            x: int,
            y: str,
        ) -> bool:
            return True
    """)
    out = _gut(src, ["foo"])
    assert "def foo(\n    x: int,\n    y: str,\n) -> bool:" in out
    assert "return True" not in out
    assert 'raise NotImplementedError("foo: not implemented")' in out
    assert _parses_clean(out)


def test_gut_function_with_docstring_replaces_body() -> None:
    src = textwrap.dedent('''\
        def foo():
            """This function's docstring gets gutted."""
            return 1
    ''')
    out = _gut(src, ["foo"])
    assert "This function's docstring gets gutted." not in out
    assert "return 1" not in out
    assert 'raise NotImplementedError("foo: not implemented")' in out
    assert _parses_clean(out)


def test_gut_missing_function_raises_GutError() -> None:
    src = "def foo():\n    return 1\n"
    g = PythonGutter()
    with pytest.raises(GutError):
        g.gut(src, GutSpec(rel_path="x.py", funcs=["nonexistent"]))


def test_gut_reverse_offset_edits_correct() -> None:
    src = textwrap.dedent("""\
        def a():
            return 111

        def b():
            return 222

        def c():
            return 333
    """)
    out = _gut(src, ["a", "b", "c"])
    assert "return 111" not in out
    assert "return 222" not in out
    assert "return 333" not in out
    assert out.count('raise NotImplementedError(') == 3
    assert 'raise NotImplementedError("a: not implemented")' in out
    assert 'raise NotImplementedError("b: not implemented")' in out
    assert 'raise NotImplementedError("c: not implemented")' in out
    assert _parses_clean(out)


def test_gut_reparses_cleanly() -> None:
    src = textwrap.dedent("""\
        def outer():
            def inner():
                return 1
            return inner()
    """)
    out = _gut(src, ["outer"])
    tree = _PARSER.parse(out.encode("utf-8"))
    assert not tree.root_node.has_error


def test_gut_result_total_loc() -> None:
    src = textwrap.dedent("""\
        def a():
            x = 1
            y = 2
            return x + y

        def b():
            return 1
    """)
    g = PythonGutter()
    result = g.gut(src, GutSpec(rel_path="x.py", funcs=["a", "b"]))
    assert result.total_loc_gutted == sum(f.body_loc for f in result.functions)
    assert result.total_loc_gutted >= 4


def test_parse_functions_finds_all_definitions() -> None:
    src = textwrap.dedent("""\
        def top():
            return 1

        class C:
            def m(self):
                return 2

        async def a():
            return 3
    """)
    g = PythonGutter()
    fns = g.parse_functions(src)
    names = sorted(f.name for f in fns)
    assert names == ["a", "m", "top"]


def test_gut_preserves_multiline_body_indent() -> None:
    src = textwrap.dedent("""\
        class Foo:
            def bar(self):
                x = 1
                y = 2
                return x + y
    """)
    out = _gut(src, ["bar"])
    assert 'raise NotImplementedError("bar: not implemented")' in out
    assert _parses_clean(out)
    lines = out.splitlines()
    stub_line = next(l for l in lines if "NotImplementedError" in l)
    assert stub_line.startswith("        ")


def test_gut_aborts_when_result_has_error_nodes(monkeypatch: pytest.MonkeyPatch) -> None:
    src = textwrap.dedent("""\
        def foo():
            return 1
    """)

    def broken_stub(self, fn):
        return "this is @@ not valid python"

    monkeypatch.setattr(PythonGutter, "stub_body", broken_stub)
    g = PythonGutter()
    with pytest.raises(GutError):
        g.gut(src, GutSpec(rel_path="x.py", funcs=["foo"]))
