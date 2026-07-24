"""CLI entry: ``python -m codex_oauth [--host H] [--port N] [--check]``."""

from __future__ import annotations

import argparse
import logging
import sys

from .bridge import _resolve_provider, build_app
from .credentials import CredentialsError


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m codex_oauth")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=9091)
    p.add_argument("--log-level", default="info")
    p.add_argument(
        "--check",
        action="store_true",
        help="Verify credentials load successfully, then exit.",
    )
    args = p.parse_args(argv)

    logging.basicConfig(
        level=args.log_level.upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    provider = _resolve_provider()
    try:
        creds = provider.get_credentials()
    except CredentialsError as e:
        print(f"[codex-bridge] credentials error: {e}", file=sys.stderr)
        return 2

    print(f"[codex-bridge] credentials OK "
          f"(account: {creds.account_id}, token: {creds.access_token[:15]}...)")
    if args.check:
        return 0

    try:
        import uvicorn
    except ImportError:
        print("[codex-bridge] uvicorn not installed; cannot serve", file=sys.stderr)
        return 3

    print(f"[codex-bridge] listening on http://{args.host}:{args.port}")
    print("[codex-bridge] point codex at:")
    print(f"           export OPENAI_BASE_URL=http://{args.host}:{args.port}/v1")
    print("           export OPENAI_API_KEY=$WCB_CODEX_BRIDGE_SECRET")
    uvicorn.run(
        build_app(provider),
        host=args.host,
        port=args.port,
        log_level=args.log_level,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
