from __future__ import annotations

import os
import subprocess
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from sforge.author.errors import CloneError


_LANG_EXTS: dict[str, tuple[str, ...]] = {
    "go": (".go",),
    "rust": (".rs",),
    "python": (".py",),
    "typescript": (".ts", ".tsx"),
    "c": (".c", ".h"),
    "cpp": (".cpp", ".cc", ".cxx", ".hpp", ".h"),
    "java": (".java",),
    "zig": (".zig",),
    "lean": (".lean",),
}

_SKIP_DIRS = frozenset({"vendor", "target", "node_modules", ".git"})


def clone(repo: str, commit: str, work_dir: Path) -> Path:
    work_dir.mkdir(parents=True, exist_ok=True)
    checkout = work_dir / "repo"
    subprocess.run(
        ["git", "clone", repo, str(checkout)],
        check=True,
        capture_output=True,
        text=True,
        timeout=300,
    )
    subprocess.run(
        ["git", "-C", str(checkout), "checkout", commit],
        check=True,
        capture_output=True,
        text=True,
        timeout=60,
    )
    return checkout


def count_repo_loc(path: Path, lang: str) -> int:
    exts = _LANG_EXTS.get(lang)
    if exts is None:
        raise CloneError(f"unknown lang for LOC counting: {lang!r}")
    total = 0
    for src in _iter_source_files(path, exts):
        with src.open("rb") as fh:
            for line in fh:
                if line.strip():
                    total += 1
    return total


def _iter_source_files(root: Path, exts: tuple[str, ...]) -> Iterator[Path]:
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
        for name in filenames:
            if name.endswith(exts):
                yield Path(dirpath) / name


@contextmanager
def temp_workspace() -> Iterator[Path]:
    with tempfile.TemporaryDirectory(prefix="sforge-author-") as td:
        yield Path(td)
