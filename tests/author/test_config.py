from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import pytest

from sforge.author.config import AuthorConfig, GutTarget
from sforge.author.errors import AuthorError


def _base_ns(**overrides: Any) -> argparse.Namespace:
    defaults: dict[str, Any] = dict(
        task_id="goawk_printf",
        name="GoAWK printf",
        category="code_reconstruction",
        repo="https://github.com/benhoyt/goawk",
        commit="4c907fb2838a4f819252cc3030e898eebf8a1c10",
        base="go",
        lang="go",
        gut=["interp/functions.go:parseFmtTypes,sprintf"],
        cwd="/home/workspace/goawk",
        test_cmd="go test ./...",
        test_filter="printf|sprintf",
    )
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


def test_from_namespace_roundtrip() -> None:
    cfg = AuthorConfig.from_namespace(_base_ns())
    assert cfg.task_id == "goawk_printf"
    assert cfg.name == "GoAWK printf"
    assert cfg.lang == "go"
    assert cfg.gut_targets == [
        GutTarget(rel_path="interp/functions.go", funcs=["parseFmtTypes", "sprintf"])
    ]
    assert cfg.out_dir == Path("tasks")
    assert cfg.internet is False
    assert cfg.tier == "auto"
    assert cfg.min_tests == 20
    assert cfg.allow_precutoff is False
    assert cfg.no_calibrate is False
    assert cfg.gutted_max == 5
    assert cfg.golden_min == 95
    assert cfg.eval_timeout == 600
    assert cfg.dry_run is False
    assert cfg.force is False


def test_from_namespace_multiple_gut_targets() -> None:
    ns = _base_ns(gut=["a/b.go:foo", "c/d.go:bar,baz"])
    cfg = AuthorConfig.from_namespace(ns)
    assert cfg.gut_targets == [
        GutTarget(rel_path="a/b.go", funcs=["foo"]),
        GutTarget(rel_path="c/d.go", funcs=["bar", "baz"]),
    ]


def test_from_namespace_out_dir_override(tmp_path: Path) -> None:
    ns = _base_ns(out_dir=str(tmp_path))
    cfg = AuthorConfig.from_namespace(ns)
    assert cfg.out_dir == tmp_path


def test_from_namespace_model_cutoff_str() -> None:
    from datetime import date

    ns = _base_ns(model_cutoff="2026-01-15")
    cfg = AuthorConfig.from_namespace(ns)
    assert cfg.model_cutoff == date(2026, 1, 15)


def test_invalid_task_id_hyphen() -> None:
    with pytest.raises(AuthorError):
        AuthorConfig.from_namespace(_base_ns(task_id="Bad-Task"))


def test_invalid_task_id_leading_digit() -> None:
    with pytest.raises(AuthorError):
        AuthorConfig.from_namespace(_base_ns(task_id="1task"))


def test_invalid_lang() -> None:
    with pytest.raises(AuthorError):
        AuthorConfig.from_namespace(_base_ns(lang="cobol"))


def test_missing_gut_targets() -> None:
    with pytest.raises(AuthorError):
        AuthorConfig.from_namespace(_base_ns(gut=[]))


def test_missing_gut_targets_none() -> None:
    with pytest.raises(AuthorError):
        AuthorConfig.from_namespace(_base_ns(gut=None))


def test_invalid_gut_spec_no_colon() -> None:
    with pytest.raises(AuthorError):
        AuthorConfig.from_namespace(_base_ns(gut=["nopath"]))


def test_invalid_gut_spec_empty_funcs() -> None:
    with pytest.raises(AuthorError):
        AuthorConfig.from_namespace(_base_ns(gut=["a/b.go:"]))


def test_invalid_gut_spec_empty_relpath() -> None:
    with pytest.raises(AuthorError):
        AuthorConfig.from_namespace(_base_ns(gut=[":foo,bar"]))
