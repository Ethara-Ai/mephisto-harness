from __future__ import annotations

import re
from dataclasses import dataclass
from typing import ClassVar

import tree_sitter_go
from tree_sitter import Language, Node, Parser, Query, QueryCursor

from sforge.author.errors import GutError
from sforge.author.gutters.base import (
    BaseGutter,
    FunctionInfo,
    GutResult,
    GutSpec,
)


_GO_LANG = Language(tree_sitter_go.language())
_PARSER = Parser(_GO_LANG)

_QUERY_SRC = """
(function_declaration
  name: (identifier) @name
  body: (block) @body) @func

(method_declaration
  name: (field_identifier) @name
  body: (block) @body) @func
"""
_QUERY = Query(_GO_LANG, _QUERY_SRC)

_NUMERIC_TYPES = {
    "int", "int8", "int16", "int32", "int64",
    "uint", "uint8", "uint16", "uint32", "uint64",
    "uintptr", "byte", "rune",
    "float32", "float64",
    "complex64", "complex128",
}


@dataclass
class _FuncMatch:
    name: str
    func_node: Node
    body_node: Node
    info: FunctionInfo


class GoGutter(BaseGutter):
    lang: ClassVar[str] = "go"

    def parse_functions(self, source: str) -> list[FunctionInfo]:
        return [m.info for m in self._match_functions(source)]

    def stub_body(self, fn: FunctionInfo) -> str:
        if not fn.returns:
            return (
                "{\n"
                "\t// TODO(agent): reimplement this function.\n"
                "\t// See TASK.md for the specification.\n"
                "}"
            )
        zeros = _zero_values(fn.returns, fn.name)
        return (
            "{\n"
            "\t// TODO(agent): reimplement this function.\n"
            "\t// See TASK.md for the specification.\n"
            f"\treturn {', '.join(zeros)}\n"
            "}"
        )

    def gut(self, source: str, spec: GutSpec) -> GutResult:
        matches = self._match_functions(source)
        by_name: dict[str, list[_FuncMatch]] = {}
        for m in matches:
            by_name.setdefault(m.name, []).append(m)

        selected: list[_FuncMatch] = []
        missing: list[str] = []
        for fname in spec.funcs:
            hits = by_name.get(fname)
            if not hits:
                missing.append(fname)
                continue
            selected.extend(hits)
        if missing:
            raise GutError(
                f"functions not found in {spec.rel_path}: {', '.join(missing)}"
            )

        source_bytes = source.encode("utf-8")
        needs_errors = any(_needs_errors_import(m.info) for m in selected)

        edits: list[tuple[int, int, bytes]] = []
        for m in selected:
            stub = self.stub_body(m.info).encode("utf-8")
            edits.append((m.body_node.start_byte, m.body_node.end_byte, stub))

        edits.sort(key=lambda e: e[0], reverse=True)
        gutted = bytearray(source_bytes)
        for start, end, replacement in edits:
            gutted[start:end] = replacement
        gutted_bytes = bytes(gutted)

        if needs_errors and not _has_errors_import(source_bytes):
            gutted_bytes = _inject_errors_import(gutted_bytes)

        original_error_ranges = _error_node_ranges(source_bytes)
        new_error_ranges = _error_node_ranges(gutted_bytes)
        introduced = new_error_ranges - original_error_ranges
        if introduced:
            first = sorted(introduced)[0]
            raise GutError(
                f"gutted source contains ERROR node at byte range {first}"
            )

        total_loc = sum(m.info.body_loc for m in selected)
        return GutResult(
            gutted_source=gutted_bytes.decode("utf-8"),
            functions=[m.info for m in selected],
            total_loc_gutted=total_loc,
        )

    def _match_functions(self, source: str) -> list[_FuncMatch]:
        source_bytes = source.encode("utf-8")
        tree = _PARSER.parse(source_bytes)
        cursor = QueryCursor(_QUERY)
        captures = cursor.captures(tree.root_node)

        func_nodes = captures.get("func", [])
        name_nodes = captures.get("name", [])
        body_nodes = captures.get("body", [])

        by_func: dict[int, dict[str, Node]] = {}
        for f in func_nodes:
            by_func[f.id] = {"func": f}
        for n in name_nodes:
            parent = _enclosing_func_or_method(n)
            if parent is not None and parent.id in by_func:
                by_func[parent.id]["name"] = n
        for b in body_nodes:
            parent = _enclosing_func_or_method(b)
            if parent is not None and parent.id in by_func:
                by_func[parent.id]["body"] = b

        results: list[_FuncMatch] = []
        for entry in by_func.values():
            f = entry.get("func")
            name = entry.get("name")
            body = entry.get("body")
            if f is None or name is None or body is None:
                continue
            name_text = _text(name, source_bytes)
            signature = source_bytes[f.start_byte:body.start_byte].decode(
                "utf-8"
            ).rstrip()
            body_loc = max(0, body.end_point[0] - body.start_point[0])
            info = FunctionInfo(
                name=name_text,
                signature=signature,
                body_start_byte=body.start_byte,
                body_end_byte=body.end_byte,
                body_loc=body_loc,
                receiver=_extract_receiver(f, source_bytes),
                params=_extract_params(f, source_bytes),
                returns=_extract_returns(f, source_bytes),
            )
            results.append(
                _FuncMatch(name=name_text, func_node=f, body_node=body, info=info)
            )
        results.sort(key=lambda m: m.func_node.start_byte)
        return results


def _text(node: Node, src: bytes) -> str:
    return src[node.start_byte:node.end_byte].decode("utf-8")


def _enclosing_func_or_method(node: Node) -> Node | None:
    cur = node.parent
    while cur is not None:
        if cur.type in ("function_declaration", "method_declaration"):
            return cur
        cur = cur.parent
    return None


def _extract_receiver(func_node: Node, src: bytes) -> str | None:
    if func_node.type != "method_declaration":
        return None
    recv = func_node.child_by_field_name("receiver")
    if recv is None:
        return None
    text = _text(recv, src).strip()
    if text.startswith("(") and text.endswith(")"):
        text = text[1:-1].strip()
    return text


def _extract_params(func_node: Node, src: bytes) -> list[str]:
    params = func_node.child_by_field_name("parameters")
    if params is None:
        return []
    out: list[str] = []
    for child in params.named_children:
        if child.type in ("parameter_declaration", "variadic_parameter_declaration"):
            out.append(_text(child, src).strip())
    return out


def _extract_returns(func_node: Node, src: bytes) -> list[str]:
    ret = func_node.child_by_field_name("result")
    if ret is None:
        return []
    if ret.type == "parameter_list":
        out: list[str] = []
        for child in ret.named_children:
            if child.type == "parameter_declaration":
                type_node = child.child_by_field_name("type")
                if type_node is None:
                    out.append(_text(child, src).strip())
                else:
                    type_text = _text(type_node, src).strip()
                    name_count = sum(
                        1 for c in child.named_children if c.type == "identifier"
                    )
                    if name_count == 0:
                        name_count = 1
                    out.extend([type_text] * name_count)
        return out
    return [_text(ret, src).strip()]


def _zero_for(type_text: str) -> str:
    t = type_text.strip()
    if not t:
        return "nil"
    if t == "error":
        return "nil"
    if t == "string":
        return '""'
    if t == "bool":
        return "false"
    if t in _NUMERIC_TYPES:
        return "0"
    if (
        t.startswith("*")
        or t.startswith("[]")
        or t.startswith("map[")
        or t.startswith("chan")
        or t.startswith("<-chan")
        or t.startswith("chan<-")
        or t.startswith("func(")
        or t.startswith("interface{")
        or t == "any"
        or t == "interface{}"
    ):
        return "nil"
    if re.match(r"^\[\d*\][^\s]", t):
        return f"{t}{{}}"
    if "." in t or re.match(r"^[A-Za-z_][A-Za-z0-9_]*(\[.*\])?$", t):
        return f"{t}{{}}"
    return "nil"


def _zero_values(returns: list[str], func_name: str) -> list[str]:
    zeros = [_zero_for(r) for r in returns]
    last_error_idx = -1
    for i, r in enumerate(returns):
        if r.strip() == "error":
            last_error_idx = i
    if last_error_idx >= 0:
        zeros[last_error_idx] = f'errors.New("{func_name}: not implemented")'
    return zeros


def _needs_errors_import(fn: FunctionInfo) -> bool:
    return any(r.strip() == "error" for r in fn.returns)


def _has_errors_import(src: bytes) -> bool:
    tree = _PARSER.parse(src)
    for node in _iter_nodes(tree.root_node):
        if node.type == "import_spec":
            path_node = node.child_by_field_name("path")
            if path_node is not None:
                txt = _text(path_node, src).strip()
                if txt == '"errors"':
                    return True
    return False


def _iter_nodes(node: Node):
    yield node
    for c in node.children:
        yield from _iter_nodes(c)


def _inject_errors_import(src: bytes) -> bytes:
    tree = _PARSER.parse(src)
    root = tree.root_node

    grouped_import: Node | None = None
    single_imports: list[Node] = []
    package_node: Node | None = None
    for child in root.children:
        if child.type == "package_clause":
            package_node = child
        elif child.type == "import_declaration":
            spec_list = None
            for c in child.children:
                if c.type == "import_spec_list":
                    spec_list = c
                    break
            if spec_list is not None:
                grouped_import = child
                break
            single_imports.append(child)

    if grouped_import is not None:
        spec_list = None
        for c in grouped_import.children:
            if c.type == "import_spec_list":
                spec_list = c
                break
        assert spec_list is not None
        insert_at = spec_list.start_byte + 1
        insertion = b'\n\t"errors"'
        return src[:insert_at] + insertion + src[insert_at:]

    if single_imports:
        last = single_imports[-1]
        insert_at = last.end_byte
        insertion = b'\nimport "errors"'
        return src[:insert_at] + insertion + src[insert_at:]

    if package_node is not None:
        insert_at = package_node.end_byte
        insertion = b'\n\nimport "errors"'
        return src[:insert_at] + insertion + src[insert_at:]

    raise GutError("could not find package clause to inject import")


def _error_node_ranges(src: bytes) -> set[tuple[int, int]]:
    tree = _PARSER.parse(src)
    out: set[tuple[int, int]] = set()
    for node in _iter_nodes(tree.root_node):
        if node.type == "ERROR" or node.is_missing:
            out.add((node.start_byte, node.end_byte))
    return out
