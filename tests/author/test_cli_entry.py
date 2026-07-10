from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from sforge.author.calibrate import CalibrationReport
from sforge.author.cli_entry import cmd_author_clone_gut
from sforge.author.errors import (
    CalibrationError,
    ContaminationError,
    GutError,
    ManifestError,
    TierMismatchError,
)


_GOAWK_COMMIT = "4c907fb2838a4f819252cc3030e898eebf8a1c10"
_GO_SOURCE = """package pkg

import "errors"

func Foo() (string, error) {
\treturn "hello", nil
}

func Bar(x int) int {
\treturn x + 1
}
"""


def _write_benchmark(tmp_path: Path, *, base_keys=("go",)) -> Path:
    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir(parents=True, exist_ok=True)
    lines = ["name: test", "base_images:"]
    for key in base_keys:
        lines.append(f"  {key}:")
        lines.append(f"    official_image: golang:1.22")
        lines.append(f"    extra_packages: [git]")
    (tasks_dir / "BENCHMARK.yaml").write_text("\n".join(lines) + "\n")
    return tasks_dir


def _args(**overrides: Any) -> argparse.Namespace:
    defaults = dict(
        task_id="fake_task",
        name="Fake Task",
        category="code_reconstruction",
        repo="https://example.com/fake.git",
        commit=_GOAWK_COMMIT,
        base="go",
        lang="go",
        gut=["pkg/a.go:Foo"],
        cwd="/home/workspace/fake",
        test_cmd="go test ./...",
        test_filter=".*",
        build_cmd="go build ./...",
        cache_warm_cmd="",
        internet=False,
        tier="auto",
        min_tests=20,
        allow_precutoff=False,
        model_cutoff="2025-04-01",
        no_calibrate=True,
        gutted_max=5.0,
        golden_min=95.0,
        eval_timeout=600,
        out_dir="tasks",
        dry_run=True,
        force=False,
        extra_notes="",
        tasks_dir=None,
        log_dir=None,
    )
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


def _install_workspace_mocks(
    monkeypatch,
    *,
    files: dict[str, bytes] | None = None,
    commit_date: date = date(2026, 5, 1),
) -> None:
    def _fake_clone(repo: str, commit: str, work_dir: Path) -> Path:
        checkout = work_dir / "repo"
        checkout.mkdir(parents=True, exist_ok=True)
        if files is not None:
            for rel, content in files.items():
                target = checkout / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(content)
        return checkout

    monkeypatch.setattr("sforge.author.cli_entry.workspace.clone", _fake_clone)
    monkeypatch.setattr(
        "sforge.author.cli_entry.commit_info.get_commit_date",
        lambda repo_path, sha: commit_date,
    )


def test_dry_run_prints_manifest_and_exits_zero(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    tasks_dir = _write_benchmark(tmp_path)
    monkeypatch.setenv("SFORGE_TASKS_DIR", str(tasks_dir))
    _install_workspace_mocks(monkeypatch, files={"pkg/a.go": _GO_SOURCE.encode()})

    args = _args(out_dir=str(tmp_path / "out"))
    rc = cmd_author_clone_gut(args)
    assert rc == 0

    out = capsys.readouterr().out
    manifest = json.loads(out)
    assert manifest["task_id"] == "fake_task"
    assert manifest["base_image"] == "go"
    assert manifest["submit_paths"] == ["pkg/a.go"]
    assert not (tmp_path / "out" / "fake_task.json").exists()


def test_missing_base_raises_manifest_error(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    _write_benchmark(tmp_path, base_keys=("python",))
    monkeypatch.setenv("SFORGE_TASKS_DIR", str(tmp_path / "tasks"))
    _install_workspace_mocks(monkeypatch, files={"pkg/a.go": _GO_SOURCE.encode()})

    rc = cmd_author_clone_gut(_args())
    assert rc == ManifestError.exit_code
    err = capsys.readouterr().err
    assert "'go' not present" in err or "go' not present" in err


def test_missing_benchmark_yaml_raises_manifest_error(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    monkeypatch.setenv("SFORGE_TASKS_DIR", str(tmp_path / "does_not_exist"))
    _install_workspace_mocks(monkeypatch, files={"pkg/a.go": _GO_SOURCE.encode()})

    rc = cmd_author_clone_gut(_args())
    assert rc == ManifestError.exit_code
    assert "BENCHMARK.yaml not found" in capsys.readouterr().err


def test_gut_target_file_missing_raises_gut_error(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    tasks_dir = _write_benchmark(tmp_path)
    monkeypatch.setenv("SFORGE_TASKS_DIR", str(tasks_dir))
    _install_workspace_mocks(monkeypatch, files={})

    rc = cmd_author_clone_gut(_args())
    assert rc == GutError.exit_code
    assert "gut target not found" in capsys.readouterr().err


def test_contamination_gate_blocks_without_allow(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    tasks_dir = _write_benchmark(tmp_path)
    monkeypatch.setenv("SFORGE_TASKS_DIR", str(tasks_dir))
    _install_workspace_mocks(
        monkeypatch,
        files={"pkg/a.go": _GO_SOURCE.encode()},
        commit_date=date(2023, 4, 1),
    )

    rc = cmd_author_clone_gut(_args(allow_precutoff=False))
    assert rc == ContaminationError.exit_code
    assert "predates cutoff" in capsys.readouterr().err


def test_contamination_gate_bypassed_with_allow(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    tasks_dir = _write_benchmark(tmp_path)
    monkeypatch.setenv("SFORGE_TASKS_DIR", str(tasks_dir))
    _install_workspace_mocks(
        monkeypatch,
        files={"pkg/a.go": _GO_SOURCE.encode()},
        commit_date=date(2023, 4, 1),
    )

    rc = cmd_author_clone_gut(_args(allow_precutoff=True))
    assert rc == 0


def test_tier_mismatch_warns_in_dry_run(tmp_path: Path, monkeypatch, capsys) -> None:
    tasks_dir = _write_benchmark(tmp_path)
    monkeypatch.setenv("SFORGE_TASKS_DIR", str(tasks_dir))
    _install_workspace_mocks(monkeypatch, files={"pkg/a.go": _GO_SOURCE.encode()})

    rc = cmd_author_clone_gut(_args(tier="extreme"))
    assert rc == 0
    err = capsys.readouterr().err
    assert "cannot be enforced during dry-run" in err
    assert "extreme" in err


def test_tier_mismatch_warns_in_no_calibrate(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    tasks_dir = _write_benchmark(tmp_path)
    monkeypatch.setenv("SFORGE_TASKS_DIR", str(tasks_dir))
    _install_workspace_mocks(monkeypatch, files={"pkg/a.go": _GO_SOURCE.encode()})

    out_dir = tmp_path / "out"
    rc = cmd_author_clone_gut(
        _args(tier="extreme", dry_run=False, no_calibrate=True, out_dir=str(out_dir))
    )
    assert rc == 0
    err = capsys.readouterr().err
    assert "cannot be enforced with --no-calibrate" in err


def test_tier_mismatch_enforced_after_calibration(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    tasks_dir = _write_benchmark(tmp_path)
    monkeypatch.setenv("SFORGE_TASKS_DIR", str(tasks_dir))
    _install_workspace_mocks(monkeypatch, files={"pkg/a.go": _GO_SOURCE.encode()})

    class _FakeReport:
        gutted_score = 1.0
        golden_score = 100.0
        gutted_runtime = 1.0
        golden_runtime = 1.0
        golden_total_tests = 5

    def _fake_calibrate(config, out_path, gutted_files, originals):
        return _FakeReport()

    import sforge.author.cli_entry as cli_entry_mod

    monkeypatch.setattr(cli_entry_mod.calibrate_mod, "calibrate", _fake_calibrate)

    out_dir = tmp_path / "out"
    rc = cmd_author_clone_gut(
        _args(tier="extreme", dry_run=False, no_calibrate=False, out_dir=str(out_dir))
    )
    assert rc == TierMismatchError.exit_code
    assert "tier mismatch" in capsys.readouterr().err


def test_no_calibrate_writes_manifest_and_reports(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    tasks_dir = _write_benchmark(tmp_path)
    monkeypatch.setenv("SFORGE_TASKS_DIR", str(tasks_dir))
    _install_workspace_mocks(monkeypatch, files={"pkg/a.go": _GO_SOURCE.encode()})

    out_dir = tmp_path / "out"
    rc = cmd_author_clone_gut(_args(dry_run=False, no_calibrate=True, out_dir=str(out_dir)))
    assert rc == 0
    written = out_dir / "fake_task.json"
    assert written.exists()
    data = json.loads(written.read_text())
    assert data["task_id"] == "fake_task"

    out = capsys.readouterr().out
    assert "Manifest written" in out
    assert "Skipped calibration" in out


def test_force_required_to_overwrite(tmp_path: Path, monkeypatch, capsys) -> None:
    tasks_dir = _write_benchmark(tmp_path)
    monkeypatch.setenv("SFORGE_TASKS_DIR", str(tasks_dir))
    _install_workspace_mocks(monkeypatch, files={"pkg/a.go": _GO_SOURCE.encode()})

    out_dir = tmp_path / "out"
    out_dir.mkdir()
    (out_dir / "fake_task.json").write_text("{}")

    rc = cmd_author_clone_gut(
        _args(dry_run=False, no_calibrate=True, out_dir=str(out_dir))
    )
    assert rc == ManifestError.exit_code
    assert "already exists" in capsys.readouterr().err


def test_calibration_success_prints_scores(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    tasks_dir = _write_benchmark(tmp_path)
    monkeypatch.setenv("SFORGE_TASKS_DIR", str(tasks_dir))
    _install_workspace_mocks(monkeypatch, files={"pkg/a.go": _GO_SOURCE.encode()})

    def _fake_calibrate(config, manifest_path, gutted, golden):
        return CalibrationReport(
            gutted_score=1.82,
            golden_score=100.0,
            gutted_runtime=11.5,
            golden_runtime=22.3,
            gutted_log_dir=tmp_path / "gutted-log",
            golden_log_dir=tmp_path / "golden-log",
            golden_total_tests=55,
        )

    monkeypatch.setattr(
        "sforge.author.cli_entry.calibrate_mod.calibrate", _fake_calibrate
    )

    out_dir = tmp_path / "out"
    rc = cmd_author_clone_gut(
        _args(dry_run=False, no_calibrate=False, out_dir=str(out_dir))
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "Calibration" in out
    assert "1.82" in out
    assert "100.00" in out


def test_calibration_failure_returns_exit_code_4(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    tasks_dir = _write_benchmark(tmp_path)
    monkeypatch.setenv("SFORGE_TASKS_DIR", str(tasks_dir))
    _install_workspace_mocks(monkeypatch, files={"pkg/a.go": _GO_SOURCE.encode()})

    def _fail(*args, **kw):
        raise CalibrationError("gutted 50 > 5")

    monkeypatch.setattr("sforge.author.cli_entry.calibrate_mod.calibrate", _fail)

    rc = cmd_author_clone_gut(
        _args(dry_run=False, no_calibrate=False, out_dir=str(tmp_path / "out"))
    )
    assert rc == CalibrationError.exit_code
    assert "gutted 50 > 5" in capsys.readouterr().err
