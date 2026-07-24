"""Codex ChatGPT-subscription bridge for the EdgeBench harness.

Routes OpenAI Responses-API traffic (from the containerized ``codex`` CLI)
through the user's ChatGPT subscription OAuth token instead of an API key, by:

  1. Reading OAuth credentials from ``${CODEX_HOME:-~/.codex}/auth.json`` (or a
     pooled/exported auth.json), and refreshing them via ``auth.openai.com``.
  2. Exposing an OpenAI-compatible ``/v1/responses`` server that forwards to the
     ChatGPT backend with the OAuth bearer + ``ChatGPT-Account-Id`` header.

This is the OpenAI twin of ``claude_oauth``. See ``run_trajectory_codex.sh``.
"""

from .credentials import (
    CodexCredentials,
    CredentialProvider,
    CredentialsError,
    MultiAccountCredentialProvider,
    load_account_pool,
    load_credentials,
    refresh_credentials,
)

__all__ = [
    "CodexCredentials",
    "CredentialProvider",
    "CredentialsError",
    "MultiAccountCredentialProvider",
    "load_account_pool",
    "load_credentials",
    "refresh_credentials",
]
