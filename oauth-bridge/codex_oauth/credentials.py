"""OpenAI Codex ChatGPT-subscription OAuth credentials: read from disk + refresh.

The official ``codex`` CLI ("Sign in with ChatGPT") stores its credential as a
plain file at ``${CODEX_HOME:-~/.codex}/auth.json`` (NOT a keychain). Shape::

    {"OPENAI_API_KEY": null,
     "tokens": {"id_token": "<jwt>",
                "access_token": "<jwt>",
                "refresh_token": "rt....",
                "account_id": "<uuid>"},
     "last_refresh": "2026-07-24T06:30:03Z"}

The ``access_token`` is a JWT; its ``exp`` claim is the expiry (there is no
separate ``expiresAt`` field like Claude has, so we decode it). ``account_id``
must be sent to the ChatGPT backend as the ``ChatGPT-Account-Id`` header.

Sources tried in priority order:
  1. ``CODEX_CREDENTIALS`` env var (inline JSON, for tests/CI).
  2. ``WCB_CODEX_CREDS_PATH`` env var (path to an auth.json, for pool accounts).
  3. ``${CODEX_HOME:-~/.codex}/auth.json`` (the local codex login).
  4. ``~/.cache/wildclawbench/codex_creds.json`` (bridge refresh cache, last).

This mirrors ``claude_oauth.credentials`` so the two bridges behave the same at
the pool/rotation layer; the differences are the on-disk shape, the refresh
endpoint (``auth.openai.com``), and that expiry is decoded from the JWT.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import httpx

_LOG = logging.getLogger(__name__)

# Public Codex OAuth client id. Taken from the ``client_id`` / ``aud`` claim
# that ships inside every ChatGPT-subscription access token; required for the
# refresh-token grant.
CODEX_CLIENT_ID = os.environ.get(
    "WCB_CODEX_CLIENT_ID", "app_EMoamEEZ73f0CkXaXp7hrann"
)
REFRESH_ENDPOINT = os.environ.get(
    "WCB_CODEX_REFRESH_URL", "https://auth.openai.com/oauth/token"
)
REFRESH_SCOPE = "openid profile email offline_access"
REFRESH_LEEWAY_SECONDS = 300

_CACHE_PATH = Path.home() / ".cache" / "wildclawbench" / "codex_creds.json"


class CredentialsError(RuntimeError):
    """Raised when credentials cannot be loaded or refreshed."""


def _jwt_claims(token: str) -> dict:
    """Best-effort decode of a JWT payload segment. Returns {} on any failure."""
    try:
        parts = token.split(".")
        if len(parts) < 2:
            return {}
        payload = parts[1]
        payload += "=" * (-len(payload) % 4)  # pad base64url
        return json.loads(base64.urlsafe_b64decode(payload.encode("ascii")))
    except Exception:  # noqa: BLE001 - decoding is purely advisory
        return {}


def _account_id_from_id_token(id_token: Optional[str]) -> Optional[str]:
    if not id_token:
        return None
    claims = _jwt_claims(id_token)
    auth = claims.get("https://api.openai.com/auth")
    if isinstance(auth, dict):
        return auth.get("chatgpt_account_id")
    return None


@dataclass
class CodexCredentials:
    access_token: str
    refresh_token: str
    account_id: str
    id_token: Optional[str] = None
    expires_at_ms: int = 0  # derived from the access_token JWT `exp`

    @classmethod
    def from_codex_payload(cls, payload: dict) -> "CodexCredentials":
        tokens = payload.get("tokens") if isinstance(payload, dict) else None
        tokens = tokens if isinstance(tokens, dict) else {}
        try:
            access_token = tokens["access_token"]
            refresh_token = tokens["refresh_token"]
        except (KeyError, TypeError) as e:
            raise CredentialsError(f"Malformed Codex auth.json (tokens): {e}") from e
        account_id = (
            tokens.get("account_id")
            or _account_id_from_id_token(tokens.get("id_token"))
            or ""
        )
        if not account_id:
            raise CredentialsError("Codex auth.json missing tokens.account_id")
        exp = int(_jwt_claims(access_token).get("exp", 0) or 0)
        return cls(
            access_token=access_token,
            refresh_token=refresh_token,
            account_id=account_id,
            id_token=tokens.get("id_token"),
            expires_at_ms=exp * 1000,
        )

    def to_codex_payload(self) -> dict:
        return {
            "OPENAI_API_KEY": None,
            "tokens": {
                "id_token": self.id_token,
                "access_token": self.access_token,
                "refresh_token": self.refresh_token,
                "account_id": self.account_id,
            },
            "last_refresh": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }

    def is_expired(self, leeway_seconds: int = REFRESH_LEEWAY_SECONDS) -> bool:
        # An access token whose `exp` we could not parse (expires_at_ms == 0)
        # is treated as NOT expired: refreshing a token we cannot reason about
        # risks burning a rotating refresh_token needlessly. A live 401 will
        # force a reload/refresh at the bridge layer instead.
        if self.expires_at_ms <= 0:
            return False
        return time.time() >= (self.expires_at_ms / 1000.0) - leeway_seconds


def _read_inline_env() -> Optional[str]:
    raw = os.environ.get("CODEX_CREDENTIALS")
    return raw if raw else None


def _default_auth_path() -> Path:
    base = os.environ.get("CODEX_HOME") or str(Path.home() / ".codex")
    return Path(base) / "auth.json"


def _read_credentials_file() -> Optional[str]:
    # An EXPLICIT WCB_CODEX_CREDS_PATH must not silently fall back to the local
    # ~/.codex/auth.json — that would let `--check` report OK on the wrong
    # account when a pool file is missing. If set, that path is authoritative.
    env_path = os.environ.get("WCB_CODEX_CREDS_PATH")
    if env_path:
        p = Path(env_path).expanduser()
        if not p.is_file():
            raise CredentialsError(
                f"WCB_CODEX_CREDS_PATH points to a missing file: {p}"
            )
        try:
            return p.read_text(encoding="utf-8")
        except OSError as e:
            raise CredentialsError(f"could not read {p}: {e}") from e
    default = _default_auth_path()
    if default.is_file():
        try:
            return default.read_text(encoding="utf-8")
        except OSError as e:
            _LOG.debug("credentials file %s read failed: %s", default, e)
    return None


def _read_cache_file() -> Optional[str]:
    if _CACHE_PATH.is_file():
        try:
            return _CACHE_PATH.read_text(encoding="utf-8")
        except OSError:
            return None
    return None


def _no_credentials_hint() -> str:
    return (
        "No Codex credentials found. Sign in via the `codex` CLI first "
        "(Sign in with ChatGPT), which writes ${CODEX_HOME:-~/.codex}/auth.json, "
        "or set WCB_CODEX_CREDS_PATH to an exported auth.json, or "
        "CODEX_CREDENTIALS to inline JSON."
    )


def load_credentials() -> CodexCredentials:
    raw = _read_inline_env() or _read_credentials_file() or _read_cache_file()
    if not raw:
        raise CredentialsError(_no_credentials_hint())
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as e:
        raise CredentialsError(f"Codex credentials are not valid JSON: {e}") from e
    return CodexCredentials.from_codex_payload(payload)


def refresh_credentials(
    creds: CodexCredentials,
    *,
    timeout: float = 30.0,
    max_attempts: int = 3,
    backoff_base: float = 1.0,
) -> CodexCredentials:
    """Exchange ``refresh_token`` for a new ``access_token`` (rotated refresh).

    OpenAI rotates ``refresh_token`` on every call, so the caller MUST persist
    the returned credentials or the next refresh will fail. 4xx (typically a
    revoked refresh token) is raised immediately; 5xx / network errors retry.
    """
    last_error: Optional[Exception] = None
    r = None
    for attempt in range(1, max_attempts + 1):
        try:
            with httpx.Client(timeout=timeout) as client:
                r = client.post(
                    REFRESH_ENDPOINT,
                    json={
                        "grant_type": "refresh_token",
                        "client_id": CODEX_CLIENT_ID,
                        "refresh_token": creds.refresh_token,
                        "scope": REFRESH_SCOPE,
                    },
                    headers={"content-type": "application/json"},
                )
        except (httpx.HTTPError, OSError) as e:
            last_error = e
            if attempt >= max_attempts:
                raise CredentialsError(
                    f"Codex OAuth refresh network error after {attempt} attempts: {e}"
                ) from e
            time.sleep(backoff_base * (2 ** (attempt - 1)))
            continue

        if r.status_code == 200:
            break
        if 400 <= r.status_code < 500:
            raise CredentialsError(
                f"Codex OAuth refresh failed (non-retryable): "
                f"HTTP {r.status_code} {r.text[:200]}"
            )
        last_error = CredentialsError(
            f"Codex OAuth refresh failed: HTTP {r.status_code} {r.text[:200]}"
        )
        if attempt >= max_attempts:
            raise last_error
        time.sleep(backoff_base * (2 ** (attempt - 1)))
    else:  # pragma: no cover
        raise CredentialsError(
            f"Codex OAuth refresh failed after {max_attempts} attempts: {last_error}"
        )

    try:
        body = r.json()
    except ValueError as e:
        raise CredentialsError(f"Codex OAuth refresh returned non-JSON: {e}") from e

    access_token = body.get("access_token")
    if not access_token:
        raise CredentialsError(f"Codex OAuth refresh missing access_token: {body}")
    refresh_token = body.get("refresh_token") or creds.refresh_token
    id_token = body.get("id_token") or creds.id_token
    exp = int(_jwt_claims(access_token).get("exp", 0) or 0)
    return CodexCredentials(
        access_token=access_token,
        refresh_token=refresh_token,
        account_id=creds.account_id
        or _account_id_from_id_token(id_token)
        or "",
        id_token=id_token,
        expires_at_ms=exp * 1000,
    )


def write_cache(creds: CodexCredentials) -> None:
    _CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    _CACHE_PATH.write_text(json.dumps(creds.to_codex_payload()), encoding="utf-8")
    try:
        os.chmod(_CACHE_PATH, 0o600)
    except OSError:
        pass


class CredentialProvider:
    """Thread-safe lazy credential cache with auto-refresh (single account)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._creds: Optional[CodexCredentials] = None

    def _load(self) -> CodexCredentials:
        return load_credentials()

    def get_credentials(self) -> CodexCredentials:
        with self._lock:
            if self._creds is None:
                self._creds = self._load()
            if self._creds.is_expired():
                _LOG.info("Refreshing Codex OAuth token")
                self._creds = refresh_credentials(self._creds)
                try:
                    write_cache(self._creds)
                except OSError as e:
                    _LOG.warning("Could not persist refreshed creds to cache: %s", e)
            return self._creds

    def get_access_token(self) -> str:
        return self.get_credentials().access_token

    def force_reload(self) -> None:
        with self._lock:
            self._creds = None

    def token_prefix(self) -> Optional[str]:
        with self._lock:
            return self._creds.access_token[:20] if self._creds else None


class _FileCredentialProvider(CredentialProvider):
    """CredentialProvider that always loads from a specific auth.json path."""

    def __init__(self, path: Path) -> None:
        super().__init__()
        self._path = Path(path).expanduser()

    def _load(self) -> CodexCredentials:
        if not self._path.is_file():
            raise CredentialsError(f"credentials file not found: {self._path}")
        try:
            raw = self._path.read_text(encoding="utf-8")
        except OSError as e:
            raise CredentialsError(f"could not read {self._path}: {e}") from e
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as e:
            raise CredentialsError(f"invalid JSON in {self._path}: {e}") from e
        return CodexCredentials.from_codex_payload(payload)

    def get_credentials(self) -> CodexCredentials:
        with self._lock:
            if self._creds is None:
                self._creds = self._load()
            if not self._creds.is_expired():
                return self._creds
            # Cross-process serialization: only one bridge process refreshes;
            # others wait on the flock then re-read the rotated token. Without
            # this, concurrent runs sharing a pool file race and lose tokens.
            import fcntl

            lock_path = self._path.with_suffix(self._path.suffix + ".lock")
            lock_path.parent.mkdir(parents=True, exist_ok=True)
            with open(lock_path, "w") as lock_fh:
                try:
                    fcntl.flock(lock_fh.fileno(), fcntl.LOCK_EX)
                except OSError as e:
                    _LOG.warning("flock failed on %s: %s; proceeding", lock_path, e)
                try:
                    fresh = self._load()
                    if not fresh.is_expired():
                        self._creds = fresh
                        return self._creds
                except CredentialsError:
                    pass
                _LOG.info("Refreshing Codex OAuth token from %s", self._path)
                self._creds = refresh_credentials(self._creds)
                try:
                    self._path.write_text(
                        json.dumps(self._creds.to_codex_payload()), encoding="utf-8"
                    )
                    os.chmod(self._path, 0o600)
                except OSError as e:
                    _LOG.warning("Could not persist refreshed creds to %s: %s",
                                 self._path, e)
            return self._creds


# ---------------------------------------------------------------------------
# Multi-account pool support (mirrors claude_oauth)
# ---------------------------------------------------------------------------


@dataclass
class _AccountSlot:
    provider: CredentialProvider
    label: str
    exhausted_until: float = 0.0
    invalid: bool = False

    def is_available(self, now: Optional[float] = None) -> bool:
        if self.invalid:
            return False
        now = now if now is not None else time.time()
        return now >= self.exhausted_until


class MultiAccountCredentialProvider:
    """Pool of ``CredentialProvider``s with rotation + exhaustion tracking.

    Exposes ``get_credentials()`` / ``get_access_token()`` / ``force_reload()``
    like the single provider. Selection policy: first available slot in
    insertion order (put your primary account first).
    """

    def __init__(self, slots: list[_AccountSlot]) -> None:
        if not slots:
            raise CredentialsError("MultiAccountCredentialProvider needs >= 1 slot")
        self._slots = slots
        self._lock = threading.Lock()
        self._last_used_index = 0

    def get_credentials(self) -> CodexCredentials:
        with self._lock:
            slot, idx = self._select_slot_locked()
            self._last_used_index = idx
        try:
            return slot.provider.get_credentials()
        except CredentialsError:
            with self._lock:
                slot.invalid = True
            return self.get_credentials()

    def get_access_token(self) -> str:
        return self.get_credentials().access_token

    def _select_slot_locked(self) -> tuple[_AccountSlot, int]:
        now = time.time()
        for idx, slot in enumerate(self._slots):
            if slot.is_available(now):
                return slot, idx
        soonest = min(
            (s.exhausted_until for s in self._slots if not s.invalid), default=0.0
        )
        delta = max(0.0, soonest - now)
        raise CredentialsError(
            f"all {len(self._slots)} accounts exhausted; soonest reset in {delta:.0f}s"
        )

    def force_reload(self) -> None:
        with self._lock:
            for slot in self._slots:
                slot.provider.force_reload()
                slot.exhausted_until = 0.0
                slot.invalid = False

    def mark_account_exhausted(self, token_prefix: str, until_unix: float) -> None:
        with self._lock:
            slot = self._find_slot_by_prefix_locked(token_prefix)
            if slot is None:
                return
            slot.exhausted_until = max(slot.exhausted_until, until_unix)
            _LOG.info("account %s exhausted until %s (in %.0fs)", slot.label,
                      until_unix, max(0.0, until_unix - time.time()))

    def mark_account_invalid(self, token_prefix: str) -> None:
        with self._lock:
            slot = self._find_slot_by_prefix_locked(token_prefix)
            if slot is None:
                return
            slot.invalid = True
            _LOG.warning("account %s marked invalid", slot.label)

    def next_reset_at(self) -> Optional[float]:
        with self._lock:
            now = time.time()
            if any(s.is_available(now) for s in self._slots):
                return None
            future = [s.exhausted_until for s in self._slots if not s.invalid]
            return min(future) if future else None

    def snapshot(self) -> list[dict]:
        with self._lock:
            return [
                {
                    "label": s.label,
                    "token_prefix": s.provider.token_prefix(),
                    "invalid": s.invalid,
                    "exhausted_until": s.exhausted_until,
                    "available": s.is_available(),
                }
                for s in self._slots
            ]

    def _find_slot_by_prefix_locked(self, token_prefix: str) -> Optional[_AccountSlot]:
        for slot in self._slots:
            sp = slot.provider.token_prefix()
            if sp and (sp.startswith(token_prefix) or token_prefix.startswith(sp)):
                return slot
        return None


def load_account_pool(spec: str) -> Optional[MultiAccountCredentialProvider]:
    """Parse a ``WCB_CODEX_ACCOUNT_POOL`` spec into a multi-account provider.

    Spec: colon-separated entries, each either a path to an auth.json, or the
    literal ``default`` (the standard single-account resolution). Empty entries
    are skipped. Returns ``None`` if the spec yields no slots.
    """
    if not spec:
        return None
    slots: list[_AccountSlot] = []
    for raw in spec.split(":"):
        entry = raw.strip()
        if not entry:
            continue
        if entry == "default":
            slots.append(_AccountSlot(provider=CredentialProvider(), label="default"))
            continue
        slots.append(_AccountSlot(
            provider=_FileCredentialProvider(Path(entry)), label=f"file:{entry}"
        ))
    if not slots:
        return None
    return MultiAccountCredentialProvider(slots)
