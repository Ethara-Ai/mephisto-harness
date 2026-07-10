from __future__ import annotations

import os
import subprocess
from datetime import date
from pathlib import Path

import pytest

from sforge.author.commit_info import check_contamination, get_commit_date
from sforge.author.errors import ContaminationError


def _init_repo(repo: Path, commit_date_iso: str) -> str:
    env = os.environ.copy()
    env["GIT_AUTHOR_DATE"] = commit_date_iso
    env["GIT_COMMITTER_DATE"] = commit_date_iso
    env["GIT_AUTHOR_NAME"] = "Test"
    env["GIT_AUTHOR_EMAIL"] = "test@example.com"
    env["GIT_COMMITTER_NAME"] = "Test"
    env["GIT_COMMITTER_EMAIL"] = "test@example.com"
    subprocess.run(
        ["git", "init", "-q", "-b", "main", str(repo)],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    subprocess.run(
        ["git", "-C", str(repo), "config", "commit.gpgsign", "false"],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    (repo / "README.md").write_text("hi\n")
    subprocess.run(
        ["git", "-C", str(repo), "add", "-A"],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    subprocess.run(
        ["git", "-C", str(repo), "commit", "-q", "-m", "init"],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    return subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    ).stdout.strip()


def test_get_commit_date_returns_iso_date(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    sha = _init_repo(repo, "2020-01-01T00:00:00Z")
    assert get_commit_date(repo, sha) == date(2020, 1, 1)


def test_check_contamination_before_cutoff_raises() -> None:
    with pytest.raises(ContaminationError):
        check_contamination(date(2020, 1, 1), date(2025, 4, 1), allow=False)


def test_check_contamination_after_cutoff_passes() -> None:
    check_contamination(date(2026, 1, 1), date(2025, 4, 1), allow=False)


def test_check_contamination_at_boundary_passes() -> None:
    check_contamination(date(2025, 4, 1), date(2025, 4, 1), allow=False)


def test_check_contamination_allow_bypass_never_raises() -> None:
    check_contamination(date(2020, 1, 1), date(2025, 4, 1), allow=True)
    check_contamination(date(1999, 12, 31), date(2025, 4, 1), allow=True)
