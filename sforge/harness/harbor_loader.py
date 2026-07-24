from __future__ import annotations

import base64
import hashlib
from pathlib import Path
from typing import Any

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib  # type: ignore[import-not-found, no-redef]

from sforge.harness.benchmark import BenchmarkMeta
from sforge.harness.score_rescale import parse_rescale_spec
from sforge.harness.task_spec import JudgeSpec, TaskSpec, WorkSpec


_NETWORK_MODE_TO_INTERNET = {
    "public": True,
    "allowlist": True,
    "no-network": False,
    "none": False,
}


def _digest12(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()[:12]


def _parse_memory_mb(mb: Any) -> str | None:
    if mb is None:
        return None
    try:
        return f"{int(mb)}m"
    except (TypeError, ValueError):
        return None


def _build_eval_cmd(test_sh_source: str, cwd: str) -> str:
    # Must satisfy BOTH contracts: Harbor's reward.txt AND SForge's structured_json (JSON on stdout).
    encoded = base64.b64encode(test_sh_source.encode()).decode()
    return (
        f"cd {cwd} && "
        f"mkdir -p /logs/verifier && "
        f"echo {encoded} | base64 -d > /tmp/harbor_test.sh && "
        f"chmod +x /tmp/harbor_test.sh && "
        f"bash /tmp/harbor_test.sh; "
        f"SCORE=$(cat /logs/verifier/reward.txt 2>/dev/null | tr -d '[:space:]' || echo 0); "
        f'echo "{{\\"score\\": ${{SCORE:-0}}}}"'
    )


def _strip_org(name: str) -> str:
    return name.split("/", 1)[1] if "/" in name else name


def load_harbor_task(task_dir: Path, benchmark: BenchmarkMeta) -> TaskSpec:
    task_dir = task_dir.resolve()
    toml_path = task_dir / "task.toml"
    if not toml_path.exists():
        raise FileNotFoundError(f"No task.toml in {task_dir}")

    with open(toml_path, "rb") as f:
        cfg = tomllib.load(f)

    task_block: dict = cfg.get("task", {})
    env_block: dict = cfg.get("environment", {})
    verifier_block: dict = cfg.get("verifier", {})
    verifier_env: dict = verifier_block.get("environment", {})
    agent_block: dict = cfg.get("agent", {})
    ext: dict = cfg.get("extensions", {}).get("sforge", {})

    task_name = task_block.get("name") or task_dir.name
    task_id = ext.get("task_id") or _strip_org(task_name)

    base_image_key = ext.get("base_image")
    if not base_image_key:
        raise ValueError(
            f"Harbor task '{task_id}' missing [extensions.sforge].base_image; "
            f"SForge needs a base_image key that resolves in BENCHMARK.yaml."
        )
    base_image_spec = benchmark.base_images.get(base_image_key)
    if base_image_spec is None:
        raise ValueError(
            f"Harbor task '{task_id}' base_image '{base_image_key}' not in "
            f"BENCHMARK.yaml. Available: {list(benchmark.base_images.keys())}"
        )

    instruction_path = task_dir / "instruction.md"
    if not instruction_path.exists():
        raise FileNotFoundError(
            f"Harbor task '{task_id}' missing instruction.md at {instruction_path}"
        )
    agent_query = instruction_path.read_text().strip()

    tests_path = task_dir / "tests" / "test.sh"
    if not tests_path.exists():
        raise FileNotFoundError(
            f"Harbor task '{task_id}' missing tests/test.sh at {tests_path}"
        )
    test_sh_source = tests_path.read_text()

    cwd = env_block.get("workdir") or ext.get("cwd") or "/workspace"
    platform = ext.get("platform", "linux/amd64")
    internet = _NETWORK_MODE_TO_INTERNET.get(
        env_block.get("network_mode", "public"), True
    )

    work_image_tag = ext.get("work_image_tag")
    if not work_image_tag:
        work_docker = env_block.get("docker_image")
        if not work_docker:
            raise ValueError(
                f"Harbor task '{task_id}': need either "
                f"[environment].docker_image or [extensions.sforge].work_image_tag."
            )
        work_image_tag = _digest12(f"harbor:work:{work_docker}")

    judge_image_tag = ext.get("judge_image_tag")
    if not judge_image_tag:
        judge_docker = verifier_env.get("docker_image") or env_block.get("docker_image")
        if not judge_docker:
            raise ValueError(
                f"Harbor task '{task_id}': need either "
                f"[verifier.environment].docker_image or "
                f"[extensions.sforge].judge_image_tag."
            )
        judge_image_tag = _digest12(f"harbor:judge:{judge_docker}")

    work = WorkSpec(
        specs_dir=cwd,
        agent_query=agent_query,
        setup_cmds=None,
        image_tag=work_image_tag,
        cpu_limit=env_block.get("cpus"),
        mem_limit=_parse_memory_mb(env_block.get("memory_mb")),
    )

    judge_env_for_limits = verifier_env or env_block
    judge = JudgeSpec(
        eval_cmd=_build_eval_cmd(test_sh_source, cwd),
        eval_timeout=int(verifier_block.get("timeout_sec", 600)),
        parser=ext.get("parser", "structured_json"),
        setup_cmds=None,
        image_tag=judge_image_tag,
        game_server_cmd=ext.get("game_server_cmd"),
        score_direction=ext.get("score_direction", "maximize"),
        selection=ext.get("selection", "pass_rate_first"),
        rescale=parse_rescale_spec(ext.get("rescale")),
        cpu_limit=judge_env_for_limits.get("cpus"),
        mem_limit=_parse_memory_mb(judge_env_for_limits.get("memory_mb")),
    )

    submit_paths = ext.get("submit_paths")
    if submit_paths is None:
        raise ValueError(
            f"Harbor task '{task_id}': [extensions.sforge].submit_paths is required "
            f"(SForge needs to know what the agent submits)."
        )
    submit_exclude = [
        e.rstrip("/") for e in ext.get("submit_exclude", ["tests/"])
    ]

    task_spec = TaskSpec(
        task_id=task_id,
        name=task_block.get("description") or task_name,
        base_image=base_image_key,
        platform=platform,
        cwd=cwd,
        submit_paths=list(submit_paths),
        submit_exclude=submit_exclude,
        work=work,
        judge=judge,
        benchmark_name=benchmark.name,
        base_image_spec=base_image_spec,
        game_mode=bool(ext.get("game_mode", False)),
        internet=internet,
        publish_platforms=ext.get("publish_platforms"),
    )

    return task_spec
