from __future__ import annotations

import base64
import json
from pathlib import Path

from sforge.author.config import AuthorConfig, GutTarget
from sforge.author.gutters.base import GutResult
from sforge.author.manifest import build_manifest
from sforge.harness.benchmark import BenchmarkMeta
from sforge.harness.task_spec import make_task_spec


GOAWK_COMMIT = "4c907fb2838a4f819252cc3030e898eebf8a1c10"


def _make_config() -> AuthorConfig:
    return AuthorConfig(
        task_id="goawk_printf_reimplementation_v2",
        name="GoAWK printf/sprintf reimplementation (regenerated)",
        category="code_reconstruction",
        repo="https://github.com/benhoyt/goawk",
        commit=GOAWK_COMMIT,
        base="go",
        lang="go",
        gut_targets=[
            GutTarget(rel_path="interp/functions.go", funcs=["parseFmtTypes", "sprintf"])
        ],
        cwd="/home/workspace/goawk",
        test_cmd=(
            "go test -count=1 -timeout=300s -v "
            "-run '^(TestInterp|TestCharsMode)$' ./interp/ -awk="
        ),
        test_filter="printf|sprintf",
        build_cmd="go build ./...",
        cache_warm_cmd=(
            "cd /home/workspace/goawk && go build ./... "
            "&& go test -run='^$' ./interp/"
        ),
    )


def _make_gut_results() -> list[GutResult]:
    return [
        GutResult(
            gutted_source="package interp\n\n// gutted\n",
            functions=[],
            total_loc_gutted=110,
        )
    ]


def test_manifest_matches_goawk_shape() -> None:
    manifest = build_manifest(_make_config(), _make_gut_results())

    assert set(manifest.keys()) == {
        "task_id",
        "name",
        "category",
        "base_image",
        "platform",
        "internet",
        "cwd",
        "submit_paths",
        "submit_exclude",
        "work",
        "judge",
    }

    assert manifest["task_id"] == "goawk_printf_reimplementation_v2"
    assert manifest["base_image"] == "go"
    assert manifest["platform"] == "linux/amd64"
    assert manifest["internet"] is False
    assert manifest["cwd"] == "/home/workspace/goawk"
    assert manifest["submit_paths"] == ["interp/functions.go"]
    assert manifest["submit_exclude"] == []

    work = manifest["work"]
    assert set(work.keys()) == {"setup_cmds", "specs_dir", "agent_query"}
    assert work["specs_dir"] == "/home/workspace/goawk"
    assert isinstance(work["setup_cmds"], list) and len(work["setup_cmds"]) == 1
    assert "TASK.md" in work["agent_query"]

    judge = manifest["judge"]
    assert set(judge.keys()) == {
        "setup_cmds",
        "eval_cmd",
        "eval_timeout",
        "parser",
        "score_direction",
        "selection",
        "rescale",
    }
    assert judge["eval_cmd"] == "bash /tmp/score.sh"
    assert judge["eval_timeout"] == 600
    assert judge["parser"] == "structured_json"
    assert judge["score_direction"] == "maximize"
    assert judge["selection"] == "score_first"
    assert judge["rescale"] == {"kind": "linear", "lower": 0, "upper": 100}
    assert isinstance(judge["setup_cmds"], list) and len(judge["setup_cmds"]) == 1


def test_manifest_setup_scripts_contain_expected_markers() -> None:
    manifest = build_manifest(_make_config(), _make_gut_results())

    work_script = manifest["work"]["setup_cmds"][0]
    assert GOAWK_COMMIT in work_script
    assert "git clone https://github.com/benhoyt/goawk /tmp/src" in work_script
    assert "TASKMD_EOF" in work_script
    assert "base64 -d" in work_script
    assert "git init" in work_script
    assert "git commit" in work_script

    judge_script = manifest["judge"]["setup_cmds"][0]
    assert GOAWK_COMMIT in judge_script
    assert "git clone https://github.com/benhoyt/goawk /tmp/src" in judge_script
    assert "SCORE_EOF" in judge_script
    assert "chmod +x /tmp/score.sh" in judge_script


def test_manifest_embeds_gutted_source_as_base64() -> None:
    cfg = _make_config()
    gutted_source = "package interp\n\n// gutted body\n"
    results = [GutResult(gutted_source=gutted_source, functions=[], total_loc_gutted=42)]
    manifest = build_manifest(cfg, results)

    expected_b64 = base64.b64encode(gutted_source.encode()).decode()
    work_script = manifest["work"]["setup_cmds"][0]
    assert expected_b64 in work_script
    assert "/home/workspace/goawk/interp/functions.go" in work_script


def test_manifest_loads_via_task_spec(tmp_path: Path) -> None:
    manifest = build_manifest(_make_config(), _make_gut_results())
    task_path = tmp_path / "goawk_test.json"
    task_path.write_text(json.dumps(manifest, indent=2))

    benchmark = BenchmarkMeta(
        name="edgebench-test",
        base_images={"go": {"official_image": "golang:1.22", "extra_packages": ["git"]}},
    )
    spec = make_task_spec(task_path, benchmark)

    assert spec.judge.eval_cmd == "bash /tmp/score.sh"
    assert spec.judge.parser == "structured_json"
    assert spec.judge.score_direction == "maximize"
    assert spec.judge.selection == "score_first"
    assert spec.judge.eval_timeout == 600
    assert spec.base_image == "go"
    assert spec.platform == "linux/amd64"
    assert spec.submit_paths == ["interp/functions.go"]
    assert spec.internet is False
    assert spec.work.setup_cmds is not None
    assert spec.judge.setup_cmds is not None


def test_manifest_top_level_shape_matches_reference() -> None:
    reference_path = Path(__file__).resolve().parents[2] / "tasks" / "goawk_printf_reimplementation.json"
    reference = json.loads(reference_path.read_text())

    manifest = build_manifest(_make_config(), _make_gut_results())

    assert set(manifest.keys()) == set(reference.keys())
    assert set(manifest["work"].keys()) == set(reference["work"].keys())
    assert set(manifest["judge"].keys()) == set(reference["judge"].keys())

    for key in ("base_image", "platform", "internet", "submit_exclude"):
        assert type(manifest[key]) is type(reference[key])
    assert type(manifest["submit_paths"]) is type(reference["submit_paths"])

    assert manifest["judge"]["parser"] == reference["judge"]["parser"]
    assert manifest["judge"]["score_direction"] == reference["judge"]["score_direction"]
    assert manifest["judge"]["rescale"] == reference["judge"]["rescale"]


def test_manifest_multiple_gut_targets() -> None:
    cfg = AuthorConfig(
        task_id="multi",
        name="Multi",
        category="code_reconstruction",
        repo="https://example.com/repo",
        commit="deadbeef",
        base="go",
        lang="go",
        gut_targets=[
            GutTarget(rel_path="a/x.go", funcs=["foo"]),
            GutTarget(rel_path="b/y.go", funcs=["bar", "baz"]),
        ],
        cwd="/w",
        test_cmd="go test ./...",
        test_filter=".*",
        build_cmd="go build ./...",
    )
    results = [
        GutResult(gutted_source="package a\n", functions=[], total_loc_gutted=1),
        GutResult(gutted_source="package b\n", functions=[], total_loc_gutted=1),
    ]
    manifest = build_manifest(cfg, results)
    assert manifest["submit_paths"] == ["a/x.go", "b/y.go"]
    work_script = manifest["work"]["setup_cmds"][0]
    assert "/w/a/x.go" in work_script
    assert "/w/b/y.go" in work_script
