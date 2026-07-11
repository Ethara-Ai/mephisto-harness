from __future__ import annotations

import argparse
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from sforge.author.errors import AuthorError


VALID_LANGS = frozenset({"go", "rust", "python", "typescript", "c", "cpp", "java", "zig", "lean"})
TASK_ID_RE = re.compile(r"^[a-z][a-z0-9_]*$")
DEFAULT_MODEL_CUTOFF = date(2025, 4, 1)


@dataclass
class GutTarget:
    rel_path: str
    funcs: list[str]


@dataclass
class AuthorConfig:
    task_id: str
    name: str
    category: str
    repo: str
    commit: str
    base: str
    lang: str
    gut_targets: list[GutTarget]
    cwd: str
    test_cmd: str
    test_filter: str
    build_cmd: str = ""
    cache_warm_cmd: str = ""
    internet: bool = False
    tier: str = "auto"
    min_tests: int = 20
    allow_precutoff: bool = False
    model_cutoff: date = DEFAULT_MODEL_CUTOFF
    no_calibrate: bool = False
    gutted_max: int = 5
    golden_min: int = 95
    eval_timeout: int = 600
    out_dir: Path = field(default_factory=lambda: Path("tasks"))
    dry_run: bool = False
    force: bool = False
    extra_notes: str = ""

    def __post_init__(self) -> None:
        if not TASK_ID_RE.match(self.task_id):
            raise AuthorError(
                f"invalid task_id: {self.task_id!r} (must match {TASK_ID_RE.pattern})"
            )
        if self.lang not in VALID_LANGS:
            raise AuthorError(
                f"unknown lang: {self.lang!r} (must be one of {sorted(VALID_LANGS)})"
            )
        if not self.gut_targets:
            raise AuthorError("at least one --gut target is required")

    @classmethod
    def from_namespace(cls, ns: argparse.Namespace) -> AuthorConfig:
        gut_raw = getattr(ns, "gut", None) or []
        gut_targets: list[GutTarget] = []
        for entry in gut_raw:
            if ":" not in entry:
                raise AuthorError(
                    f"invalid --gut spec: {entry!r} (expected 'relpath:func1,func2')"
                )
            rel_path, funcs_str = entry.split(":", 1)
            rel_path = rel_path.strip()
            funcs = [f.strip() for f in funcs_str.split(",") if f.strip()]
            if not rel_path:
                raise AuthorError(f"invalid --gut spec: {entry!r} (missing relpath)")
            if not funcs:
                raise AuthorError(f"invalid --gut spec: {entry!r} (missing functions)")
            gut_targets.append(GutTarget(rel_path=rel_path, funcs=funcs))

        model_cutoff = getattr(ns, "model_cutoff", None)
        if isinstance(model_cutoff, str):
            model_cutoff = date.fromisoformat(model_cutoff)
        elif model_cutoff is None:
            model_cutoff = DEFAULT_MODEL_CUTOFF

        out_dir = getattr(ns, "out_dir", None)
        out_dir = Path(out_dir) if out_dir is not None else Path("tasks")

        return cls(
            task_id=ns.task_id,
            name=ns.name,
            category=ns.category,
            repo=ns.repo,
            commit=ns.commit,
            base=ns.base,
            lang=ns.lang,
            gut_targets=gut_targets,
            cwd=ns.cwd,
            test_cmd=ns.test_cmd,
            test_filter=ns.test_filter,
            build_cmd=getattr(ns, "build_cmd", "") or "",
            cache_warm_cmd=getattr(ns, "cache_warm_cmd", "") or "",
            internet=getattr(ns, "internet", False),
            tier=getattr(ns, "tier", "auto"),
            min_tests=getattr(ns, "min_tests", 20),
            allow_precutoff=getattr(ns, "allow_precutoff", False),
            model_cutoff=model_cutoff,
            no_calibrate=getattr(ns, "no_calibrate", False),
            gutted_max=getattr(ns, "gutted_max", 5),
            golden_min=getattr(ns, "golden_min", 95),
            eval_timeout=getattr(ns, "eval_timeout", 600),
            out_dir=out_dir,
            dry_run=getattr(ns, "dry_run", False),
            force=getattr(ns, "force", False),
            extra_notes=getattr(ns, "extra_notes", "") or "",
        )
