from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

import tree_sitter_rust
from tree_sitter import Language, Node, Parser, Query, QueryCursor

from sforge.author.errors import GutError
from sforge.author.gutters.base import (
    BaseGutter,
    FunctionInfo,
    GutResult,
    GutSpec,
)


_RUST_LANG = Language(tree_sitter_rust.language())
_PARSER = Parser(_RUST_LANG)

_QUERY_SRC = """
(function_item
  name: (identifier) @name
  body: (block) @body) @func
"""
_QUERY = Query(_RUST_LANG, _QUERY_SRC)


@dataclass
class _FuncMatch:
    name: str
    func_node: Node
    body_node: Node
    info: FunctionInfo


class RustGutter(BaseGutter):
    lang: ClassVar[str] = "rust"

    def parse_functions(self, source: str) -> list[FunctionInfo]:
        return [m.info for m in self._match_functions(source)]

    def stub_body(self, fn: FunctionInfo) -> str:
        return f'{{\n    todo!("{fn.name}: not implemented")\n}}'

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
        name_nodes = captures.get("name", [])
        body_nodes = captures.get("body", [])

        by_func: dict[int, dict[str, Node]] = {}
        for f in func_nodes:
            by_func[f.id] = {"func": f}
        for n in name_nodes:
            parent = _enclosing_function(n)
            if parent is not None and parent.id in by_func:
                by_func[parent.id]["name"] = n
        for b in body_nodes:
            parent = _enclosing_function(b)
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
                params=_extract_params(f, source_bytes),
                returns=_extract_returns(f, source_bytes),
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
        if cur.type == "function_item":
            return cur
        cur = cur.parent
    return None


def _extract_params(func_node: Node, src: bytes) -> list[str]:
    params = func_node.child_by_field_name("parameters")
    if params is None:
        return []
    out: list[str] = []
    for child in params.named_children:
        if child.type in ("parameter", "self_parameter", "variadic_parameter"):
            out.append(_text(child, src).strip())
    return out


def _extract_returns(func_node: Node, src: bytes) -> list[str]:
    ret = func_node.child_by_field_name("return_type")
    if ret is None:
        return []
    return [_text(ret, src).strip()]


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
