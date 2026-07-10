from __future__ import annotations

import base64
import shlex

from sforge.author.config import AuthorConfig
from sforge.author.gutters.base import GutResult
from sforge.author.templates import (
    SCORE_SH_TEMPLATE,
    SETUP_JUDGE_SH_TEMPLATE,
    SETUP_WORKSPACE_SH_TEMPLATE,
    TASK_MD_TEMPLATE,
    render,
)


def _build_gut_files_bullets(config: AuthorConfig) -> str:
    lines = []
    for target in config.gut_targets:
        funcs = ", ".join(target.funcs)
        lines.append(f"- `{target.rel_path}` — funcs: {funcs}")
    return "\n".join(lines)


_OVERLAY_MARKERS: dict[str, str] = {
    "go": "TODO(agent)",
    "python": "NotImplementedError",
}


def _build_prepared_files_bash(config: AuthorConfig, gut_results: list[GutResult]) -> str:
    marker = _OVERLAY_MARKERS.get(config.lang, "TODO(agent)")
    marker_q = shlex.quote(marker)
    lines = []
    for target, result in zip(config.gut_targets, gut_results):
        src = result.gutted_source
        raw = src.encode() if isinstance(src, str) else src
        b64 = base64.b64encode(raw).decode()
        path = f"{config.cwd}/{target.rel_path}"
        q = shlex.quote(path)
        lines.append(f"mkdir -p \"$(dirname {q})\"")
        lines.append(f"printf '%s' '{b64}' | base64 -d > {q}")
        size = len(raw)
        lines.append(f"grep -q {marker_q} {q} || {{ echo 'overlay verification failed: {target.rel_path}' >&2; exit 1; }}")
        lines.append(f"[ \"$(wc -c < {q})\" -eq {size} ] || {{ echo 'overlay size mismatch: {target.rel_path}' >&2; exit 1; }}")
    return "\n".join(lines)


def build_manifest(config: AuthorConfig, gut_results: list[GutResult]) -> dict:
    gut_files = _build_gut_files_bullets(config)
    task_md = render(
        TASK_MD_TEMPLATE,
        task_id=config.task_id,
        name=config.name,
        category=config.category,
        repo=config.repo,
        commit=config.commit,
        lang=config.lang,
        gut_files=gut_files,
        cwd=config.cwd,
        test_cmd=config.test_cmd,
        test_filter=config.test_filter,
        extra_notes=config.extra_notes,
    )

    prepared_files_bash = _build_prepared_files_bash(config, gut_results)
    setup_workspace = render(
        SETUP_WORKSPACE_SH_TEMPLATE,
        repo=config.repo,
        commit=config.commit,
        cwd=config.cwd,
        prepared_files_bash=prepared_files_bash,
        task_md=task_md,
    )

    build_cmd = config.build_cmd or "true"
    score_sh = render(
        SCORE_SH_TEMPLATE,
        cwd=config.cwd,
        build_cmd=build_cmd,
        test_cmd=config.test_cmd,
        test_filter=config.test_filter,
        test_filter_pyrepr=repr(config.test_filter),
    )

    cache_warm_cmd = config.cache_warm_cmd or "true"
    setup_judge = render(
        SETUP_JUDGE_SH_TEMPLATE,
        repo=config.repo,
        commit=config.commit,
        cwd=config.cwd,
        cache_warm_cmd=cache_warm_cmd,
        score_sh=score_sh,
    )

    return {
        "task_id": config.task_id,
        "name": config.name,
        "category": config.category,
        "base_image": config.base,
        "platform": "linux/amd64",
        "internet": config.internet,
        "cwd": config.cwd,
        "submit_paths": [t.rel_path for t in config.gut_targets],
        "submit_exclude": [],
        "work": {
            "setup_cmds": [setup_workspace],
            "specs_dir": config.cwd,
            "agent_query": "Read `TASK.md` in the working directory for the full specification and grading formula.",
        },
        "judge": {
            "setup_cmds": [setup_judge],
            "eval_cmd": "bash /tmp/score.sh",
            "eval_timeout": config.eval_timeout,
            "parser": "structured_json",
            "score_direction": "maximize",
            "selection": "score_first",
            "rescale": {"kind": "linear", "lower": 0, "upper": 100},
        },
    }
