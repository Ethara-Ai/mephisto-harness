# Copyright (c) 2026 ByteDance Ltd. and/or its affiliates
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Agent execution with iterative evaluation via judge server.

The agent runs in a work container with:
- sforge-submit script for on-demand evaluation
- Stop hook to prevent premature exit (unconditional block)
- Auto-eval runs on the host side (invisible to agent)

Architecture:
    Host: sforge serve (judge HTTP server, started separately)
          + auto-eval thread (extracts code from container, submits to judge)
    Container: Agent + sforge-submit (curl-based)
    Communication: HTTP (container → host judge server)
"""

from __future__ import annotations

import io
import json
import signal
import shlex
import tarfile as _tarfile
import threading
import time
import traceback
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from urllib.parse import urlparse

import requests

from sforge.harness.agent import Agent
from sforge.harness.backend import ContainerBackend, ContainerHandle
from sforge.harness.config import SForgeConfig
from sforge.harness.constants import ADMIN_SECRET
from sforge.harness.docker_build import (
    close_logger,
    setup_logger,
)
from sforge.harness.evolve_scripts import (
    generate_evolve_prompt,
    generate_game_prompt,
    generate_submit_script,
)
from sforge.harness.task_spec import TaskSpec


@dataclass
class RunResult:
    """Result of running an agent on a task."""

    archive: bytes = b""
    best_pass_rate: float = 0.0
    best_score: float | None = None
    best_round: str = ""
    total_rounds: int = 0
    agent_submissions: int = 0
    auto_submissions: int = 0
    agent_output: str = ""
    timed_out: bool = False
    runtime_seconds: float = 0.0
    resume_count: int = 0

    def to_dict(self) -> dict:
        d = {
            "best_pass_rate": self.best_pass_rate,
            "best_round": self.best_round,
            "total_rounds": self.total_rounds,
            "agent_submissions": self.agent_submissions,
            "auto_submissions": self.auto_submissions,
            "timed_out": self.timed_out,
            "runtime_seconds": self.runtime_seconds,
            "archive_size_bytes": len(self.archive),
            "resume_count": self.resume_count,
        }
        if self.best_score is not None:
            d["best_score"] = self.best_score
        return d


# ---------------------------------------------------------------------------
# Environment and command helpers
# ---------------------------------------------------------------------------


def _build_agent_env(
    agent: Agent,
    model: str | None = None,
) -> dict[str, str]:
    """Build environment variables dict for an agent container."""
    config = agent._config
    env: dict[str, str] = {}

    if config.http_proxy:
        env["http_proxy"] = config.http_proxy
        env["HTTP_PROXY"] = config.http_proxy
    if config.https_proxy:
        env["https_proxy"] = config.https_proxy
        env["HTTPS_PROXY"] = config.https_proxy
    if config.no_proxy:
        env["no_proxy"] = config.no_proxy
        env["NO_PROXY"] = config.no_proxy

    if config.agent_api_key:
        env[agent.api_key_env] = config.agent_api_key

    if config.agent_api_base_url and agent.api_base_env:
        env[agent.api_base_env] = config.agent_api_base_url

    effective_model = model or config.agent_model or agent.default_model
    if effective_model and agent.model_env:
        env[agent.model_env] = effective_model

    if config.nodejs_mirror_url:
        env["SFORGE_NODEJS_MIRROR_URL"] = config.nodejs_mirror_url
    if config.npm_registry_url:
        env["npm_config_registry"] = config.npm_registry_url

    env.update(config.agent_extra_env)

    agent.augment_env(env, model)

    return env


# ---------------------------------------------------------------------------
# Container setup helpers
# ---------------------------------------------------------------------------


def _install_tools(
    backend: ContainerBackend,
    handle: ContainerHandle,
    task_spec: TaskSpec,
    agent: Agent,
    log_dir: Path,
    logger,
    disable_stop_hook: bool = False,
) -> None:
    """Install sforge-submit and agent stop hooks."""

    # 1. Install sforge-submit script
    submit_script = generate_submit_script()
    local_submit = log_dir / "_sforge-submit.sh"
    local_submit.write_text(submit_script)
    backend.copy_to_container(
        handle, local_submit, PurePosixPath("/usr/local/bin/sforge-submit")
    )
    backend.exec_run(handle, "chmod a+x /usr/local/bin/sforge-submit", user="root")
    logger.info("Installed sforge-submit script")

    # 2. Install agent-specific stop hook (unless disabled)
    if not disable_stop_hook:
        agent.install_stop_hook(backend, handle, log_dir, logger)
    else:
        logger.info("Stop hook disabled by flag")


def _extract_archive_from_container(
    backend: ContainerBackend,
    handle: ContainerHandle,
    task_spec: TaskSpec,
) -> bytes:
    """Extract the current submission archive from a running work container."""
    patch_dir = task_spec.cwd
    submit_paths = " ".join(task_spec.submit_paths)
    excludes = " ".join(f"--exclude={e}" for e in task_spec.submit_exclude)
    tar_cmd = (
        f"cd {patch_dir} && tar czf /tmp/final.tar.gz "
        f"--exclude=.git {excludes} {submit_paths}"
    )
    backend.exec_run(handle, ["/bin/bash", "-c", tar_cmd])
    raw = backend.copy_from_container(handle, PurePosixPath("/tmp/final.tar.gz"))
    outer = _tarfile.open(fileobj=io.BytesIO(raw))
    member = outer.getmembers()[0]
    archive = outer.extractfile(member).read()
    outer.close()
    return archive


def _text_has_cap_signal(text: str) -> bool:
    """Cheap check: does the agent output tail look like a rate-limit / cap?

    Used ONLY as a fallback when the bridge's /healthz probe is unreachable,
    so we can still choose a conservative pause over a hard failure. Kept
    deliberately simple (substring match on unambiguous slugs/status).
    """
    if not text:
        return False
    low = text.lower()
    return (
        "rate_limit_error" in low
        or "too many requests" in low
        or "resource_exhausted" in low
        or "accounts exhausted" in low
        or "credentials_unavailable" in low
        or " 429" in low
    )


def _bridge_pool_status(api_base_url, logger):
    """Query the OAuth bridge /healthz for (reset_at, pool_size).

    ``reset_at`` is the Unix time the soonest exhausted account becomes
    available (None if any account is available now or there is no pool).
    ``pool_size`` is the number of pooled accounts (0 for single-account /
    no bridge). Best-effort: any error yields (None, 0).
    """
    if not api_base_url:
        return (None, 0)
    base = api_base_url.rstrip("/")
    if base.endswith("/v1"):
        base = base[: -len("/v1")]
    try:
        resp = requests.get(f"{base}/healthz", timeout=10)
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:  # noqa: BLE001 — best-effort probe
        if logger:
            logger.debug(f"bridge /healthz probe failed: {exc}")
        return (None, 0)
    reset = data.get("next_reset_at_unix")
    reset_at = float(reset) if isinstance(reset, (int, float)) and reset > 0 else None
    accounts = data.get("accounts") or []
    pool_size = len(accounts) if isinstance(accounts, list) else 0
    return (reset_at, pool_size)


# --- Resume / recovery tuning (module-level: config, not per-run state) ---
MIN_RUNTIME_FOR_RESUME = 1      # a segment shorter than this is a "quick crash"
MAX_RESUMES = 100              # hard global ceiling on agent resumes
MAX_POOL_PAUSE = 6 * 3600      # never wait more than 6h for one pool reset
MIN_POOL_PAUSES = 3            # min pool-pause cycles (scales up to pool size)
BRIDGE_DOWN_PAUSE = 300        # conservative sleep when the bridge is unreachable


def _auto_eval_loop(
    backend: ContainerBackend,
    handle: ContainerHandle,
    task_spec: TaskSpec,
    host_judge_url: str,
    session_token: str,
    eval_interval: int,
    stop_event: threading.Event,
    logger,
    log_dir: Path,
) -> None:
    """Host-side auto-eval: periodically extract code and submit to judge.

    Runs as a daemon thread. Fire-and-forget — does not poll for results.
    Writes tick entries to auto_eval_ticks.log for post-mortem inspection.
    """
    ticks_log = log_dir / "auto_eval_ticks.log"
    while True:
        stop_event.wait(eval_interval)
        if stop_event.is_set():
            break
        try:
            archive = _extract_archive_from_container(backend, handle, task_spec)
            resp = requests.post(
                f"{host_judge_url}/api/v1/submit",
                data={
                    "token": session_token,
                    "kind": "auto",
                    "admin_secret": ADMIN_SECRET,
                },
                files={"archive": ("archive.tar.gz", archive, "application/gzip")},
                timeout=120,
            )
            resp.raise_for_status()
            data = resp.json()
            ts = time.strftime("%Y-%m-%dT%H:%M:%S")
            with open(ticks_log, "a") as f:
                f.write(
                    f"[{ts}] submitted {len(archive)} bytes -> {data.get('submission_id', '?')} round={data.get('round_id', '?')}\n"
                )
        except Exception as e:
            ts = time.strftime("%Y-%m-%dT%H:%M:%S")
            try:
                with open(ticks_log, "a") as f:
                    f.write(f"[{ts}] error: {e}\n")
            except Exception:
                pass
            logger.debug("Auto-eval tick failed: %s", e)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def run_agent(
    task_spec: TaskSpec,
    agent: Agent,
    config: SForgeConfig,
    backend: ContainerBackend,
    run_id: str,
    model: str | None = None,
    timeout: int | None = None,
    judge_url: str = "http://host.docker.internal:8080",
    eval_interval: int = 300,
    disable_stop_hook: bool = False,
    disable_auto_eval: bool = False,
    disable_auto_resume: bool = False,
    internet: bool = True,
    verbose: bool = False,
    shutdown_event: threading.Event | None = None,
    max_submissions: int | None = None,
    submission_cooldown: int | None = None,
) -> RunResult:
    """Run an agent on a task with iterative evaluation.

    Requires a running judge server (started via `sforge serve`).

    1. Build work + judge images
    2. Create work container (with judge URL in env)
    3. Install agent + tools (submit script, stop hook, auto-eval daemon)
    4. Run agent (high max-turns for iterative work)
    5. Read final state, extract archive
    """
    effective_timeout = timeout or config.agent_timeout or agent.timeout

    log_dir = config.log_dir / "runs" / run_id / task_spec.task_id
    log_dir.mkdir(parents=True, exist_ok=True)
    logger = setup_logger(
        f"agent.{task_spec.task_id}.{run_id}",
        log_dir / "run_agent.log",
        verbose=verbose,
    )

    # judge_url is for container use; derive a host-local URL for registration/polling
    parsed_judge = urlparse(judge_url)
    if parsed_judge.hostname == "host.docker.internal":
        host_judge_url = judge_url.replace("host.docker.internal", "127.0.0.1")
    elif backend.backend_name == "k8s":
        # judge_url points to VPC IP (for pods); host talks to judge server locally
        host_judge_url = f"http://127.0.0.1:{parsed_judge.port or 8080}"
    else:
        host_judge_url = judge_url

    handle = None
    net_isolation = None
    api_proxy = None
    relay_name = None
    install_parts: list[str] = []

    try:
        # 0. Clean up stale iptables chains from previous runs that were killed
        if backend.backend_name == "docker":
            from sforge.harness.network_isolation import cleanup_stale_chains

            cleanup_stale_chains(logger)

        # 1. Check images exist (must run `sforge build` first)
        for image_key in (task_spec.work_image_key, task_spec.judge_image_key):
            if not backend.image_exists(image_key):
                raise RuntimeError(
                    f"Image '{image_key}' not found. Run `sforge pull --task {task_spec.task_id}` to fetch from registry, or `sforge build --task {task_spec.task_id}` to build locally."
                )
        logger.info("Images ready")

        # 1b. Register session with judge server
        reg_body: dict = {
            "task_id": task_spec.task_id,
            "run_id": run_id,
            "admin_secret": ADMIN_SECRET,
        }
        if config.judge_cpu_limit is not None:
            reg_body["judge_cpu_limit"] = config.judge_cpu_limit
        if config.judge_mem_limit is not None:
            reg_body["judge_mem_limit"] = config.judge_mem_limit
        if max_submissions is not None:
            reg_body["max_agent_submissions"] = max_submissions
        if submission_cooldown is not None:
            reg_body["submission_cooldown"] = submission_cooldown
        if backend.backend_name != "docker":
            reg_body["backend"] = backend.backend_name
            reg_body["k8s_image_registry"] = config.k8s_image_registry
            reg_body["k8s_namespace"] = config.k8s_namespace
            if config.k8s_node_selector:
                reg_body["k8s_node_selector"] = config.k8s_node_selector
            if config.k8s_kubeconfig:
                reg_body["k8s_kubeconfig"] = config.k8s_kubeconfig
        for _reg_attempt in range(1, 6):
            try:
                reg_resp = requests.post(
                    f"{host_judge_url}/api/v1/register",
                    json=reg_body,
                    timeout=10,
                )
                reg_resp.raise_for_status()
                break
            except (
                requests.ConnectionError,
                requests.Timeout,
                requests.HTTPError,
            ) as exc:
                if _reg_attempt == 5:
                    raise
                wait = 2 * _reg_attempt
                logger.warning(
                    "Register attempt %d/5 failed (%s), retrying in %ds...",
                    _reg_attempt,
                    exc,
                    wait,
                )
                time.sleep(wait)
        session_token = reg_resp.json()["token"]
        logger.info("Registered session with judge server")

        # 2. Create container
        container_name = f"sforge.run.{task_spec.task_id}.{run_id}"

        backend.remove_container_by_name(container_name)

        env = _build_agent_env(agent, model)
        env["SFORGE_JUDGE_URL"] = judge_url
        env["SFORGE_TOKEN"] = session_token
        env["SFORGE_PATCH_DIR"] = task_spec.cwd
        env["SFORGE_SUBMIT_PATHS"] = " ".join(task_spec.submit_paths)
        env["SFORGE_SUBMIT_EXCLUDE_FLAGS"] = " ".join(
            f"--exclude={e}" for e in task_spec.submit_exclude
        )

        if task_spec.game_mode:
            game_api_base = (
                judge_url.rstrip("/") + f"/api/v1/game/{run_id}/{task_spec.task_id}"
            )
            env["GAME_SERVER_URL"] = game_api_base

        # Ensure judge server URL bypasses proxy
        judge_host = urlparse(judge_url).hostname or ""
        for key in ("NO_PROXY", "no_proxy"):
            existing = env.get(key, "")
            if judge_host and judge_host not in existing:
                env[key] = f"{existing},{judge_host}" if existing else judge_host

        # Network isolation: preflight + extra_hosts pre-resolve
        container_extra_hosts = {"host.docker.internal": "host-gateway"}
        container_cap_drop: list[str] = []

        use_relay = False
        if not internet:
            from sforge.harness.network_isolation import (
                check_iptables_permission,
                is_ip_address,
                resolve_hostname,
            )

            if config.http_proxy or config.https_proxy:
                raise RuntimeError(
                    "Network isolation (internet=false) is not compatible with "
                    "direct proxy configuration. Start a local API proxy first:\n"
                    "  python -m sforge proxy --target <YOUR_API_URL>\n"
                    "Then set SFORGE_AGENT_API_BASE_URL="
                    "http://host.docker.internal:9090 "
                    "and unset HTTP_PROXY/HTTPS_PROXY before running."
                )
            use_relay = not check_iptables_permission()

            if not use_relay:
                # Linux host with iptables: original path, unchanged.
                api_url = config.agent_api_base_url or agent.default_api_base_url
                if api_url:
                    api_host = urlparse(api_url).hostname or ""
                    if (
                        api_host
                        and api_host != "host.docker.internal"
                        and not is_ip_address(api_host)
                    ):
                        resolved_ips = resolve_hostname(api_host, logger)
                        if resolved_ips:
                            container_extra_hosts[api_host] = resolved_ips[0]
                container_cap_drop = ["NET_RAW"]
                logger.info("Network isolation enabled: iptables preflight passed")
            else:
                # Docker Desktop (macOS): no host iptables. Use an internal
                # Docker network + dual-homed relay instead (see isolated_network).
                logger.info(
                    "Network isolation: iptables unavailable, using Docker "
                    "relay (macOS/Docker Desktop)"
                )

        cpu = (
            config.work_cpu_limit
            if config.work_cpu_limit is not None
            else task_spec.work.cpu_limit
        )
        mem = (
            config.work_mem_limit
            if config.work_mem_limit is not None
            else task_spec.work.mem_limit
        )

        # macOS relay isolation: stand up the internal network + relay BEFORE
        # the work container, and point the agent's API base + judge URL at the
        # relay IP. The relay forwards :9090 (proxy/oauth bridge) and :8080
        # (judge) to the host. Container installs on the bridge (with internet),
        # then cuts over to the internal net after install.
        if not internet and use_relay:
            import docker as _docker

            from sforge.harness.isolated_network import (
                RELAY_IP,
                ensure_isolated_network,
                relay_base_urls,
                start_relay,
                wait_for_relay,
            )

            relay_client = _docker.from_env()
            ensure_isolated_network(relay_client)
            relay_name = start_relay(relay_client, run_id, logger)
            wait_for_relay(relay_client, relay_name, logger)
            relay_proxy_url, relay_judge_url = relay_base_urls()
            judge_url = relay_judge_url
            env["SFORGE_JUDGE_URL"] = relay_judge_url
            if agent.api_base_env:
                env[agent.api_base_env] = relay_proxy_url
            logger.info(
                "Isolated-mode (Docker Desktop) enabled: install with internet, "
                "then cut over to internal net; endpoints via relay %s",
                RELAY_IP,
            )

        handle = backend.create_container(
            task_spec.work_image_key,
            container_name,
            environment=env,
            extra_hosts=container_extra_hosts,
            cap_drop=container_cap_drop or None,
            cpu_limit=cpu,
            mem_limit=mem,
            platform=task_spec.platform,
        )
        backend.start_container(handle)
        logger.info(f"Container started: {container_name} (judge_url={judge_url})")

        # 3. Install agent runtime
        for i, cmd in enumerate(agent.install_cmds):
            logger.info(f"Install step {i + 1}/{len(agent.install_cmds)}: {cmd}")
            result = backend.exec_run_with_exit_code(
                handle, f"/bin/bash -c {shlex.quote(cmd)}", timeout=600
            )
            install_parts.append(result.output)
            if result.timed_out:
                raise RuntimeError(f"Install command timed out: {cmd}")
            if result.exit_code != 0:
                raise RuntimeError(
                    f"Install command failed (exit {result.exit_code}): {cmd}\n{result.output}"
                )
            logger.info(f"Install step {i + 1} done ({result.elapsed_seconds:.1f}s)")

        (log_dir / "install_output.txt").write_text("\n".join(install_parts))
        logger.info("Agent installation complete")

        # 4. Install tools.
        #    Game-mode tasks skip sforge-submit (scoring is built into the
        #    game HTTP API and there is no archive to submit), but still need
        #    the stop hook — otherwise the agent exits naturally as soon as
        #    the model decides it's "done", losing the full timeout budget.
        effective_eval_interval = 0 if disable_auto_eval else eval_interval
        auto_eval_stop = None
        if not task_spec.game_mode:
            _install_tools(
                backend,
                handle,
                task_spec,
                agent,
                log_dir,
                logger,
                disable_stop_hook=disable_stop_hook,
            )

            # Start host-side auto-eval thread (if enabled)
            if effective_eval_interval > 0:
                auto_eval_stop = threading.Event()
                auto_eval_thread = threading.Thread(
                    target=_auto_eval_loop,
                    args=(
                        backend,
                        handle,
                        task_spec,
                        host_judge_url,
                        session_token,
                        effective_eval_interval,
                        auto_eval_stop,
                        logger,
                        log_dir,
                    ),
                    daemon=True,
                )
                auto_eval_thread.start()
                logger.info(
                    f"Host-side auto-eval started (interval={effective_eval_interval}s)"
                )
        elif not disable_stop_hook:
            agent.install_stop_hook(backend, handle, log_dir, logger)

        # 4a2. macOS relay: cut the work container over to the internal net now
        # that install (which needed internet) is done. Internet egress is
        # severed here; the relay keeps proxy + judge reachable.
        if not internet and use_relay:
            import docker as _docker

            from sforge.harness.isolated_network import cut_over_to_isolated

            cut_over_to_isolated(_docker.from_env(), container_name, logger)

        # 4b. Apply network isolation (after install + tools, before agent)
        if not internet and not use_relay:
            from sforge.harness.network_isolation import (
                AllowedEndpoint,
                build_allowed_endpoints,
            )

            gateway_ip = backend.get_container_gateway_ip(handle) or ""
            if not gateway_ip and backend.backend_name == "docker":
                raise RuntimeError("Cannot determine gateway IP for network isolation")

            effective_api_url = config.agent_api_base_url or agent.default_api_base_url
            endpoints = build_allowed_endpoints(
                judge_url,
                effective_api_url,
                gateway_ip,
                logger,
            )
            net_isolation = backend.create_network_isolation(handle, endpoints, logger)
            net_isolation.apply()

        # 5. Write prompt
        if task_spec.game_mode:
            prompt = generate_game_prompt(task_spec.work.agent_query, internet=internet)
        else:
            prompt = generate_evolve_prompt(
                task_spec.work.agent_query,
                submit_paths=task_spec.submit_paths,
                internet=internet,
                max_submissions=max_submissions,
                submission_cooldown=submission_cooldown,
            )
        prompt_path = "/tmp/agent_prompt.md"
        local_prompt = log_dir / "agent_prompt.md"
        local_prompt.write_text(prompt)
        backend.copy_to_container(handle, local_prompt, PurePosixPath(prompt_path))
        backend.exec_run(handle, f"chmod a+r {prompt_path}")
        logger.info(f"Prompt written ({len(prompt)} bytes)")

        # 6. Run agent (with auto-resume on abnormal exit)
        can_resume = not disable_auto_resume and agent.resume_cmd is not None
        remaining_timeout = effective_timeout
        resume_count = 0
        total_runtime = 0.0
        agent_timed_out = False
        all_output_parts: list[str] = []
        agent_live_log = log_dir / "agent_output.txt"
        # Wall-clock seconds spent paused while the whole account pool was
        # capped. NOT charged against remaining_timeout, so a cap gap can never
        # silently consume the active-compute budget.
        paused_seconds = 0.0
        # Bounded number of pool-pause cycles: at least MIN_POOL_PAUSES, and up
        # to one per account so a pool that caps one account at a time can be
        # traversed fully before we give up.
        pool_pause_count = 0
        _pool_pause_url = config.agent_api_base_url or agent.default_api_base_url

        started_at = time.time()
        from datetime import datetime

        started_at_iso = datetime.fromtimestamp(started_at).strftime(
            "%Y-%m-%dT%H:%M:%S"
        )
        (log_dir / "started_at").write_text(f"{started_at_iso}\n{started_at}\n")

        on_chunk_cb = None

        while remaining_timeout > 0:
            is_resume = resume_count > 0
            run_cmd = agent.format_run_cmd(
                prompt_path,
                model=model,
                internet=internet,
                resume=is_resume,
            )
            if is_resume:
                logger.info(
                    f"Resuming agent (attempt {resume_count}/{MAX_RESUMES}, "
                    f"{remaining_timeout:.0f}s left): {run_cmd[:200]}..."
                )
            else:
                logger.info(
                    f"Running agent: {run_cmd[:200]}... (timeout={remaining_timeout:.0f}s)"
                )

            seg_result = backend.exec_run_with_timeout(
                handle,
                ["/bin/bash", "-c", run_cmd],
                timeout=int(remaining_timeout),
                log_file=agent_live_log,
                workdir=task_spec.cwd,
                environment=env,
                stream_to_stdout=verbose,
                shutdown_event=shutdown_event,
                log_append=is_resume,
                on_chunk=on_chunk_cb,
            )
            all_output_parts.append(seg_result.output)
            total_runtime += seg_result.elapsed_seconds

            if seg_result.timed_out:
                agent_timed_out = True
                break

            if not can_resume:
                break

            # Every completed segment costs active-compute budget, however
            # short — keep the accounting consistent for all exit paths.
            remaining_timeout -= seg_result.elapsed_seconds

            # A near-instant exit is the signature of resume-thrash: the agent
            # crashed immediately, almost always because the whole OAuth account
            # pool is rate-limit-capped. Ask the bridge when the pool next
            # resets and PAUSE until then, instead of relaunching straight back
            # into the same 429. The pause is bounded (count + duration) and is
            # not charged against the active-compute budget.
            if seg_result.elapsed_seconds < MIN_RUNTIME_FOR_RESUME:
                reset_at, pool_size = _bridge_pool_status(_pool_pause_url, logger)
                now = time.time()

                # Fallback: if the bridge probe failed but the agent output
                # clearly shows a cap, still choose a conservative pause rather
                # than a hard failure (a real cap outlives a bridge blip).
                if reset_at is None:
                    tail = seg_result.output[-4000:] if seg_result.output else ""
                    if _text_has_cap_signal(tail):
                        reset_at = now + BRIDGE_DOWN_PAUSE

                if reset_at is not None and reset_at > now:
                    max_pool_pauses = max(MIN_POOL_PAUSES, pool_size)
                    if pool_pause_count >= max_pool_pauses:
                        logger.warning(
                            f"Pool-pause budget spent ({pool_pause_count}/"
                            f"{max_pool_pauses}); stopping."
                        )
                        break
                    wait = min(reset_at - now + 30.0, MAX_POOL_PAUSE, remaining_timeout)
                    if wait > 0:
                        logger.warning(
                            f"Account pool capped; pausing {wait:.0f}s until reset "
                            f"(pause {pool_pause_count + 1}/{max_pool_pauses}; "
                            f"not charged to the run budget)."
                        )
                        _pause_start = time.time()
                        if shutdown_event is not None:
                            shutdown_event.wait(wait)
                            if shutdown_event.is_set():
                                break
                        else:
                            time.sleep(wait)
                        paused_seconds += time.time() - _pause_start
                        pool_pause_count += 1
                        continue

                logger.warning(
                    f"Agent exited after only {seg_result.elapsed_seconds:.1f}s "
                    f"(< {MIN_RUNTIME_FOR_RESUME}s) and the pool is not capped; "
                    f"not resuming (likely systematic failure)."
                )
                break

            if resume_count >= MAX_RESUMES:
                logger.warning(f"Max resume attempts ({MAX_RESUMES}) reached")
                break

            resume_count += 1
            # A segment that ran long enough to resume is real progress: reset
            # the pool-pause budget so it is measured per-incident.
            pool_pause_count = 0
            logger.info(
                f"Agent exited after {seg_result.elapsed_seconds:.1f}s, will resume"
            )

        agent_output = "\n".join(all_output_parts)
        runtime = total_runtime
        logger.info(
            f"Agent finished: runtime={runtime:.1f}s, timed_out={agent_timed_out}, "
            f"resumes={resume_count}, pool_paused={paused_seconds:.0f}s"
        )

        # 7. Stop auto-eval thread before extracting final archive
        if auto_eval_stop is not None:
            auto_eval_stop.set()
            logger.info("Auto-eval thread stopped")

        # 8. Extract final archive (tar of submit_paths)
        try:
            final_archive = _extract_archive_from_container(backend, handle, task_spec)
            (log_dir / "final_archive.tar.gz").write_bytes(final_archive)
            logger.info(f"Final archive: {len(final_archive)} bytes")
        except Exception as e:
            logger.warning(
                f"Failed to extract final archive (container may have stopped): {e}"
            )
            final_archive = b""

        # 8. Collect results
        if task_spec.game_mode:
            try:
                requests.post(
                    f"{host_judge_url}/api/v1/game/{run_id}/{task_spec.task_id}/close-all",
                    timeout=30,
                )
            except Exception:
                logger.warning("Failed to close active game sessions")

            try:
                history_resp = requests.get(
                    f"{host_judge_url}/api/v1/history?token={session_token}",
                    timeout=10,
                )
                history_resp.raise_for_status()
                history = history_resp.json()
            except Exception:
                logger.warning("Failed to fetch run history from judge server")
                history = {"run_id": run_id, "best_score": None, "entries": []}

            (log_dir / "game_history.json").write_text(
                json.dumps(history, indent=2, ensure_ascii=False)
            )

            game_entries = [
                e for e in history.get("entries", []) if e.get("type") == "game"
            ]
            best_score_raw = history.get("best_score")
            best_score = float(best_score_raw) if best_score_raw is not None else None
            best_pass_rate_raw = history.get("best_pass_rate", 0.0)
            best_pass_rate = float(best_pass_rate_raw) if best_pass_rate_raw else 0.0
            best_round = history.get("best_round", "")
            total_rounds = len(game_entries)

            result = RunResult(
                archive=final_archive,
                best_pass_rate=best_pass_rate,
                best_score=best_score,
                best_round=best_round,
                total_rounds=total_rounds,
                agent_submissions=total_rounds,
                auto_submissions=0,
                agent_output=agent_output,
                timed_out=agent_timed_out,
                runtime_seconds=runtime,
                resume_count=resume_count,
            )
            logger.info(
                f"Done (game): best_score={best_score} ({best_round}), "
                f"sessions={total_rounds}, resumes={resume_count}, runtime={runtime:.1f}s"
            )
        else:
            # Save debug artifacts from container (non-authoritative, best-effort)
            try:
                state_result = backend.exec_run_with_timeout(
                    handle,
                    [
                        "/bin/bash",
                        "-c",
                        "cat /tmp/sforge_state.json 2>/dev/null || echo '{}'",
                    ],
                    timeout=10,
                )
                state = json.loads(state_result.output.strip())
                (log_dir / "evolve_state.json").write_text(
                    json.dumps(state, indent=2, ensure_ascii=False)
                )
            except Exception:
                logger.warning("Failed to read state file from container")

            # Stop work container processes
            try:
                backend.exec_run(handle, "kill 1 2>/dev/null || true", user="root")
                logger.info("Work container processes stopped")
            except Exception:
                pass

            # Drain pending judge evaluations before querying final results
            drain_deadline = time.time() + 900
            while time.time() < drain_deadline:
                try:
                    h = requests.get(
                        f"{host_judge_url}/api/v1/history",
                        params={"token": session_token, "admin_secret": ADMIN_SECRET},
                        timeout=10,
                    ).json()
                    pending = [
                        e
                        for e in h.get("entries", [])
                        if e.get("status") in ("running", "queued")
                    ]
                    if not pending:
                        break
                    logger.info(f"Draining {len(pending)} pending judge evals...")
                except Exception:
                    break
                time.sleep(15)
            else:
                logger.warning(
                    "Drain timed out after 15 min; some reports may be missing."
                )

            # Query Judge Server for authoritative results (with admin_secret to get full history)
            try:
                history_resp = requests.get(
                    f"{host_judge_url}/api/v1/history",
                    params={"token": session_token, "admin_secret": ADMIN_SECRET},
                    timeout=10,
                )
                history_resp.raise_for_status()
                history = history_resp.json()
            except Exception:
                logger.warning("Failed to fetch run history from judge server")
                history = {
                    "run_id": run_id,
                    "best_score": None,
                    "best_pass_rate": 0.0,
                    "best_round": "",
                    "agent_submissions": 0,
                    "auto_submissions": 0,
                    "entries": [],
                }

            (log_dir / "run_history.json").write_text(
                json.dumps(history, indent=2, ensure_ascii=False)
            )

            best_pass_rate = history.get("best_pass_rate", 0.0)
            best_score_raw = history.get("best_score")
            best_score = float(best_score_raw) if best_score_raw is not None else None
            best_round = history.get("best_round", "")
            agent_subs = history.get("agent_submissions", 0)
            auto_subs = history.get("auto_submissions", 0)
            total_rounds = agent_subs + auto_subs

            result = RunResult(
                archive=final_archive,
                best_pass_rate=best_pass_rate,
                best_score=best_score,
                best_round=best_round,
                total_rounds=total_rounds,
                agent_submissions=agent_subs,
                auto_submissions=auto_subs,
                agent_output=agent_output,
                timed_out=agent_timed_out,
                runtime_seconds=runtime,
                resume_count=resume_count,
            )

            logger.info(
                f"Done: best={result.best_pass_rate:.2%} "
                f"(round {result.best_round!r}), "
                f"agent_subs={agent_subs}, auto_subs={auto_subs}, "
                f"resumes={resume_count}, runtime={runtime:.1f}s"
            )
        return result

    except KeyboardInterrupt:
        logger.info("Run interrupted by user (Ctrl+C)")

        # Stop auto-eval thread
        if auto_eval_stop is not None:
            auto_eval_stop.set()

        # Try to extract archive from the container before it's destroyed
        interrupted_archive = b""
        try:
            if handle is not None:
                interrupted_archive = _extract_archive_from_container(
                    backend, handle, task_spec
                )
                (log_dir / "final_archive.tar.gz").write_bytes(interrupted_archive)
                logger.info(
                    f"Final archive (interrupted): {len(interrupted_archive)} bytes"
                )
        except Exception:
            pass

        # Query judge server for results accumulated before interruption (full history)
        try:
            history_resp = requests.get(
                f"{host_judge_url}/api/v1/history",
                params={"token": session_token, "admin_secret": ADMIN_SECRET},
                timeout=10,
            )
            history_resp.raise_for_status()
            history = history_resp.json()
        except Exception:
            history = {
                "run_id": run_id,
                "best_score": None,
                "best_pass_rate": 0.0,
                "best_round": "",
                "agent_submissions": 0,
                "auto_submissions": 0,
                "entries": [],
            }

        (log_dir / "run_history.json").write_text(
            json.dumps(history, indent=2, ensure_ascii=False)
        )

        best_pass_rate = history.get("best_pass_rate", 0.0)
        best_score_raw = history.get("best_score")
        best_score = float(best_score_raw) if best_score_raw is not None else None
        best_round = history.get("best_round", "")
        agent_subs = history.get("agent_submissions", 0)
        auto_subs = history.get("auto_submissions", 0)
        total_rounds = agent_subs + auto_subs

        logger.info(
            f"Interrupted results: best={best_pass_rate:.2%} "
            f"(round {best_round!r}), "
            f"agent_subs={agent_subs}, auto_subs={auto_subs}"
        )

        return RunResult(
            archive=interrupted_archive,
            best_pass_rate=best_pass_rate,
            best_score=best_score,
            best_round=best_round,
            total_rounds=total_rounds,
            agent_submissions=agent_subs,
            auto_submissions=auto_subs,
            agent_output="Stopped by user (Ctrl+C)",
            timed_out=False,
            resume_count=resume_count,
        )
    except Exception as e:
        logger.error(f"Error: {e}\n{traceback.format_exc()}")

        try:
            history_resp = requests.get(
                f"{host_judge_url}/api/v1/history?token={session_token}",
                timeout=10,
            )
            history_resp.raise_for_status()
            history = history_resp.json()
            best_pass_rate = history.get("best_pass_rate", 0.0)
            best_score_raw = history.get("best_score")
            best_score = float(best_score_raw) if best_score_raw is not None else None
            best_round = history.get("best_round", "")
            agent_subs = history.get("agent_submissions", 0)
            auto_subs = history.get("auto_submissions", 0)
        except Exception:
            best_pass_rate = 0.0
            best_score = None
            best_round = ""
            agent_subs = 0
            auto_subs = 0

        return RunResult(
            best_pass_rate=best_pass_rate,
            best_score=best_score,
            best_round=best_round,
            total_rounds=agent_subs + auto_subs,
            agent_submissions=agent_subs,
            auto_submissions=auto_subs,
            agent_output=str(e),
            timed_out=False,
            resume_count=locals().get("resume_count", 0),
        )
    finally:
        if net_isolation is not None:
            try:
                net_isolation.cleanup()
            except Exception as exc:
                if logger:
                    logger.warning(f"Failed to cleanup network isolation: {exc}")
        if relay_name is not None:
            try:
                import docker as _docker

                from sforge.harness.isolated_network import cleanup_relay

                cleanup_relay(_docker.from_env(), relay_name, logger)
            except Exception as exc:
                if logger:
                    logger.warning(f"Failed to cleanup relay: {exc}")
        if threading.current_thread() is threading.main_thread():
            prev_handler = signal.signal(signal.SIGINT, signal.SIG_IGN)
            print(
                "\nStopping container, please wait... (Ctrl+C disabled during cleanup)"
            )
            backend.cleanup_container(handle, logger)
            signal.signal(signal.SIGINT, prev_handler)
        else:
            backend.cleanup_container(handle, logger)
        close_logger(logger)
