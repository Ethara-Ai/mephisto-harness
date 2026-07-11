from __future__ import annotations

import re
from typing import ClassVar

from sforge.author.errors import GutError
from sforge.author.gutters.base import (
    BaseGutter,
    FunctionInfo,
    GutResult,
    GutSpec,
)


_ZIG_FUNC_RE = re.compile(r"^(?:pub\s+)?fn\s+(\w+)\s*\(", re.MULTILINE)


class ZigGutter(BaseGutter):
    lang: ClassVar[str] = "zig"

    def parse_functions(self, source: str) -> list[FunctionInfo]:
        return self._match_functions(source)

    def stub_body(self, fn: FunctionInfo) -> str:
        return f'{{\n    @panic("{fn.name}: not implemented");\n}}'

    def gut(self, source: str, spec: GutSpec) -> GutResult:
        matches = self._match_functions(source)
        by_name: dict[str, list[FunctionInfo]] = {}
        for m in matches:
            by_name.setdefault(m.name, []).append(m)

        selected: list[FunctionInfo] = []
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

        edits: list[tuple[int, int, str]] = []
        for fn in selected:
            edits.append((fn.body_start_byte, fn.body_end_byte, self.stub_body(fn)))

        edits.sort(key=lambda e: e[0], reverse=True)
        result = source
        for start, end, replacement in edits:
            result = result[:start] + replacement + result[end:]

        total_loc = sum(fn.body_loc for fn in selected)
        return GutResult(
            gutted_source=result,
            functions=selected,
            total_loc_gutted=total_loc,
        )

    def _match_functions(self, source: str) -> list[FunctionInfo]:
        results: list[FunctionInfo] = []
        for m in _ZIG_FUNC_RE.finditer(source):
            name = m.group(1)
            func_start = m.start()
            bounds = _find_body_bounds(source, func_start)
            if bounds is None:
                continue
            body_start, body_end = bounds
            signature = source[func_start:body_start].rstrip()
            body_loc = source[body_start:body_end].count("\n")
            results.append(
                FunctionInfo(
                    name=name,
                    signature=signature,
                    body_start_byte=body_start,
                    body_end_byte=body_end,
                    body_loc=body_loc,
                    receiver=None,
                    params=[],
                    returns=[],
                )
            )
        return results


def _find_body_bounds(source: str, search_from: int) -> tuple[int, int] | None:
    n = len(source)
    i = search_from
    paren_depth = 0
    brace_start = -1
    while i < n:
        ch = source[i]
        if ch == "(":
            paren_depth += 1
        elif ch == ")":
            paren_depth -= 1
        elif ch == "{" and paren_depth == 0:
            brace_start = i
            break
        i += 1
    if brace_start == -1:
        return None
    depth = 1
    i = brace_start + 1
    while i < n and depth > 0:
        ch = source[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
        i += 1
    if depth != 0:
        return None
    return (brace_start, i)
