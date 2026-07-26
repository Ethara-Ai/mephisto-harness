from __future__ import annotations

from pathlib import Path

import pytest

from sforge.harness.benchmark import load_benchmark

_BENCH_YAML = """\
name: edgebench
base_images:
  python:
    official_image: python:3.11
"""


def _write_bench(dir_path: Path) -> None:
    dir_path.mkdir(parents=True, exist_ok=True)
    (dir_path / "BENCHMARK.yaml").write_text(_BENCH_YAML)


def test_orphan_tasks_dir_loads_via_external_benchmark(tmp_path: Path) -> None:
    tasks_dir = tmp_path / "dataset" / "some-uuid"
    tasks_dir.mkdir(parents=True)
    bench_dir = tmp_path / "harbor"
    _write_bench(bench_dir)

    meta = load_benchmark(tasks_dir, bench_dir)

    assert meta.name == "edgebench"
    assert "python" in meta.base_images


def test_orphan_tasks_dir_without_benchmark_raises(tmp_path: Path) -> None:
    tasks_dir = tmp_path / "dataset" / "some-uuid"
    tasks_dir.mkdir(parents=True)

    with pytest.raises(FileNotFoundError):
        load_benchmark(tasks_dir)


def test_relative_benchmark_dir_resolves_absolute(tmp_path: Path, monkeypatch) -> None:
    _write_bench(tmp_path / "harbor")
    monkeypatch.chdir(tmp_path)

    meta = load_benchmark(Path("dataset"), Path("harbor"))

    assert meta.name == "edgebench"


def test_default_behavior_reads_from_tasks_dir(tmp_path: Path) -> None:
    _write_bench(tmp_path)

    meta = load_benchmark(tmp_path)

    assert meta.name == "edgebench"
