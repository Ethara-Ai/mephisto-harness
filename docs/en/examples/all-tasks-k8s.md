---
title: "All Tasks (Kubernetes)"
---

# All Tasks (Kubernetes)

Run the full EdgeBench suite (~50 tasks) across a Kubernetes cluster.

::: tip Official leaderboard settings
The experiment YAMLs in this example are the **official EdgeBench leaderboard settings** (12-hour budget, stop hook + auto-eval enabled, resource limits as given). For results comparable to the leaderboard, change only `env`, `model`, and registry values.
:::

::: warning Cost
With frontier models (e.g. Claude Opus), one task over the full 12-hour budget can cost **hundreds to over a thousand USD** in API usage; a full ~50-task run is a five-figure spend. Gauge your burn rate on one task with a short `--timeout` first.
:::

## Prerequisites

| Requirement | Check |
|-------------|-------|
| Linux host with `kubectl` configured | `kubectl cluster-info` |
| NetworkPolicy support (for network isolation) | CNI enforces NetworkPolicy; kubeconfig can create/delete `NetworkPolicy` in the target namespace |
| Docker Engine (for pushing images) | `docker run hello-world` |
| Python >= 3.10 | `python --version` |
| A container registry reachable from K8s nodes | e.g. `<registry-ip>:5000` |

## Step-by-step

### 1. Install SForge

```bash
pip install sforge
```

### 2. Fetch task definitions

```bash
sforge fetch-tasks edgebench
sforge list            # verify tasks are visible
```

### 3. Push images to the cluster registry

K8s pods pull images at runtime. Pulling from Docker Hub or other public
registries is too slow and will severely impact agent performance — image
pulls can take minutes per task and eat into the evaluation budget. You
should push all images to a private registry **within the same VPC** as
your K8s cluster beforehand.

```bash
# Pull pre-built images from the public registry
sforge pull --all --registry seededge

# Push to your private registry
sforge push --all --registry <registry-ip>:5000
```

Verify an image is available in your registry:

```bash
curl -s http://<registry-ip>:5000/v2/_catalog | head
```

<details>
<summary>Setting up a private Docker registry</summary>

If you don't already have a private registry, you can start one with a
single command:

```bash
docker run -d -p 5000:5000 --restart=always --name registry registry:2
```

**Configuring insecure (HTTP) registries:** By default Docker only trusts
HTTPS registries. For a plain HTTP registry on your LAN, you need to
configure every machine that pushes or pulls (including K8s nodes) to
trust it:

1. Edit `/etc/docker/daemon.json` (create if it doesn't exist):

   ```json
   {
     "insecure-registries": ["<registry-ip>:5000"]
   }
   ```

2. Restart Docker:

   ```bash
   sudo systemctl restart docker
   ```

3. For K8s nodes using containerd, add the registry to
   `/etc/containerd/config.toml` **on every node in the cluster**
   (pods can be scheduled to any node):

   ```toml
   [plugins."io.containerd.grpc.v1.cri".registry.configs."<registry-ip>:5000".tls]
     insecure_skip_verify = true
   ```

   Then restart containerd: `sudo systemctl restart containerd`

</details>

### 4. Set up the judge server

Start the judge server and set `--judge-url` to the host's IP address
that K8s pods can reach (not `localhost` or `host.docker.internal`):

```bash
sforge serve --port 8080
```

### 5. Configure LLM-graded tasks

The `college_english_exam_bank` task uses an LLM to grade agent submissions.
Its judge container calls out to a model API, so it needs credentials
passed via `SFORGE_JUDGE_EXTRA_ENV`.

Set this **before starting the judge server**:

```bash
export SFORGE_JUDGE_EXTRA_ENV="SFORGE_JUDGE_API_KEY=your-key,SFORGE_JUDGE_API_BASE_URL=https://api.openai.com/v1,SFORGE_JUDGE_MODEL=gpt-5.5"
sforge serve --port 8080
```

| Variable (inside judge container) | Purpose |
|-----------------------------------|---------|
| `SFORGE_JUDGE_API_KEY` | API key the grading script uses to call the LLM |
| `SFORGE_JUDGE_API_BASE_URL` | Base URL of the LLM endpoint for grading |
| `SFORGE_JUDGE_MODEL` | Model ID used by the grading script |

Non-LLM-graded tasks ignore these variables, so it is safe to set them
unconditionally for all tasks.

### 6. Run the experiment

The [`experiment.yaml`](https://github.com/ByteDance-Seed/EdgeBench/blob/main/examples/all-tasks-k8s/experiment.yaml) defines the
full EdgeBench suite — all tasks, per-task overrides, model config, and
resource limits. See [Experiment YAML Walkthrough](#experiment-yaml-walkthrough)
below for details.

```bash
sforge run --experiment experiment.yaml \
  --judge-url http://<judge-host-ip>:8080 \
  --run-id edgebench-001
```

This launches all tasks staggered over 600 seconds total (the delay is
evenly divided among tasks). Monitor progress with:

```bash
sforge visualizer
# Open http://127.0.0.1:8000
```

Or watch a specific task's log:

```bash
tail -f logs/runs/*/ad_placement_optimization/agent_output.txt
```


## Experiment YAML Walkthrough

The `experiment.yaml` in this directory is annotated with comments. Key
sections:

### `env:`

Environment variables injected into the host process before parsing the
rest of the config. Most important for K8s:

```yaml
env:
  SFORGE_K8S_IMAGE_REGISTRY: "<registry-ip>:5000"   # REQUIRED for k8s
```

### `stagger:`

Seconds between launching consecutive tasks. With 50+ tasks, launching
them all at once causes API rate-limit storms and K8s scheduling pressure.
600 seconds (10 minutes) is a safe default. Set to `0` to launch all
simultaneously.

### `model:`

```yaml
model:
  api_key: "sk-xxxx"
  model: claude-opus-4-8

  # Only needed for third-party / self-hosted endpoints.
  # Omit when using the Anthropic API directly.
  # api_base_url: "https://api.deepseek.com/anthropic"
```

### `defaults:`

Applied to every task unless overridden per-task.

### Per-task overrides

```yaml
tasks:
  smt_solver:
    work_cpu_limit: 16       # needs more CPU than the default 4
    work_mem_limit: "16g"
  anchorhead_text_adventure:
    submission_cooldown: 0   # game-mode task, no cooldown
  carleson_formalization: *lean_task   # YAML anchor for Lean tasks
```

### YAML anchors

Shared override blocks can be defined with `x-` prefix and referenced with
`*`:

```yaml
x-lean-task: &lean_task
  work_cpu_limit: 8
  work_mem_limit: "16g"
  judge_cpu_limit: 8
  judge_mem_limit: "16g"

tasks:
  carleson_formalization: *lean_task
  pfr_formalization: *lean_task
```


## Other Experiment Configs

The examples directory includes additional experiment configs for other
agents and third-party models:

- [`experiment-codex.yaml`](https://github.com/ByteDance-Seed/EdgeBench/blob/main/examples/all-tasks-k8s/experiment-codex.yaml) — Codex with GPT-5.5
- [`experiment-deepseek.yaml`](https://github.com/ByteDance-Seed/EdgeBench/blob/main/examples/all-tasks-k8s/experiment-deepseek.yaml) — Claude Code with DeepSeek V4 Pro (1M context)
- [`experiment-glm.yaml`](https://github.com/ByteDance-Seed/EdgeBench/blob/main/examples/all-tasks-k8s/experiment-glm.yaml) — Claude Code with GLM 5.1 (200K context)

```bash
sforge run --experiment experiment-codex.yaml \
  --judge-url http://<judge-host-ip>:8080 \
  --run-id edgebench-codex-001
```

For a detailed explanation of the Claude Code third-party model settings (cache optimization, model routing variables, context window configuration), see [Single Task (Docker)](/en/examples/single-task-docker#using-a-third-party-model).

## K8s-Specific Environment Variables

| Variable | Required | Purpose |
|----------|----------|---------|
| `SFORGE_K8S_IMAGE_REGISTRY` | **Yes** | Registry that K8s pods pull images from. Backend init fails without it. |
| `SFORGE_K8S_NAMESPACE` | No (default: `default`) | Kubernetes namespace for pods |
| `SFORGE_K8S_KUBECONFIG` | No | Path to kubeconfig file (uses default context if omitted) |
| `SFORGE_K8S_NODE_SELECTOR` | No | Node selector for pods, format: `"key1=val1,key2=val2"` |

For all other environment variables, see [Environment Variables](/en/configuration/environment-variables).
