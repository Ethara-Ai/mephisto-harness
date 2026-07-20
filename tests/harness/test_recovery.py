from __future__ import annotations

import time

import pytest

from sforge.harness import run_agent


@pytest.mark.parametrize(
    "text, expected",
    [
        ("HTTP 429 rate_limit_error", True),
        ("Too Many Requests", True),
        ("resource_exhausted", True),
        ("all 3 accounts exhausted; soonest reset in 1800s", True),
        ("credentials_unavailable", True),
        ("error code 429 from upstream", True),
        ("Successfully wrote policy.py and passed all tests", False),
        ("no issues encountered", False),
        ("", False),
    ],
)
def test_text_has_cap_signal(text: str, expected: bool) -> None:
    assert run_agent._text_has_cap_signal(text) is expected


class _FakeResp:
    def __init__(self, data: dict) -> None:
        self._data = data

    def raise_for_status(self) -> None:
        pass

    def json(self) -> dict:
        return self._data


def _patch_get(monkeypatch, data: dict) -> None:
    monkeypatch.setattr(
        run_agent.requests, "get", lambda url, timeout=None: _FakeResp(data)
    )


def test_pool_status_all_capped(monkeypatch) -> None:
    reset = time.time() + 300
    _patch_get(monkeypatch, {"accounts": [{}, {}, {}], "next_reset_at_unix": reset})
    reset_at, size = run_agent._bridge_pool_status("http://x:9090/v1", None)
    assert size == 3
    assert reset_at is not None and 250 < reset_at - time.time() < 350


def test_pool_status_available_pool_reports_size_but_no_reset(monkeypatch) -> None:
    _patch_get(monkeypatch, {"accounts": [{}, {}], "next_reset_at_unix": None})
    reset_at, size = run_agent._bridge_pool_status("http://x/v1", None)
    assert reset_at is None
    assert size == 2


def test_pool_status_strips_v1_suffix(monkeypatch) -> None:
    seen: dict[str, str] = {}

    def _get(url, timeout=None):
        seen["url"] = url
        return _FakeResp({"accounts": [], "next_reset_at_unix": None})

    monkeypatch.setattr(run_agent.requests, "get", _get)
    run_agent._bridge_pool_status("http://host:9090/v1", None)
    assert seen["url"] == "http://host:9090/healthz"


def test_pool_status_no_url() -> None:
    assert run_agent._bridge_pool_status(None, None) == (None, 0)
    assert run_agent._bridge_pool_status("", None) == (None, 0)


def test_pool_status_network_error(monkeypatch) -> None:
    def _boom(url, timeout=None):
        raise RuntimeError("connection refused")

    monkeypatch.setattr(run_agent.requests, "get", _boom)
    assert run_agent._bridge_pool_status("http://x/v1", None) == (None, 0)


def test_pool_status_malformed_json_uses_defaults(monkeypatch) -> None:
    _patch_get(monkeypatch, {"unexpected": "shape"})
    reset_at, size = run_agent._bridge_pool_status("http://x/v1", None)
    assert reset_at is None
    assert size == 0


def test_pool_status_zero_reset_is_ignored(monkeypatch) -> None:
    _patch_get(monkeypatch, {"accounts": [{}], "next_reset_at_unix": 0})
    reset_at, size = run_agent._bridge_pool_status("http://x/v1", None)
    assert reset_at is None
    assert size == 1


def test_recovery_constants_are_sane() -> None:
    assert run_agent.MIN_RUNTIME_FOR_RESUME >= 1
    assert run_agent.MAX_RESUMES >= 1
    assert run_agent.MIN_POOL_PAUSES >= 1
    assert run_agent.MAX_POOL_PAUSE > 0
    assert run_agent.BRIDGE_DOWN_PAUSE > 0
