from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from sforge.author.calibrate import CalibrationReport, calibrate, pack_submission
from sforge.author.config import AuthorConfig, GutTarget
from sforge.author.errors import CalibrationError


def _make_config(**overrides) -> AuthorConfig:
    defaults = dict(
        task_id="fake_task",
        name="Fake Task",
        category="code_reconstruction",
        repo="https://example.com/fake.git",
        commit="deadbeefdeadbeefdeadbeefdeadbeefdeadbeef",
        base="go",
        lang="go",
        gut_targets=[GutTarget(rel_path="pkg/a.go", funcs=["Foo"])],
        cwd="/home/workspace/fake",
        test_cmd="go test ./...",
        test_filter=".*",
        build_cmd="go build ./...",
    )
    defaults.update(overrides)
    return AuthorConfig(**defaults)


def _write_minimal_manifest(tmp_path: Path, task_id: str = "fake_task") -> Path:
    (tmp_path / "BENCHMARK.yaml").write_text(
        "name: test\nbase_images:\n  go:\n    official_image: golang:1.22\n"
    )
    manifest = {
        "task_id": task_id,
        "name": "Fake",
        "category": "code_reconstruction",
        "base_image": "go",
        "platform": "linux/amd64",
        "internet": False,
        "cwd": "/home/workspace/fake",
        "submit_paths": ["pkg/a.go"],
        "submit_exclude": [],
        "work": {
            "setup_cmds": ["echo work"],
            "specs_dir": "/home/workspace/fake",
            "agent_query": "task",
        },
        "judge": {
            "setup_cmds": ["echo judge"],
            "eval_cmd": "bash /tmp/score.sh",
            "eval_timeout": 600,
            "parser": "structured_json",
            "score_direction": "maximize",
            "selection": "score_first",
            "rescale": {"kind": "linear", "lower": 0, "upper": 100},
        },
    }
    path = tmp_path / f"{task_id}.json"
    path.write_text(json.dumps(manifest))
    return path


def _fake_report(score: float, runtime: float = 12.5):
    r = SimpleNamespace()
    r.score_0_100 = score
    r.score = score
    r.runtime_seconds = runtime
    return r


def _install_docker_mocks(monkeypatch):
    monkeypatch.setattr("sforge.author.calibrate.docker.from_env", lambda: MagicMock())
    monkeypatch.setattr(
        "sforge.author.calibrate.create_backend_from_config",
        lambda *a, **kw: MagicMock(),
    )
    monkeypatch.setattr(
        "sforge.author.calibrate.build_all_images",
        lambda *a, **kw: ("base:tag", "work:tag", "judge:tag"),
    )


def test_pack_submission_produces_valid_targz() -> None:
    import io
    import tarfile

    files = {"a.go": b"package a\n", "b/c.go": b"package c\n"}
    data = pack_submission(files)
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
        names = sorted(tar.getnames())
        assert names == ["a.go", "b/c.go"]
        assert tar.extractfile("a.go").read() == b"package a\n"


def test_gutted_score_too_high_raises(tmp_path: Path, monkeypatch) -> None:
    manifest_path = _write_minimal_manifest(tmp_path)
    _install_docker_mocks(monkeypatch)

    monkeypatch.setattr(
        "sforge.author.calibrate.judge_submission",
        lambda *a, **kw: _fake_report(50.0),
    )

    cfg = _make_config(gutted_max=5, golden_min=95)
    with pytest.raises(CalibrationError, match=r"50\.00.*> gutted_max 5"):
        calibrate(cfg, manifest_path, {"pkg/a.go": b"stub"}, {"pkg/a.go": b"orig"})


def test_golden_score_too_low_raises(tmp_path: Path, monkeypatch) -> None:
    manifest_path = _write_minimal_manifest(tmp_path)
    _install_docker_mocks(monkeypatch)

    call_scores = iter([1.0, 40.0])
    monkeypatch.setattr(
        "sforge.author.calibrate.judge_submission",
        lambda *a, **kw: _fake_report(next(call_scores)),
    )

    cfg = _make_config(gutted_max=5, golden_min=95)
    with pytest.raises(CalibrationError, match=r"40\.00.*< golden_min 95"):
        calibrate(cfg, manifest_path, {"pkg/a.go": b"stub"}, {"pkg/a.go": b"orig"})


def test_both_pass_returns_report(tmp_path: Path, monkeypatch) -> None:
    manifest_path = _write_minimal_manifest(tmp_path)
    _install_docker_mocks(monkeypatch)

    call_scores = iter([1.82, 100.0])
    call_runtimes = iter([11.5, 22.3])

    def _judge(*a, **kw):
        return _fake_report(next(call_scores), next(call_runtimes))

    monkeypatch.setattr("sforge.author.calibrate.judge_submission", _judge)

    cfg = _make_config(gutted_max=5, golden_min=95)
    report = calibrate(cfg, manifest_path, {"pkg/a.go": b"stub"}, {"pkg/a.go": b"orig"})

    assert isinstance(report, CalibrationReport)
    assert report.gutted_score == pytest.approx(1.82)
    assert report.golden_score == pytest.approx(100.0)
    assert report.gutted_runtime == pytest.approx(11.5)
    assert report.golden_runtime == pytest.approx(22.3)
    assert report.gutted_log_dir.exists()
    assert report.golden_log_dir.exists()
