#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Run an SForge trajectory through the vendored Claude Code OAuth bridge, using
# THIS machine's own Claude subscription. Portable: no absolute paths, no
# secrets — every teammate runs the same script with their own credential.
#
# The bridge reads your OAuth token from your OS credential store (macOS
# Keychain, or ~/.claude/.credentials.json on Linux), AUTO-REFRESHES it, and
# forwards agent traffic to api.anthropic.com on your Max/Pro plan. A fresh
# random secret gates each run so no other local process can spend your quota.
#
# USAGE:
#   export SFORGE_TASKS_DIR=/abs/path/to/a/tasks-dir-with-BENCHMARK.yaml
#   ./oauth-bridge/run_via_oauth_bridge.sh <task_id> [run_id] [timeout_seconds]
#
# ENV OVERRIDES:
#   SFORGE_TASKS_DIR      (required) tasks dir containing <task_id>.json + BENCHMARK.yaml
#   MODEL                 default claude-opus-4-8
#   BRIDGE_PORT           default 8765
#   WCB_CC_ACCOUNT_POOL   optional: colon-separated OAuth cred JSON files for
#                         multi-account failover across a 5-hour cap
#   EXTRA_RUN_ARGS        optional: extra args appended verbatim to `sforge run`.
#                         Used by scripts/probe_difficulty.sh to pass
#                         `--max-submissions 1` for the one-pass author-side
#                         probe (requirements/MEPHISTO.md §3.1). Word-split on
#                         purpose, so quote per-arg values simply.
#   NET_MODE              optional: `--enable-internet` (default, matches the
#                         reference runbook) or `--disable-internet`. A probe
#                         should prefer disable so the agent cannot fetch a
#                         published solution; note that needs sudo iptables and
#                         that the judge + this bridge stay reachable either way.
# ---------------------------------------------------------------------------
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"   # .../oauth-bridge
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"                    # sforge repo root

TASK="${1:?usage: run_via_oauth_bridge.sh <task_id> [run_id] [timeout]}"
RUN_ID="${2:-${TASK}-bridge}"
TIMEOUT="${3:-1800}"
MODEL="${MODEL:-claude-opus-4-8}"
BRIDGE_PORT="${BRIDGE_PORT:-8765}"
: "${SFORGE_TASKS_DIR:?set SFORGE_TASKS_DIR to a tasks dir (must contain BENCHMARK.yaml)}"

# python: prefer the repo venv (where sforge + bridge deps live), else system python3
PY="python3"; [ -x "$REPO_ROOT/.venv/bin/python" ] && PY="$REPO_ROOT/.venv/bin/python"

# --- preconditions ----------------------------------------------------------
docker info >/dev/null 2>&1 || { echo "ERROR: Docker not running." >&2; exit 1; }
"$PY" -c "import fastapi,uvicorn,httpx" 2>/dev/null || {
  echo "ERROR: bridge deps missing. Run: $PY -m pip install -r $SCRIPT_DIR/requirements.txt" >&2; exit 1; }
"$PY" -m claude_oauth --check >/dev/null 2>&1 || {
  cd "$SCRIPT_DIR"; PYTHONPATH="$SCRIPT_DIR" "$PY" -m claude_oauth --check 2>&1 | tail -3
  echo "ERROR: no Claude credential found. Sign in first:  claude   (then /login)" >&2; exit 1; }

# --- ephemeral per-run secret (gates who may spend this subscription) --------
BRIDGE_SECRET="$(openssl rand -hex 32 2>/dev/null || "$PY" -c 'import secrets;print(secrets.token_hex(32))')"

# --- launch the bridge (bind 0.0.0.0 so the work container reaches it via
#     host.docker.internal). claude-code is a first-class CLI client, so the
#     third-party-app workarounds are disabled. -------------------------------
echo "[bridge] starting on 0.0.0.0:$BRIDGE_PORT (log: /tmp/wcb-bridge.log)"
( cd "$SCRIPT_DIR" && PYTHONPATH="$SCRIPT_DIR" \
    WCB_CC_BRIDGE_SECRET="$BRIDGE_SECRET" \
    WCB_CC_BILLING_ATTRIBUTION=0 \
    WCB_CC_TOOL_RENAME=0 \
    ${WCB_CC_ACCOUNT_POOL:+WCB_CC_ACCOUNT_POOL="$WCB_CC_ACCOUNT_POOL"} \
    "$PY" -m claude_oauth --host 0.0.0.0 --port "$BRIDGE_PORT" >/tmp/wcb-bridge.log 2>&1 ) &
BRIDGE_PID=$!
trap 'echo "[bridge] stopping"; kill $BRIDGE_PID 2>/dev/null || true' EXIT INT TERM

# --- wait for health --------------------------------------------------------
for i in $(seq 1 30); do
  curl -s -o /dev/null --max-time 2 "http://127.0.0.1:$BRIDGE_PORT/healthz" && break
  sleep 1
done
curl -s -o /dev/null --max-time 2 "http://127.0.0.1:$BRIDGE_PORT/healthz" || {
  echo "ERROR: bridge not healthy; see /tmp/wcb-bridge.log" >&2; tail -5 /tmp/wcb-bridge.log >&2; exit 2; }

# --- preflight one request THROUGH the bridge (proves the whole chain) -------
code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 30 \
  "http://127.0.0.1:$BRIDGE_PORT/v1/messages" -H "x-api-key: $BRIDGE_SECRET" \
  -H "anthropic-version: 2023-06-01" -H "content-type: application/json" \
  -d '{"model":"'"$MODEL"'","max_tokens":4,"messages":[{"role":"user","content":"ping"}]}')"
echo "[bridge] preflight -> HTTP $code  (200/400 ok · 401 secret-mismatch · 429 cap)"
[ "$code" = 401 ] && { echo "ERROR: bridge rejected its own secret." >&2; exit 3; }

# --- point sforge's agent at the bridge and run -----------------------------
cd "$REPO_ROOT"
export SFORGE_AGENT_API_BASE_URL="http://host.docker.internal:$BRIDGE_PORT"
export SFORGE_AGENT_API_KEY="$BRIDGE_SECRET"     # -> ANTHROPIC_AUTH_TOKEN in container; bridge validates it
unset CLAUDE_CODE_OAUTH_TOKEN SFORGE_AGENT_EXTRA_ENV 2>/dev/null || true

NET_MODE="${NET_MODE:---enable-internet}"
echo "[run] task=$TASK run_id=$RUN_ID timeout=${TIMEOUT}s model=$MODEL net=$NET_MODE (via bridge, subscription auth)"
[ -n "${EXTRA_RUN_ARGS:-}" ] && echo "[run] extra args: $EXTRA_RUN_ARGS"
# shellcheck disable=SC2086  # EXTRA_RUN_ARGS is intentionally word-split
"$PY" -m sforge run --task "$TASK" \
  --agent claude-code --model "$MODEL" \
  --timeout "$TIMEOUT" "$NET_MODE" \
  --work-cpu-limit 4 --work-mem-limit 8g \
  --run-id "$RUN_ID" ${EXTRA_RUN_ARGS:-}
