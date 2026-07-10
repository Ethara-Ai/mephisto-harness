from __future__ import annotations

import pytest

from sforge.author.templates import (
    SCORE_SH_TEMPLATE,
    SETUP_JUDGE_SH_TEMPLATE,
    SETUP_WORKSPACE_SH_TEMPLATE,
    TASK_MD_TEMPLATE,
    render,
)


def test_task_md_renders() -> None:
    out = render(
        TASK_MD_TEMPLATE,
        task_id="goawk_x",
        name="GoAWK X",
        category="code_reconstruction",
        repo="https://github.com/benhoyt/goawk",
        commit="abc123",
        lang="go",
        gut_files="- `interp/functions.go` — funcs: parseFmtTypes, sprintf",
        cwd="/home/workspace/goawk",
        test_cmd="go test ./interp/",
        test_filter="printf|sprintf",
        extra_notes="",
    )
    assert "GoAWK X" in out
    assert "goawk_x" in out
    assert "code_reconstruction" in out
    assert "abc123" in out
    assert "interp/functions.go" in out
    assert "/home/workspace/goawk" in out
    assert "go test ./interp/" in out
    assert "printf|sprintf" in out
    assert "score = passed / total * 100" in out


def test_task_md_missing_kwarg_raises() -> None:
    with pytest.raises(KeyError):
        render(TASK_MD_TEMPLATE, task_id="x")


def test_setup_workspace_renders() -> None:
    out = render(
        SETUP_WORKSPACE_SH_TEMPLATE,
        repo="https://github.com/benhoyt/goawk",
        commit="4c907fb2838a4f819252cc3030e898eebf8a1c10",
        cwd="/home/workspace/goawk",
        prepared_files_bash="printf '%s' 'AA==' | base64 -d > /x",
        task_md="# hello\n",
    )
    assert "git clone https://github.com/benhoyt/goawk /tmp/src" in out
    assert "4c907fb2838a4f819252cc3030e898eebf8a1c10" in out
    assert "TASKMD_EOF" in out
    assert "git init -q" in out
    assert "git commit -q -m 'initial workspace (functions gutted)'" in out
    assert "base64 -d" in out


def test_setup_workspace_missing_kwarg_raises() -> None:
    with pytest.raises(KeyError):
        render(SETUP_WORKSPACE_SH_TEMPLATE, repo="r", commit="c", cwd="/x")


def test_setup_judge_renders() -> None:
    score_sh = "#!/bin/bash\necho hi\n"
    out = render(
        SETUP_JUDGE_SH_TEMPLATE,
        repo="https://github.com/benhoyt/goawk",
        commit="abc123",
        cwd="/home/workspace/goawk",
        cache_warm_cmd="go build ./...",
        score_sh=score_sh,
    )
    assert "git clone https://github.com/benhoyt/goawk /tmp/src" in out
    assert "SCORE_EOF" in out
    assert "chmod +x /tmp/score.sh" in out
    assert "go build ./..." in out
    assert score_sh in out


def test_setup_judge_missing_kwarg_raises() -> None:
    with pytest.raises(KeyError):
        render(SETUP_JUDGE_SH_TEMPLATE, repo="r", commit="c", cwd="/x")


def test_score_sh_renders() -> None:
    out = render(
        SCORE_SH_TEMPLATE,
        cwd="/home/workspace/goawk",
        build_cmd="go build ./...",
        test_cmd="go test -v ./interp/",
        test_filter="printf|sprintf",
        test_filter_pyrepr=repr("printf|sprintf"),
    )
    assert out.startswith("#!/bin/bash")
    assert "cd /home/workspace/goawk" in out
    assert "emit_zero() {" in out
    assert "emit_zero() {{" not in out
    assert "if ! go build ./... > /tmp/build.log 2>&1" in out
    assert "go test -v ./interp/ > /tmp/test.out" in out
    assert "filt = re.compile('printf|sprintf')" in out
    assert '>>>>> Start Structured Result' in out
    assert '>>>>> End Structured Result' in out
    assert '{"score": 0,' in out
    assert 'details.append({"name": name, "status": "FAIL"})' in out
    assert 'json.dumps({"score": score,' in out
    assert 'f"{passed}/{total} passed"' in out


def test_score_sh_missing_kwarg_raises() -> None:
    with pytest.raises(KeyError):
        render(SCORE_SH_TEMPLATE, cwd="/x", build_cmd="b", test_cmd="t")


def test_score_sh_extra_kwarg_silent() -> None:
    out = render(
        SCORE_SH_TEMPLATE,
        cwd="/x",
        build_cmd="b",
        test_cmd="t",
        test_filter="f",
        test_filter_pyrepr=repr("f"),
        unused_extra="ignored",
    )
    assert "ignored" not in out


def test_score_sh_python_body_is_syntactically_valid() -> None:
    out = render(
        SCORE_SH_TEMPLATE,
        cwd="/x",
        build_cmd="true",
        test_cmd="true",
        test_filter=".*",
        test_filter_pyrepr=repr(".*"),
    )
    start = out.index("<<'PYEOF'\n") + len("<<'PYEOF'\n")
    end = out.index("\nPYEOF", start)
    body = out[start:end]
    compile(body, "<embedded>", "exec")
