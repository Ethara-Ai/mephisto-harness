# Claude Code OAuth Bridge — team setup

Run SForge trajectories on **your own Claude Max/Pro subscription** (no API key).
Each teammate runs their own bridge, reading their own subscription from their own
machine. **No tokens or secrets are ever shared or committed.**

## Why a bridge (vs. a raw token)

A raw `CLAUDE_CODE_OAUTH_TOKEN` is a frozen access token — it **expires mid-run**
(→ 401) and can't survive a usage cap. The bridge holds your **refresh** token and
mints fresh access tokens on demand, so runs don't die on auth, and (with a
multi-account pool) can fail over when one account hits its 5-hour cap.

```
claude-code (sforge work container)
  ANTHROPIC_BASE_URL = http://host.docker.internal:8765   (SFORGE_AGENT_API_BASE_URL)
  Authorization: Bearer <random per-run secret>           (SFORGE_AGENT_API_KEY)
    │
    ▼
oauth-bridge (your host :8765)   ── validates the secret (hmac), swaps in an
    │                               auto-refreshed OAuth token from YOUR Keychain
    ▼
api.anthropic.com  (billed on YOUR Max/Pro plan)
```

---

## What's in this folder (all committed — none of it is secret)

| File | Purpose |
|---|---|
| `claude_oauth/` | the bridge itself (Anthropic-compatible proxy) |
| `requirements.txt` | its 3 deps: fastapi, uvicorn, httpx |
| `run_via_oauth_bridge.sh` | launcher: starts the bridge → preflights → runs the task → tears down |
| `BRIDGE_SETUP.md` | this file |
| `.gitignore` | belt-and-suspenders: never commit credential-shaped files |

---

## One-time setup (each teammate, on their own machine)

**1. Sign in to Claude Code with your subscription** — this is what puts your OAuth
token in your OS credential store. Either the Claude Code desktop app, or the CLI:

```bash
claude            # then run /login and sign in with your Max/Pro account
```

- **macOS:** the token lands in the Keychain (service `Claude Code-credentials`).
- **Linux:** the CLI writes `~/.claude/.credentials.json`.

The bridge auto-discovers both. Verify:

```bash
cd <repo-root>/oauth-bridge
PYTHONPATH=. python3 -m claude_oauth --check
# -> [bridge] credentials OK (token prefix: sk-ant-oat01-...)
```

**2. Install the bridge deps** into the same venv you run sforge from:

```bash
.venv/bin/pip install -r oauth-bridge/requirements.txt
```

That's it. Nothing to configure, no secret to set — the launcher generates a fresh
one each run.

---

## Running a trajectory

```bash
export SFORGE_TASKS_DIR=/abs/path/to/tasks-dir     # must contain <task_id>.json + BENCHMARK.yaml
./oauth-bridge/run_via_oauth_bridge.sh <task_id> [run_id] [timeout_seconds]
```

Example:

```bash
export SFORGE_TASKS_DIR="$PWD/run-h11-variant"
./oauth-bridge/run_via_oauth_bridge.sh h11_state_machine_coupling_variant h11-bridge-1 1800
```

The script: mints a per-run secret → launches the bridge (`0.0.0.0:8765`) →
health-checks → sends **one** request *through* the bridge to prove auth →
points sforge at it → runs → stops the bridge on exit.

**Healthy signals in the sforge output:** `Registered session with judge server`,
real assistant turns, **no `401`** (dead credential) and **no `429`** (cap).

> A separate judge server is still required for auto-eval:
> `SFORGE_TASKS_DIR=… python -m sforge serve --host 0.0.0.0 --port 8080`

---

## Security model — what is shared vs. private

| | |
|---|---|
| **Committed to the repo** | bridge code, deps, launcher, docs — all non-secret |
| **Stays on each machine, NEVER committed** | the OAuth token (in the OS credential store), the per-run secret (ephemeral, in memory), the refresh cache (`~/.cache/wildclawbench/`) |
| **Who can spend a subscription** | only a process that presents that run's random secret; the bridge binds loopback+`host.docker.internal` and rejects anything else with 401 |

Each teammate spends **only their own** subscription. There is no shared credential.

---

## Optional: survive the 5-hour cap with multiple accounts

If a teammate has more than one subscription (or the team pools a few), point the
bridge at several credential JSON files; it fails over automatically when one caps:

```bash
export WCB_CC_ACCOUNT_POOL="$HOME/.wcb/acct_a.json:$HOME/.wcb/acct_b.json"
./oauth-bridge/run_via_oauth_bridge.sh <task_id> ...
```

Each file is `{"claudeAiOauth": {"accessToken":..., "refreshToken":..., "expiresAt":...}}`.
Keep these **outside the repo** (e.g. `~/.wcb/`), chmod 600.

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| `no Claude credential found` | Sign in: `claude` → `/login`. Then re-run `--check`. |
| `bridge deps missing` | `.venv/bin/pip install -r oauth-bridge/requirements.txt` |
| sforge shows `401` | Your credential is invalid/expired at the OS level — re-login to Claude Code. |
| sforge shows `429` | Subscription cap hit. Wait for the 5-hour reset, or set `WCB_CC_ACCOUNT_POOL`. |
| container can't reach bridge | Ensure the run uses `--enable-internet` and the bridge bound `0.0.0.0`. |
| `bridge not healthy` | Check `/tmp/wcb-bridge.log`. |

---

*The `claude_oauth/` package is vendored from the WildClawBench project (Apache-2.0);
license headers are preserved in each file.*
