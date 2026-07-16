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

"""Claude subscription (OAuth) credentials for the host-side API proxy.

Holds a Claude Pro/Max subscription credential on the host so the containerized
Claude Code CLI can run against a subscription without the secret entering the
container. The proxy handler in ``api_proxy.py`` consumes a :class:`TokenStore`
to inject ``Authorization: Bearer <token>`` and refresh rotating tokens across a
long run. Credentials load from a raw token (``claude setup-token``, no refresh)
or a ``.credentials.json`` file (access + rotating refresh token).
"""

from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass
from pathlib import Path

import requests as req_lib

logger = logging.getLogger(__name__)

OAUTH_CLIENT_ID = "9d1c250a-e61b-44d9-88ed-5944d1962f5e"
# console.anthropic.com is decommissioned (404); platform.claude.com is required.
REFRESH_URL = "https://platform.claude.com/v1/oauth/token"
# Merged into (never replacing) the CLI's own anthropic-beta header.
REQUIRED_BETAS = ("oauth-2025-04-20", "claude-code-20250219")
_REFRESH_BUFFER_MS = 5 * 60 * 1000
_REFRESH_TIMEOUT_S = 30


@dataclass
class OAuthCredential:
    access_token: str
    refresh_token: str | None
    expires_at_ms: int


class TokenStore:
    """Thread-safe OAuth credential holder with lazy, serialized refresh.

    The single lock ensures at most one refresh runs at a time, avoiding the
    ``invalid_grant`` error that a rotating refresh token triggers if reused
    concurrently under ``ThreadingHTTPServer``.
    """

    def __init__(self, cred: OAuthCredential) -> None:
        self._cred = cred
        self._lock = threading.Lock()

    def get_token(self) -> str:
        with self._lock:
            if self._needs_refresh():
                self._refresh()
            return self._cred.access_token

    def _needs_refresh(self) -> bool:
        if not self._cred.refresh_token:
            return False
        if self._cred.expires_at_ms <= 0:
            return False
        now_ms = time.time() * 1000
        return now_ms > self._cred.expires_at_ms - _REFRESH_BUFFER_MS

    def _refresh(self) -> None:
        logger.info("Refreshing Claude subscription OAuth token...")
        resp = req_lib.post(
            REFRESH_URL,
            json={
                "grant_type": "refresh_token",
                "refresh_token": self._cred.refresh_token,
                "client_id": OAUTH_CLIENT_ID,
            },
            timeout=_REFRESH_TIMEOUT_S,
        )
        resp.raise_for_status()
        data = resp.json()
        # The refresh response rotates the refresh token; keep the old one only
        # as a defensive fallback if the server omits it (it should not).
        self._cred = OAuthCredential(
            access_token=data["access_token"],
            refresh_token=data.get("refresh_token") or self._cred.refresh_token,
            expires_at_ms=int(time.time() * 1000) + int(data["expires_in"]) * 1000,
        )
        logger.info("OAuth token refreshed (expires in %ss)", data.get("expires_in"))


def load_credential(
    *,
    raw_token: str | None = None,
    credentials_json: Path | None = None,
) -> OAuthCredential:
    """Build an OAuthCredential from a raw token or a .credentials.json file.

    ``raw_token`` (non-refreshable) takes priority over ``credentials_json``
    when both are given. Raises ValueError if neither is provided.
    """
    if raw_token:
        return OAuthCredential(
            access_token=raw_token,
            refresh_token=None,
            expires_at_ms=0,
        )
    if credentials_json:
        data = json.loads(Path(credentials_json).read_text())
        oauth = data["claudeAiOauth"]
        return OAuthCredential(
            access_token=oauth["accessToken"],
            refresh_token=oauth.get("refreshToken"),
            expires_at_ms=int(oauth.get("expiresAt", 0)),
        )
    raise ValueError(
        "Provide either raw_token or credentials_json to load an OAuth credential."
    )
