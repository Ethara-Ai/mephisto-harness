# Example: Run a Single Task on Local Docker

Run one EdgeBench task (`ad_placement_optimization`) on your local machine using Docker.

> **Scale:** The Docker backend is meant for trying out a **small number of
> tasks**. Running many tasks concurrently on one host (roughly 20+)
> will exhaust even a high-end server. For full-suite runs use the
> [Kubernetes example](../all-tasks-k8s/) with the official settings.

> **Cost:** frontier-model runs are expensive — one task over the official
> 12-hour budget can cost hundreds to over a thousand USD in API usage.
> Start with a short `--timeout` (this example uses 2 hours) to gauge your
> burn rate before scaling up.

## Prerequisites

| Requirement | Check |
|-------------|-------|
| Linux host | - |
| Docker Engine running | `docker run hello-world` |
| Python >= 3.10 | `python --version` |

> **Note:** The Docker backend needs direct access to the host Docker daemon.
> Running SForge itself inside a container introduces Docker-in-Docker issues.

## Using Claude Code with Anthropic API

### 1. Install SForge

```bash
pip install sforge
```

### 2. Fetch task definitions

```bash
sforge fetch-tasks edgebench
```

Downloads the EdgeBench task JSONs and `BENCHMARK.yaml` into `./tasks/`.
Verify with:

```bash
sforge list
```

### 3. Pull pre-built images

```bash
sforge pull --task ad_placement_optimization --registry seededge
```

This pulls the base, work, and judge images from the public registry:

- `edgebench.base.cpp:<hash>`
- `edgebench.work.ad_placement_optimization:<hash>`
- `edgebench.judge.ad_placement_optimization:<hash>`

### 4. Start the judge server

Open a **separate terminal**:

```bash
sforge serve
```

Listens on `0.0.0.0:8080` by default. The judge server receives archives
from the agent, runs them through the hidden test suite in ephemeral judge
containers, and returns scores.

### 5. Run the agent

```bash
SFORGE_AGENT_API_KEY="sk-ant-xxxx" \
sforge run --task ad_placement_optimization --agent claude-code \
  --model claude-opus-4-8[1m] \
  --timeout 7200 \
  --run-id ad-placement-optimization-001
```

This launches Claude Opus 4.8 to work on the task for 2 hours.
You will see the agent's work output streamed to stdout in real time.

### 6. View results

You can view the progress in real time via the built-in web UI:

```bash
sforge visualizer
# Open http://127.0.0.1:8000
```

Or inspect files directly:

```bash
ls logs/runs/*/ad_placement_optimization/
cat logs/runs/*/ad_placement_optimization/final_result.json
```


## Using a Third-Party Model

To evaluate a non-Anthropic model, point the API base URL at the
third-party provider and set the model ID accordingly:

```bash
SFORGE_AGENT_API_KEY="your-deepseek-key" \
SFORGE_AGENT_API_BASE_URL="https://api.deepseek.com/anthropic" \
sforge run --task ad_placement_optimization --agent claude-code \
  --model deepseek-v4-pro[1m] \
  --timeout 7200 \
  --run-id ad-placement-optimization-001
```

When using a third-party endpoint, there are three things to configure
beyond the API key and base URL:

### 1. Prompt cache optimization (`SFORGE_CLAUDE_CACHE_OPT=1`)

Third-party APIs typically don't recognize Claude Code's attribution
headers and dynamic system-prompt sections. These change across requests
and cause prefix cache misses, wasting tokens. Setting
`SFORGE_CLAUDE_CACHE_OPT=1` strips those dynamic sections so the prompt
prefix stays stable and cacheable.

### 2. Model routing environment variables

Claude Code internally dispatches to different model tiers
(opus/sonnet/haiku) for subagent calls. By default these resolve to
Anthropic model IDs. Override **all** of them so every internal call
routes to your third-party model:

| Variable | Purpose |
|----------|---------|
| `ANTHROPIC_MODEL` | Primary model used by Claude Code |
| `ANTHROPIC_DEFAULT_OPUS_MODEL` | Model for opus-tier calls |
| `ANTHROPIC_DEFAULT_SONNET_MODEL` | Model for sonnet-tier calls |
| `ANTHROPIC_DEFAULT_HAIKU_MODEL` | Model for haiku-tier calls |
| `CLAUDE_CODE_SUBAGENT_MODEL` | Model for subagent spawning |

### 3. Context window configuration

**For models with 1M context:** Append `[1m]` to the model name to
enable Claude Code's 1M context mode (e.g., `deepseek-v4-pro[1m]`).
Without this suffix, Claude Code defaults to the 200K context window.

**For models with 200K context (or smaller):** Set these variables to
prevent Claude Code from exceeding the context limit:

| Variable | Value | Purpose |
|----------|-------|---------|
| `CLAUDE_CODE_AUTO_COMPACT_WINDOW` | `200000` | Context window size in tokens |
| `CLAUDE_AUTOCOMPACT_PCT_OVERRIDE` | `80` | Trigger compaction at 80% usage |

Without these settings, Claude Code may attempt to fill a larger default
context window and hit errors when the third-party model has a smaller
limit.

### Example A: DeepSeek V4 Pro (1M context)

DeepSeek V4 Pro supports 1M context. Append `[1m]` to the model name:

```bash
export SFORGE_AGENT_API_KEY="your-deepseek-key"
export SFORGE_AGENT_API_BASE_URL="https://api.deepseek.com/anthropic"
export SFORGE_CLAUDE_CACHE_OPT=1
export SFORGE_AGENT_EXTRA_ENV="ANTHROPIC_MODEL=deepseek-v4-pro[1m],ANTHROPIC_DEFAULT_OPUS_MODEL=deepseek-v4-pro[1m],ANTHROPIC_DEFAULT_SONNET_MODEL=deepseek-v4-pro[1m],ANTHROPIC_DEFAULT_HAIKU_MODEL=deepseek-v4-pro[1m],CLAUDE_CODE_SUBAGENT_MODEL=deepseek-v4-pro[1m]"

sforge run --task ad_placement_optimization --agent claude-code \
  --model deepseek-v4-pro[1m] \
  --timeout 7200 \
  --run-id ad-placement-deepseek-001
```

### Example B: GLM 5.1 (200K context)

GLM 5.1 has a 200K context window. Set the compaction variables to
prevent context overflow:

```bash
export SFORGE_AGENT_API_KEY="your-glm-key"
export SFORGE_AGENT_API_BASE_URL="https://open.bigmodel.cn/anthropic"
export SFORGE_CLAUDE_CACHE_OPT=1
export SFORGE_AGENT_EXTRA_ENV="ANTHROPIC_MODEL=glm-5.1,ANTHROPIC_DEFAULT_OPUS_MODEL=glm-5.1,ANTHROPIC_DEFAULT_SONNET_MODEL=glm-5.1,ANTHROPIC_DEFAULT_HAIKU_MODEL=glm-5.1,CLAUDE_CODE_SUBAGENT_MODEL=glm-5.1,CLAUDE_CODE_AUTO_COMPACT_WINDOW=200000,CLAUDE_AUTOCOMPACT_PCT_OVERRIDE=80"

sforge run --task ad_placement_optimization --agent claude-code \
  --model glm-5.1 \
  --timeout 7200 \
  --run-id ad-placement-glm-001
```


## Network Isolation

Each EdgeBench task JSON has an `internet` field that controls whether the
agent can access the public internet. Most tasks set `internet: false`.
You can override this globally with CLI flags:

```bash
# Force internet off (even if the task JSON allows it)
sforge run --task ad_placement_optimization --agent claude-code \
  --disable-internet ...

# Force internet on (even if the task JSON blocks it)
sforge run --task ad_placement_optimization --agent claude-code \
  --enable-internet ...
```

<details>
<summary>How Docker network isolation works</summary>

When internet is disabled, SForge creates **per-container iptables chains**
on the host (`SFORGE_<container-id-prefix>`) that whitelist only the
endpoints the agent needs (judge server + LLM API) and DROP everything
else. The rules live in the host network namespace and cannot be modified
from inside the container (it has no `NET_ADMIN` capability). IPv6 is
blocked entirely.

The chain name format is `SFORGE_<first 12 chars of container ID>`. Jump
rules are inserted into `DOCKER-USER`, `INPUT`, and (for IPv6) `FORWARD`.

> **Note:** This only affects the Docker backend. The K8s backend uses
> Kubernetes NetworkPolicy for isolation, which is managed by the cluster
> and does not leave host-level residue.

</details>

<details>
<summary>Cleaning up stale iptables rules after abnormal exit</summary>

SForge cleans up iptables chains automatically when the run finishes
normally. However, if the process is **killed abnormally** (e.g. `kill -9`,
machine crash, OOM), stale chains remain in the host iptables.

**Automatic cleanup:** SForge checks for stale chains at the start of
every `sforge run`. It lists all `SFORGE_*` chains, checks whether the
corresponding container still exists, and removes orphaned chains. So
simply starting a new run will clean up leftovers from previous crashes.

**Manual cleanup:** If you need to clean up immediately:

```bash
# List stale SFORGE chains
sudo iptables -L -n | grep 'Chain SFORGE_'

# For each stale chain, flush and delete:
sudo iptables -F SFORGE_xxxxxxxxxxxx
sudo iptables -X SFORGE_xxxxxxxxxxxx
```

You also need to remove the jump rules from parent chains that reference
the stale chain:

```bash
sudo iptables -S DOCKER-USER | grep SFORGE_
sudo iptables -S INPUT | grep SFORGE_

# Delete by replacing -A with -D:
# e.g. "-A DOCKER-USER -s 172.17.0.2/32 -j SFORGE_abc123def456"
sudo iptables -D DOCKER-USER -s 172.17.0.2/32 -j SFORGE_abc123def456
```

Or flush all SForge chains at once:

```bash
for chain in $(sudo iptables -L -n | grep -oP 'SFORGE_[0-9a-f]{12}'); do
  sudo iptables -S DOCKER-USER 2>/dev/null | grep "$chain" | sed 's/^-A/-D/' | while read rule; do sudo iptables $rule; done
  sudo iptables -S INPUT 2>/dev/null | grep "$chain" | sed 's/^-A/-D/' | while read rule; do sudo iptables $rule; done
  sudo iptables -F "$chain" 2>/dev/null
  sudo iptables -X "$chain" 2>/dev/null
done
```

</details>


### LLM-Graded Tasks

Some tasks use an LLM to grade submissions instead of deterministic tests.
In EdgeBench, the **Professional Knowledge Work** tasks
(`college_english_exam_bank`) runs a grading script (`grade_with_codex.py`)
inside the judge container that calls out to a model API.

These tasks require API credentials passed into the judge container via
`SFORGE_JUDGE_EXTRA_ENV`. Set this **before starting the judge server**:

```bash
export SFORGE_JUDGE_EXTRA_ENV="SFORGE_JUDGE_API_KEY=your-key,SFORGE_JUDGE_API_BASE_URL=https://api.openai.com/v1,SFORGE_JUDGE_MODEL=gpt-5.5"
sforge serve
```

| Variable (inside judge container) | Purpose |
|-----------------------------------|---------|
| `SFORGE_JUDGE_API_KEY` | API key the grading script uses to call the LLM |
| `SFORGE_JUDGE_API_BASE_URL` | Base URL of the LLM endpoint for grading |
| `SFORGE_JUDGE_MODEL` | Model ID used by the grading script |

Non-LLM-graded tasks (like `ad_placement_optimization`) ignore these variables,
so it is safe to set them unconditionally.
