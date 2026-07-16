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

"""Kernel-enforced network isolation for Docker Desktop (macOS) work containers.

The host-side iptables approach in ``network_isolation.py`` needs a Linux host
and cannot run on Docker Desktop for Mac. This module provides equivalent
``internet:false`` semantics using a Docker ``--internal`` network (which the
in-VM kernel gives no NAT, so containers on it cannot reach the internet even as
root) plus a dual-homed ``socat`` relay that forwards the two endpoints the work
container legitimately needs (model API proxy + judge server) to the host.

Topology::

    work container ── sforge-isolated (--internal, no NAT) ── relay ── bridge ── host
      (isolated)                                            (dual-homed)   :9090 proxy
                                                                           :8080 judge

The work container joins ONLY the internal network, so GitHub / crates.io are
unreachable; it reaches the proxy and judge at the relay's static IP.
"""

from __future__ import annotations

import logging
import time

import docker
import docker.errors
import docker.types

ISOLATED_NET = "sforge-isolated"
ISOLATED_SUBNET = "172.28.0.0/24"
RELAY_IP = "172.28.0.2"
WORK_IP = "172.28.0.3"
RELAY_IMAGE = "alpine/socat"

# Ports forwarded by the relay to host.docker.internal, keyed by purpose.
_PROXY_PORT = 9090
_JUDGE_PORT = 8080


def ensure_isolated_network(client: docker.DockerClient) -> None:
    try:
        client.networks.get(ISOLATED_NET)
    except docker.errors.NotFound:
        client.networks.create(
            ISOLATED_NET,
            driver="bridge",
            internal=True,
            ipam=docker.types.IPAMConfig(
                pool_configs=[docker.types.IPAMPool(subnet=ISOLATED_SUBNET)]
            ),
        )


def start_relay(
    client: docker.DockerClient,
    run_id: str,
    logger: logging.Logger,
    *,
    proxy_port: int = _PROXY_PORT,
    judge_port: int = _JUDGE_PORT,
) -> str:
    """Start the dual-homed socat relay and return its container name.

    The relay is attached to the internal network at a static IP and to the
    default bridge (for host reachability), forwarding proxy_port and judge_port
    to host.docker.internal.
    """
    name = f"sforge-relay-{run_id}"
    _remove_if_exists(client, name)

    # Two socat forwards in one container; reuseaddr so restarts bind cleanly.
    script = (
        f"socat TCP-LISTEN:{proxy_port},fork,reuseaddr "
        f"TCP:host.docker.internal:{proxy_port} & "
        f"socat TCP-LISTEN:{judge_port},fork,reuseaddr "
        f"TCP:host.docker.internal:{judge_port} & wait"
    )
    container = client.containers.create(
        RELAY_IMAGE,
        name=name,
        detach=True,
        entrypoint="sh",
        command=["-c", script],
        extra_hosts={"host.docker.internal": "host-gateway"},
        network=ISOLATED_NET,
    )
    client.networks.get(ISOLATED_NET).disconnect(container)
    client.networks.get(ISOLATED_NET).connect(container, ipv4_address=RELAY_IP)
    client.networks.get("bridge").connect(container)
    container.start()
    logger.info("Isolated-mode relay started: %s (relay ip %s)", name, RELAY_IP)
    return name


def relay_base_urls() -> tuple[str, str]:
    """Return (proxy_base_url, judge_url) as seen from the work container."""
    return (
        f"http://{RELAY_IP}:{_PROXY_PORT}",
        f"http://{RELAY_IP}:{_JUDGE_PORT}",
    )


def wait_for_relay(
    client: docker.DockerClient, name: str, logger: logging.Logger
) -> None:
    """Block until the relay's socat listeners are accepting connections."""
    deadline = time.time() + 30
    while time.time() < deadline:
        container = client.containers.get(name)
        if container.status == "running":
            code, _ = container.exec_run(
                f"sh -c 'nc -z 127.0.0.1 {_PROXY_PORT} && "
                f"nc -z 127.0.0.1 {_JUDGE_PORT}'"
            )
            if code == 0:
                return
        time.sleep(0.5)
    logger.warning("Relay %s not confirmed ready after 30s", name)


def cut_over_to_isolated(
    client: docker.DockerClient, container_name: str, logger: logging.Logger
) -> None:
    """Move an installed work container from the bridge onto the internal net.

    Called AFTER agent install (which needs internet) so the running container
    loses all internet egress while keeping reachability to the relay. This is
    the moment isolation actually takes effect.
    """
    container = client.containers.get(container_name)
    try:
        client.networks.get("bridge").disconnect(container)
    except docker.errors.APIError:
        pass
    client.networks.get(ISOLATED_NET).connect(container, ipv4_address=WORK_IP)
    logger.info(
        "Isolated-mode cutover complete: %s now on internal net only (%s)",
        container_name,
        WORK_IP,
    )


def cleanup_relay(
    client: docker.DockerClient, name: str, logger: logging.Logger | None = None
) -> None:
    _remove_if_exists(client, name)
    if logger:
        logger.info("Isolated-mode relay removed: %s", name)


def _remove_if_exists(client: docker.DockerClient, name: str) -> None:
    try:
        c = client.containers.get(name)
        c.remove(force=True)
    except docker.errors.NotFound:
        pass
