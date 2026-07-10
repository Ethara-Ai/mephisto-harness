from __future__ import annotations

from typing import ClassVar

from sforge.author.gutters.base import BaseGutter, FunctionInfo, GutResult, GutSpec


class RustGutter(BaseGutter):
    lang: ClassVar[str] = "rust"

    def parse_functions(self, source: str) -> list[FunctionInfo]:
        raise NotImplementedError("rust gutter not implemented in v1")

    def gut(self, source: str, spec: GutSpec) -> GutResult:
        raise NotImplementedError("rust gutter not implemented in v1")

    def stub_body(self, fn: FunctionInfo) -> str:
        raise NotImplementedError("rust gutter not implemented in v1")
