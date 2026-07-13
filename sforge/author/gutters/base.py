from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import ClassVar


@dataclass
class GutSpec:
    rel_path: str
    funcs: list[str]


@dataclass
class FunctionInfo:
    name: str
    signature: str
    body_start_byte: int
    body_end_byte: int
    body_loc: int
    receiver: str | None
    params: list[str]
    returns: list[str]


@dataclass
class GutResult:
    gutted_source: str
    functions: list[FunctionInfo]
    total_loc_gutted: int


class BaseGutter(ABC):
    lang: ClassVar[str]

    @abstractmethod
    def parse_functions(self, source: str) -> list[FunctionInfo]: ...

    @abstractmethod
    def gut(self, source: str, spec: GutSpec) -> GutResult: ...

    @abstractmethod
    def stub_body(self, fn: FunctionInfo) -> str: ...

    def _wipe_stub(self, source: str) -> str:
        return "// TODO(agent): implement this file from scratch. See TASK.md for the specification.\n"

    def wipe_file(self, source: str) -> GutResult:
        total_loc = sum(1 for ln in source.splitlines() if ln.strip())
        stub = self._wipe_stub(source)
        return GutResult(
            gutted_source=stub,
            functions=[],
            total_loc_gutted=total_loc,
        )
