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
