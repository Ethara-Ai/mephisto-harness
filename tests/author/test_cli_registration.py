from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "sforge", *args],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        timeout=60,
    )


def test_top_level_help_lists_subcommand() -> None:
    r = _run("--help")
    assert r.returncode == 0, r.stderr
    assert "author-clone-gut" in r.stdout


def test_subcommand_help_lists_all_flags() -> None:
    r = _run("author-clone-gut", "--help")
    assert r.returncode == 0, r.stderr
    for flag in (
        "--task-id",
        "--name",
        "--category",
        "--repo",
        "--commit",
        "--base",
        "--lang",
        "--gut",
        "--cwd",
        "--test-cmd",
        "--test-filter",
        "--build-cmd",
        "--cache-warm-cmd",
        "--internet",
        "--tier",
        "--min-tests",
        "--allow-precutoff",
        "--model-cutoff",
        "--no-calibrate",
        "--gutted-max",
        "--golden-min",
        "--eval-timeout",
        "--out-dir",
        "--dry-run",
        "--force",
        "--extra-notes",
    ):
        assert flag in r.stdout, f"missing flag {flag}"
