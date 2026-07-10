from __future__ import annotations

import subprocess
from datetime import date
from pathlib import Path

from sforge.author.errors import CloneError, ContaminationError


def get_commit_date(repo_path: Path, sha: str) -> date:
    result = subprocess.run(
        ["git", "-C", str(repo_path), "show", "-s", "--format=%ci", sha],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    out = result.stdout.strip()
    if len(out) < 10:
        raise CloneError(f"unexpected git show output for {sha}: {out!r}")
    return date.fromisoformat(out[:10])


def check_contamination(commit_date: date, cutoff: date, allow: bool) -> None:
    if commit_date >= cutoff:
        return
    if allow:
        return
    raise ContaminationError(
        f"commit date {commit_date.isoformat()} predates cutoff {cutoff.isoformat()}; "
        f"pass --allow-precutoff to override"
    )
