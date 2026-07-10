from __future__ import annotations

import pytest

from sforge.author.errors import GutError
from sforge.author.gutters.base import GutSpec
from sforge.author.gutters.go import GoGutter, _has_errors_import


def _gut(src: str, funcs: list[str]) -> str:
    g = GoGutter()
    return g.gut(src, GutSpec(rel_path="x.go", funcs=funcs)).gutted_source


def test_parse_functions_finds_function_and_method() -> None:
    src = """package p

func Foo() {}

func (r *R) Bar() int { return 0 }
"""
    g = GoGutter()
    fns = g.parse_functions(src)
    names = sorted(f.name for f in fns)
    assert names == ["Bar", "Foo"]
    foo = next(f for f in fns if f.name == "Foo")
    bar = next(f for f in fns if f.name == "Bar")
    assert foo.receiver is None
    assert bar.receiver == "r *R"


def test_gut_replaces_plain_function_body() -> None:
    src = """package p

func Add(a, b int) int {
	return a + b
}
"""
    out = _gut(src, ["Add"])
    assert "return a + b" not in out
    assert "TODO(agent)" in out
    assert "return 0" in out
    assert "func Add(a, b int) int" in out


def test_gut_replaces_receiver_method_body() -> None:
    src = """package p

type Foo struct{}

func (f *Foo) Double(x int) int {
	return x * 2
}
"""
    out = _gut(src, ["Double"])
    assert "return x * 2" not in out
    assert "return 0" in out
    assert "func (f *Foo) Double(x int) int" in out


def test_reverse_offset_multiple_functions() -> None:
    src = """package p

func A() int {
	return 111
}

func B() int {
	return 222
}

func C() int {
	return 333
}
"""
    out = _gut(src, ["A", "B", "C"])
    assert "return 111" not in out
    assert "return 222" not in out
    assert "return 333" not in out
    assert out.count("return 0") == 3
    assert "func A() int" in out
    assert "func B() int" in out
    assert "func C() int" in out


def test_zero_value_string() -> None:
    src = """package p
func F() string { return "x" }
"""
    out = _gut(src, ["F"])
    assert 'return ""' in out


def test_zero_value_int_and_int64() -> None:
    src = """package p
func F() int { return 1 }
func G() int64 { return 1 }
"""
    out = _gut(src, ["F", "G"])
    assert out.count("return 0") == 2


def test_zero_value_bool() -> None:
    src = """package p
func F() bool { return true }
"""
    out = _gut(src, ["F"])
    assert "return false" in out


def test_zero_value_error_uses_errors_new() -> None:
    src = """package p

import "errors"

func F() error {
	return errors.New("x")
}
"""
    out = _gut(src, ["F"])
    assert 'errors.New("F: not implemented")' in out


def test_zero_value_pointer_slice_map_interface() -> None:
    src = """package p
func F() *int { return nil }
func G() []int { return nil }
func H() map[string]int { return nil }
func I() interface{} { return nil }
"""
    out = _gut(src, ["F", "G", "H", "I"])
    assert out.count("return nil") == 4


def test_zero_value_custom_struct() -> None:
    src = """package p

type Point struct{ X, Y int }

func F() Point {
	return Point{X: 1}
}
"""
    out = _gut(src, ["F"])
    assert "return Point{}" in out


def test_last_error_return_gets_errors_new() -> None:
    src = """package p

import "errors"

func F() (string, int, error) {
	return "a", 1, errors.New("x")
}
"""
    out = _gut(src, ["F"])
    assert 'return "", 0, errors.New("F: not implemented")' in out


def test_import_injected_when_missing() -> None:
    src = """package p

import "fmt"

func F() error {
	fmt.Println("x")
	return nil
}
"""
    g = GoGutter()
    result = g.gut(src, GutSpec(rel_path="x.go", funcs=["F"]))
    assert _has_errors_import(result.gutted_source.encode("utf-8"))
    assert 'errors.New("F: not implemented")' in result.gutted_source


def test_import_not_duplicated_when_present() -> None:
    src = """package p

import (
	"errors"
	"fmt"
)

func F() error {
	fmt.Println("x")
	return errors.New("nope")
}
"""
    out = _gut(src, ["F"])
    assert out.count('"errors"') == 1


def test_import_injected_into_grouped_block() -> None:
    src = """package p

import (
	"fmt"
)

func F() error {
	fmt.Println("x")
	return nil
}
"""
    out = _gut(src, ["F"])
    assert '"errors"' in out
    assert '"fmt"' in out


def test_import_injected_after_single_import() -> None:
    src = """package p

import "fmt"

func F() error {
	fmt.Println("x")
	return nil
}
"""
    out = _gut(src, ["F"])
    assert 'import "errors"' in out


def test_preserves_comments_before_function() -> None:
    src = """package p

// Hello does a thing.
// Multi-line.
func Hello() int {
	return 42
}
"""
    out = _gut(src, ["Hello"])
    assert "// Hello does a thing." in out
    assert "// Multi-line." in out


def test_preserves_surrounding_code_byte_for_byte() -> None:
    src = """package p

const K = 1

func F() int {
	return 42
}

const L = 2
"""
    out = _gut(src, ["F"])
    assert "const K = 1" in out
    assert "const L = 2" in out


def test_multiline_signature() -> None:
    src = """package p

func Long(
	a int,
	b string,
) (int, error) {
	return a, nil
}
"""
    out = _gut(src, ["Long"])
    assert "func Long(\n\ta int,\n\tb string,\n) (int, error)" in out
    assert 'errors.New("Long: not implemented")' in out


def test_generic_type_params() -> None:
    src = """package p

func Map[T, U any](xs []T, f func(T) U) []U {
	return nil
}
"""
    out = _gut(src, ["Map"])
    assert "func Map[T, U any](xs []T, f func(T) U) []U" in out
    assert "return nil" in out


def test_blank_identifier_receiver() -> None:
    src = """package p

type R struct{}

func (_ *R) F() int {
	return 1
}
"""
    out = _gut(src, ["F"])
    assert "func (_ *R) F() int" in out
    assert "return 0" in out


def test_raises_when_function_not_found() -> None:
    src = "package p\n\nfunc F() {}\n"
    g = GoGutter()
    with pytest.raises(GutError):
        g.gut(src, GutSpec(rel_path="x.go", funcs=["Nope"]))


def test_no_return_body() -> None:
    src = """package p

func F() {
	println("hi")
}
"""
    out = _gut(src, ["F"])
    assert "TODO(agent)" in out
    assert "return" not in out.split("func F() {")[1].split("}")[0]


def test_gut_aborts_when_result_has_error_nodes(monkeypatch: pytest.MonkeyPatch) -> None:
    src = """package p

func F() int {
	return 42
}
"""

    def broken_stub(self, fn):  # type: ignore[no-untyped-def]
        return "{ this is not valid go @@@"

    monkeypatch.setattr(GoGutter, "stub_body", broken_stub)
    g = GoGutter()
    with pytest.raises(GutError):
        g.gut(src, GutSpec(rel_path="x.go", funcs=["F"]))
