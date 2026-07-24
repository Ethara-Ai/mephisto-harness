"""Codex ChatGPT-subscription bridge for the EdgeBench harness.

Presents an OpenAI-compatible ``/v1/responses`` endpoint that the containerized
``codex`` CLI talks to (via ``OPENAI_BASE_URL``), and forwards each request to
the ChatGPT-subscription backend using the user's OAuth token instead of an API
key. It is the OpenAI twin of ``claude_oauth.bridge``.

Verified contract (from on-disk headroom sources):
  * codex sends to path ``/v1/responses`` (headroom ``auth_mode.CODEX_RESPONSES_PATH``).
  * the ChatGPT backend host is ``https://chatgpt.com/backend-api/...`` and the
    account is scoped with the ``ChatGPT-Account-Id`` header
    (headroom ``codex_rate_limits``).
  * rate-limit data comes back as ``x-codex-primary-*`` response headers.

The one value NOT found literally on disk is the exact codex *inference* upstream
path. It defaults to ``https://chatgpt.com/backend-api/codex`` and is overridable
via ``WCB_CODEX_UPSTREAM`` — if the first live call returns 404, adjust that env.
"""

from __future__ import annotations

import logging
import os
import time
import uuid

import httpx
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse

from .credentials import (
    CredentialProvider,
    CredentialsError,
    MultiAccountCredentialProvider,
    load_account_pool,
)

_LOG = logging.getLogger(__name__)

UPSTREAM_DEFAULT = "https://chatgpt.com/backend-api/codex"
CODEX_ORIGINATOR = os.environ.get("WCB_CODEX_ORIGINATOR", "codex_cli_rs")
CODEX_USER_AGENT = os.environ.get("WCB_CODEX_USER_AGENT", "codex_cli_rs/0.130.0")
CODEX_BETA = os.environ.get("WCB_CODEX_BETA", "responses=experimental")

# Hop-by-hop / auth headers we must NOT copy from the inbound request.
_STRIP_IN = {
    "host", "authorization", "x-api-key", "content-length", "connection",
    "accept-encoding", "proxy-authorization", "chatgpt-account-id",
    "openai-beta", "originator", "user-agent",
}
# Response headers we must not copy back verbatim.
_STRIP_OUT = {"content-encoding", "transfer-encoding", "connection", "content-length"}

_MAX_ACCOUNT_RETRIES = 3


def _upstream_base() -> str:
    return os.environ.get("WCB_CODEX_UPSTREAM", UPSTREAM_DEFAULT).rstrip("/")


def _bridge_secret() -> str | None:
    return os.environ.get("WCB_CODEX_BRIDGE_SECRET") or None


def _resolve_provider():
    """Pool if WCB_CODEX_ACCOUNT_POOL is set, else a single provider."""
    pool_spec = os.environ.get("WCB_CODEX_ACCOUNT_POOL")
    if pool_spec:
        prov = load_account_pool(pool_spec)
        if prov is not None:
            return prov
    return CredentialProvider()


def _presented_secret(request: Request) -> str | None:
    v = request.headers.get("x-wcb-bridge-secret")
    if v:
        return v
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[len("bearer "):].strip()
    return request.headers.get("x-api-key")


def _authorized(request: Request) -> bool:
    secret = _bridge_secret()
    if not secret:
        return True  # unauthenticated mode (warned at startup)
    import hmac

    presented = _presented_secret(request) or ""
    return hmac.compare_digest(presented, secret)


def _normalize_path(path: str) -> str:
    """Map the inbound path to the upstream sub-path.

    codex hits ``/v1/responses`` (or ``/responses``); the upstream base already
    includes the ``/codex`` segment, so we forward just ``responses`` (etc).
    """
    p = path.lstrip("/")
    if p.startswith("v1/"):
        p = p[len("v1/"):]
    return p


def _forward_headers(inbound, creds) -> dict[str, str]:
    fwd = {
        k: v for k, v in inbound.items()
        if k.lower() not in _STRIP_IN
    }
    fwd["Authorization"] = f"Bearer {creds.access_token}"
    fwd["ChatGPT-Account-Id"] = creds.account_id
    fwd["OpenAI-Beta"] = CODEX_BETA
    fwd["originator"] = CODEX_ORIGINATOR
    fwd["User-Agent"] = CODEX_USER_AGENT
    fwd.setdefault("session_id", str(uuid.uuid4()))
    fwd.setdefault("content-type", "application/json")
    return fwd


def _sniff_usage(data: bytes) -> None:
    """Pull token usage out of a response and log cached vs total input tokens.

    OpenAI's Responses API reports prompt-cache hits in
    usage.input_tokens_details.cached_tokens. Logging it lets us verify caching
    is actually happening on the ChatGPT-subscription backend.
    """
    if b"input_tokens" not in data and b"cached_tokens" not in data:
        return
    import json as _json

    text = data.decode("utf-8", "replace")
    # Find each `"usage": { ... }` and brace-match to its close (the object is
    # nested — input_tokens_details lives inside — so a regex won't do).
    start = 0
    logged = False
    while True:
        k = text.find('"usage"', start)
        if k == -1:
            break
        b = text.find("{", k)
        if b == -1:
            break
        depth = 0
        end = -1
        for i in range(b, len(text)):
            c = text[i]
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    end = i + 1
                    break
        start = (end if end != -1 else b + 1)
        if end == -1:
            continue
        try:
            u = _json.loads(text[b:end])
        except Exception:  # noqa: BLE001
            continue
        inp = u.get("input_tokens")
        out = u.get("output_tokens")
        cached = (u.get("input_tokens_details") or {}).get("cached_tokens")
        if inp is None and cached is None:
            continue
        pct = f"{100 * cached / inp:.0f}%" if (inp and cached is not None) else "?"
        _LOG.info("CACHE usage: input=%s cached=%s (%s) output=%s", inp, cached, pct, out)
        logged = True
    return logged


def _is_streaming(raw_body: bytes) -> bool:
    if not raw_body:
        return False
    try:
        import json

        return json.loads(raw_body).get("stream") is True
    except Exception:  # noqa: BLE001
        return b'"stream": true' in raw_body or b'"stream":true' in raw_body


def _classify(status: int) -> str:
    if status == 401:
        return "token_invalid"      # refresh / rotate
    if status == 429:
        return "cap"                # rotate account
    if status == 403:
        return "restricted"         # rotate account
    if 500 <= status < 600:
        return "upstream_5xx"       # inline retry
    return "ok" if status < 400 else "other"


def _mark(provider, token_prefix: str, kind: str, headers) -> None:
    """Record account state from an upstream failure (multi-account only)."""
    if not isinstance(provider, MultiAccountCredentialProvider):
        if kind == "token_invalid":
            provider.force_reload()
        return
    if kind == "cap":
        reset = headers.get("x-codex-primary-reset-at")
        try:
            until = float(reset) if reset else time.time() + 300
        except (TypeError, ValueError):
            until = time.time() + 300
        provider.mark_account_exhausted(token_prefix, until)
    elif kind in ("token_invalid", "restricted"):
        provider.mark_account_invalid(token_prefix)


def build_app(provider=None) -> FastAPI:
    provider = provider if provider is not None else _resolve_provider()
    app = FastAPI(title="Codex ChatGPT-subscription Bridge", version="1.0.0")

    if not _bridge_secret():
        _LOG.warning("WCB_CODEX_BRIDGE_SECRET unset — bridge accepts unauthenticated "
                     "requests (fine for localhost-only smoke tests)")

    @app.get("/healthz")
    async def healthz():  # noqa: ANN202
        return {"ok": True}

    @app.get("/quota")
    async def quota(request: Request):  # noqa: ANN202
        auth = _authorized(request)
        if isinstance(provider, MultiAccountCredentialProvider):
            accounts = provider.snapshot()
            if not auth:
                for a in accounts:
                    a.pop("token_prefix", None)
            return {
                "multi_account": True,
                "accounts": accounts,
                "next_reset_at_unix": provider.next_reset_at(),
            }
        return {"multi_account": False, "accounts": [], "next_reset_at_unix": None}

    @app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
    async def proxy(path: str, request: Request):  # noqa: ANN202
        if not _authorized(request):
            return JSONResponse(
                status_code=401,
                content={"error": {"type": "authentication_error",
                                    "message": "codex-bridge: missing/invalid secret"}},
            )
        raw_body = await request.body()
        url = f"{_upstream_base()}/{_normalize_path(path)}"
        params = dict(request.query_params)
        streaming = _is_streaming(raw_body)

        import asyncio

        tried: set[str] = set()
        last_resp_bytes: bytes | None = None
        last_status = 502
        for attempt in range(_MAX_ACCOUNT_RETRIES + 1):
            try:
                creds = await asyncio.to_thread(provider.get_credentials)
            except CredentialsError as e:
                return JSONResponse(
                    status_code=401,
                    content={"error": {"type": "authentication_error",
                                       "message": f"codex-bridge: {e}"}},
                )
            tok_prefix = creds.access_token[:20]
            if tok_prefix in tried and isinstance(provider, MultiAccountCredentialProvider):
                # Same burned account came back — nothing else available.
                break
            tried.add(tok_prefix)
            headers = _forward_headers(request.headers, creds)

            if streaming:
                resp = await _proxy_streaming(url, params, headers, raw_body,
                                              request.method)
                if isinstance(resp, StreamingResponse):
                    return resp
                # tuple(status, body, hdrs) => a pre-stream error we can classify
                last_status, last_resp_bytes, up_headers = resp
            else:
                last_status, last_resp_bytes, up_headers = await _proxy_buffered(
                    url, params, headers, raw_body, request.method
                )

            kind = _classify(last_status)
            if kind == "ok":
                media = up_headers.get("content-type", "application/json")
                out_headers = {k: v for k, v in up_headers.items()
                               if k.lower() not in _STRIP_OUT}
                return Response(content=last_resp_bytes, status_code=last_status,
                                headers=out_headers, media_type=media)
            _mark(provider, tok_prefix, kind, up_headers)
            if kind == "upstream_5xx" and attempt < _MAX_ACCOUNT_RETRIES:
                await asyncio.sleep(min(2 ** attempt, 8))
                continue
            if kind in ("cap", "token_invalid", "restricted") and \
                    isinstance(provider, MultiAccountCredentialProvider) and \
                    provider.next_reset_at() is None and attempt < _MAX_ACCOUNT_RETRIES:
                await asyncio.sleep(0.5)
                continue
            break

        # Exhausted retries — surface the last upstream response.
        return Response(
            content=last_resp_bytes if last_resp_bytes is not None
            else b'{"error":{"type":"api_error","message":"codex-bridge: no response"}}',
            status_code=last_status,
            media_type="application/json",
        )

    return app


async def _proxy_buffered(url, params, headers, body, method):
    """Non-streaming forward. Returns (status, body_bytes, headers_dict)."""
    timeout = httpx.Timeout(connect=15.0, read=600.0, write=60.0, pool=15.0)
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            r = await client.request(method, url, params=params, headers=headers,
                                     content=body)
        if r.status_code >= 400:
            _LOG.warning("upstream %s on %s: %s", r.status_code, url,
                         r.content[:800].decode("utf-8", "replace"))
        else:
            _sniff_usage(r.content)
        return r.status_code, r.content, dict(r.headers)
    except httpx.HTTPError as e:
        _LOG.warning("upstream network error: %s", e)
        return 502, (f'{{"error":{{"type":"network_error","message":"{e}"}}}}'
                     ).encode(), {}


async def _proxy_streaming(url, params, headers, body, method):
    """Streaming forward.

    On a 2xx upstream, returns a StreamingResponse that relays the SSE bytes.
    On a non-2xx upstream, drains a bounded error body and returns
    (status, body_bytes, headers_dict) so the caller can classify/rotate.
    """
    timeout = httpx.Timeout(connect=15.0, read=600.0, write=60.0, pool=15.0)
    client = httpx.AsyncClient(timeout=timeout)
    try:
        req = client.build_request(method, url, params=params, headers=headers,
                                   content=body)
        upstream = await client.send(req, stream=True)
    except httpx.HTTPError as e:
        await client.aclose()
        _LOG.warning("upstream stream error: %s", e)
        return 502, f'{{"error":{{"type":"network_error","message":"{e}"}}}}'.encode(), {}

    if upstream.status_code >= 400:
        body_bytes = await upstream.aread()
        hdrs = dict(upstream.headers)
        await upstream.aclose()
        await client.aclose()
        _LOG.warning("upstream %s on %s: %s", upstream.status_code, url,
                     body_bytes[:800].decode("utf-8", "replace"))
        return upstream.status_code, body_bytes[:65536], hdrs

    media = upstream.headers.get("content-type", "text/event-stream")
    out_headers = {k: v for k, v in upstream.headers.items()
                   if k.lower() not in _STRIP_OUT}

    async def event_stream():
        tail = bytearray()  # keep a bounded tail to sniff the final usage block
        try:
            async for chunk in upstream.aiter_bytes():
                tail.extend(chunk)
                if len(tail) > 32768:
                    del tail[:-32768]
                yield chunk
        finally:
            try:
                _sniff_usage(bytes(tail))
            except Exception:  # noqa: BLE001
                pass
            await upstream.aclose()
            await client.aclose()

    return StreamingResponse(event_stream(), status_code=upstream.status_code,
                             headers=out_headers, media_type=media)
