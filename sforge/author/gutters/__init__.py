from __future__ import annotations

import importlib

from sforge.author.errors import AuthorError
from sforge.author.gutters.base import BaseGutter


_LANG_MAP: dict[str, tuple[str, str]] = {
    "go": ("sforge.author.gutters.go", "GoGutter"),
    "rust": ("sforge.author.gutters.rust", "RustGutter"),
    "python": ("sforge.author.gutters.python", "PythonGutter"),
    "typescript": ("sforge.author.gutters.typescript", "TypeScriptGutter"),
    "c": ("sforge.author.gutters.c", "CGutter"),
    "cpp": ("sforge.author.gutters.cpp", "CppGutter"),
    "java": ("sforge.author.gutters.java", "JavaGutter"),
    "zig": ("sforge.author.gutters.zig", "ZigGutter"),
    "lean": ("sforge.author.gutters.lean", "LeanGutter"),
}


def get_gutter(lang: str) -> BaseGutter:
    entry = _LANG_MAP.get(lang)
    if entry is None:
        raise AuthorError(f"unknown lang: {lang}")
    module_name, class_name = entry
    try:
        module = importlib.import_module(module_name)
    except ImportError as exc:
        raise NotImplementedError(
            f"{lang} gutter not implemented in v1 (Wave B): {exc}"
        ) from exc
    cls = getattr(module, class_name)
    return cls()
