from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

import tree_sitter_cpp
from tree_sitter import Language, Node, Parser, Query, QueryCursor

from sforge.author.errors import GutError
from sforge.author.gutters.base import (
    BaseGutter,
    FunctionInfo,
    GutResult,
    GutSpec,
)


_CPP_LANG = Language(tree_sitter_cpp.language())
_PARSER = Parser(_CPP_LANG)

_QUERY_SRC = """
(function_definition
  body: (compound_statement) @body) @func
"""
_QUERY = Query(_CPP_LANG, _QUERY_SRC)


@dataclass
class _FuncMatch:
    name: str
    func_node: Node
    body_node: Node
    info: FunctionInfo


class CppGutter(BaseGutter):
    lang: ClassVar[str] = "cpp"

    def parse_functions(self, source: str) -> list[FunctionInfo]:
        return [m.info for m in self._match_functions(source)]

    def stub_body(self, fn: FunctionInfo) -> str:
        return "{\n    __builtin_trap();\n}"

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
        edits: list[tuple[int, int, bytes]] = []
        for m in selected:
            stub = self.stub_body(m.info).encode("utf-8")
            edits.append((m.body_node.start_byte, m.body_node.end_byte, stub))

        edits.sort(key=lambda e: e[0], reverse=True)
        gutted = bytearray(source_bytes)
        for start, end, replacement in edits:
            gutted[start:end] = replacement
        gutted_bytes = bytes(gutted)

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
        body_nodes = captures.get("body", [])

        body_by_func_id: dict[int, Node] = {}
        for b in body_nodes:
            parent = _enclosing_function(b)
            if parent is not None:
                body_by_func_id[parent.id] = b

        results: list[_FuncMatch] = []
        for f in func_nodes:
            body = body_by_func_id.get(f.id)
            if body is None:
                continue
            decl = f.child_by_field_name("declarator")
            if decl is None:
                continue
            name_text = _extract_func_name(decl, source_bytes)
            if name_text is None:
                continue
            signature = source_bytes[f.start_byte : body.start_byte].decode(
                "utf-8"
            ).rstrip()
            body_loc = max(0, body.end_point[0] - body.start_point[0])
            info = FunctionInfo(
                name=name_text,
                signature=signature,
                body_start_byte=body.start_byte,
                body_end_byte=body.end_byte,
                body_loc=body_loc,
                receiver=None,
                params=_extract_params(decl, source_bytes),
                returns=[],
            )
            results.append(
                _FuncMatch(name=name_text, func_node=f, body_node=body, info=info)
            )
        results.sort(key=lambda m: m.func_node.start_byte)
        return results


def _text(node: Node, src: bytes) -> str:
    return src[node.start_byte : node.end_byte].decode("utf-8")


def _enclosing_function(node: Node) -> Node | None:
    cur = node.parent
    while cur is not None:
        if cur.type == "function_definition":
            return cur
        cur = cur.parent
    return None


def _extract_func_name(node: Node, src: bytes) -> str | None:
    ntype = node.type
    if ntype == "identifier":
        return _text(node, src)
    if ntype == "qualified_identifier":
        name_child = node.child_by_field_name("name")
        if name_child is not None:
            return _extract_func_name(name_child, src)
    if ntype in ("destructor_name", "operator_name"):
        return _text(node, src)
    for field in ("declarator", "name"):
        child = node.child_by_field_name(field)
        if child is not None:
            result = _extract_func_name(child, src)
            if result is not None:
                return result
    return None


def _extract_params(declarator: Node, src: bytes) -> list[str]:
    if declarator.type == "function_declarator":
        params = declarator.child_by_field_name("parameters")
        if params is None:
            return []
        out: list[str] = []
        for child in params.named_children:
            if child.type in ("parameter_declaration", "variadic_parameter"):
                out.append(_text(child, src).strip())
        return out
    child = declarator.child_by_field_name("declarator")
    if child is not None:
        return _extract_params(child, src)
    return []


def _iter_nodes(node: Node):
    yield node
    for c in node.children:
        yield from _iter_nodes(c)


def _error_node_ranges(src: bytes) -> set[tuple[int, int]]:
    tree = _PARSER.parse(src)
    out: set[tuple[int, int]] = set()
    for node in _iter_nodes(tree.root_node):
        if node.type == "ERROR" or node.is_missing:
            out.add((node.start_byte, node.end_byte))
    return out
