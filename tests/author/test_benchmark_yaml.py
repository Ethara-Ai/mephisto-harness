from __future__ import annotations

from pathlib import Path

import yaml

from sforge.author.benchmark_yaml import ensure_base, load_base_spec


def _write_bench(path: Path) -> None:
    data = {
        "base_images": {
            "go": {"official_image": "golang:1.22"},
        }
    }
    path.write_text(yaml.safe_dump(data, sort_keys=False))


def test_ensure_base_exists(tmp_path: Path) -> None:
    bench = tmp_path / "BENCHMARK.yaml"
    _write_bench(bench)
    assert ensure_base(bench, "go") == "exists"


def test_ensure_base_missing(tmp_path: Path) -> None:
    bench = tmp_path / "BENCHMARK.yaml"
    _write_bench(bench)
    assert ensure_base(bench, "ruby") == "missing"


def test_load_base_spec_returns_dict(tmp_path: Path) -> None:
    bench = tmp_path / "BENCHMARK.yaml"
    _write_bench(bench)
    assert load_base_spec(bench, "go") == {"official_image": "golang:1.22"}


def test_load_base_spec_missing_returns_none(tmp_path: Path) -> None:
    bench = tmp_path / "BENCHMARK.yaml"
    _write_bench(bench)
    assert load_base_spec(bench, "ruby") is None


def test_load_base_spec_empty_yaml(tmp_path: Path) -> None:
    bench = tmp_path / "BENCHMARK.yaml"
    bench.write_text("")
    assert load_base_spec(bench, "go") is None
    assert ensure_base(bench, "go") == "missing"
