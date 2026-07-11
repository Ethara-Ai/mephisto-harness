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


_LEAN_DEF_RE = re.compile(
    r"^(?:noncomputable\s+)?(?:private\s+)?(?:protected\s+)?"
    r"(?:def|theorem|lemma|abbrev|instance)\s+(\w+)",
    re.MULTILINE,
)

_LEAN_ASSIGN_RE = re.compile(r":=")

_LEAN_NEXT_TOPLEVEL_RE = re.compile(
    r"^(?:noncomputable\s+)?(?:private\s+)?(?:protected\s+)?"
    r"(?:def|theorem|lemma|abbrev|instance|class\b|structure\b|"
    r"namespace\b|section\b|end\b|#\w+|open\b|variable\b|attribute\b)",
    re.MULTILINE,
)


class LeanGutter(BaseGutter):
    lang: ClassVar[str] = "lean"

    def parse_functions(self, source: str) -> list[FunctionInfo]:
        return self._match_functions(source)

    def stub_body(self, fn: FunctionInfo) -> str:
        return ":=\n  sorry"

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
        toplevel_starts = [m.start() for m in _LEAN_NEXT_TOPLEVEL_RE.finditer(source)]

        for m in _LEAN_DEF_RE.finditer(source):
            name = m.group(1)
            func_start = m.start()

            next_def_pos = _next_toplevel_after(toplevel_starts, func_start + 1)
            search_end = next_def_pos if next_def_pos is not None else len(source)

            assign_match = _find_toplevel_assign(source, m.end(), search_end)
            if assign_match is None:
                continue
            assign_start = assign_match

            body_end = search_end

            signature = source[func_start:assign_start].rstrip()
            body_loc = source[assign_start:body_end].count("\n")
            results.append(
                FunctionInfo(
                    name=name,
                    signature=signature,
                    body_start_byte=assign_start,
                    body_end_byte=body_end,
                    body_loc=body_loc,
                    receiver=None,
                    params=[],
                    returns=[],
                )
            )
        return results


def _next_toplevel_after(starts: list[int], pos: int) -> int | None:
    for s in starts:
        if s > pos:
            return s
    return None


def _find_toplevel_assign(source: str, from_pos: int, to_pos: int) -> int | None:
    depth = 0
    last = None
    i = from_pos
    while i < to_pos - 1:
        ch = source[i]
        if ch in ("(", "[", "{"):
            depth += 1
        elif ch in (")", "]", "}"):
            depth -= 1
        elif ch == ":" and source[i + 1] == "=" and depth == 0:
            last = i
            i += 2
            continue
        i += 1
    return last
