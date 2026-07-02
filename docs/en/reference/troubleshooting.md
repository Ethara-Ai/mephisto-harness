---
title: Troubleshooting
---

# Troubleshooting

## Network Issues (Most Common)

The vast majority of SForge failures are caused by network connectivity problems during Docker image builds or agent runtime. The table below maps symptoms to solutions:

| Symptom | Stage | Solution |
|---------|-------|----------|
| Docker Hub pull timeout | Build | Configure Docker daemon proxy or registry mirrors in `/etc/docker/daemon.json` |
| `pip install` timeout | Build | Set `SFORGE_PYPI_INDEX_URL` to a PyPI mirror |
| `apt-get update` timeout | Build | Set `SFORGE_APT_MIRROR_URL` to an APT mirror |
| `git clone` GitHub timeout | Build | Set `SFORGE_HTTP_PROXY` / `SFORGE_HTTPS_PROXY`, or use `SFORGE_EXTRA_HOSTS` for DNS |
| Maven download timeout | Build | Set `SFORGE_MAVEN_MIRROR_URL` to a Maven mirror |
| Node.js install failure | Run | Set `SFORGE_NODEJS_MIRROR_URL` to a Node.js binary mirror |
| Agent cannot connect to API | Run | Check `SFORGE_AGENT_API_BASE_URL` and ensure the endpoint is reachable from inside the container |
| `sforge-submit` fails with connection error | Run | Verify the Judge server is running (`sforge serve`) and the `--judge-url` is correct |
| Build succeeds but Run fails with network errors | Run | Build and Run configurations are independent --- proxy/mirror settings must be configured for both stages separately |

### Recommended Mirrors by Environment

| Purpose | Recommended Mirror |
|---------|--------------------|
| PyPI | `https://mirrors.aliyun.com/pypi/simple/` |
| APT | `https://mirrors.aliyun.com` |
| Maven | `https://maven.aliyun.com/repository/public` |
| Go | `https://goproxy.cn` |
| Node.js | `https://mirrors.aliyun.com/nodejs-release/` |
| NPM | `https://registry.npmmirror.com` (usually does not need separate configuration) |

### Build Recipe

```bash
# Volcengine ECS can usually connect to Docker Hub directly; configuring registry mirrors is enough
sudo tee /etc/docker/daemon.json <<'EOF'
{
  "registry-mirrors": [
    "https://docker.m.daocloud.io",
    "https://dockerhub.icu",
    "https://docker.chenby.cn"
  ]
}
EOF
sudo systemctl daemon-reload && sudo systemctl restart docker

# SForge build environment variables
export SFORGE_PYPI_INDEX_URL="https://mirrors.ivolces.com/pypi/simple/"
export SFORGE_APT_MIRROR_URL="http://mirrors.ivolces.com"
export SFORGE_MAVEN_MIRROR_URL="https://maven.aliyun.com/repository/public"
export SFORGE_GO_PROXY="https://goproxy.cn"

sforge build --task ad_placement_optimization
```

### Runtime Recipe (General)

At runtime, you usually only need API access and the Node.js mirror used to install Claude Code / Codex Agent:

```bash
export SFORGE_AGENT_API_KEY="sk-ant-..."
export SFORGE_AGENT_API_BASE_URL="https://api.anthropic.com"
export SFORGE_NODEJS_MIRROR_URL="https://mirrors.aliyun.com/nodejs-release/"

sforge run --task ad_placement_optimization --agent claude-code
```

See [Network & Mirrors](/en/configuration/network-setup) for detailed mirror and proxy configuration.

## Build Failures

### Check build logs

Build logs are written to the `logs/build_images/` directory:

```
logs/build_images/
├── base/<benchmark>.base.<base_image>__<hash>/build_image.log
├── work/<benchmark>.work.<task>__<hash>/build_image.log
└── judge/<benchmark>.judge.<task>__<hash>/build_image.log
```

::: tip
When a build fails, always check the log file first. The error message in the terminal is often truncated, while the log file contains the full Docker build output.
:::

### Force rebuild

If an image appears cached but is actually broken, force a clean rebuild:

```bash
sforge build --task ad_placement_optimization --force-rebuild
```

### Common build failures

| Error | Cause | Fix |
|-------|-------|-----|
| `unable to resolve host` | DNS failure inside Docker build | Set `SFORGE_EXTRA_HOSTS` or configure Docker daemon DNS |
| `Could not fetch URL` (pip) | PyPI unreachable | Set `SFORGE_PYPI_INDEX_URL` |
| `E: Failed to fetch` (apt) | APT mirror unreachable | Set `SFORGE_APT_MIRROR_URL` |
| `fatal: unable to access` (git) | GitHub unreachable | Set proxy or use `SFORGE_EXTRA_HOSTS` |
| `COPY failed: file not found` | Dockerfile context issue | Report as a bug |

## Agent Issues

### Agent installation failure

Check the install log:

```bash
cat logs/runs/<run_id>/<task_id>/install_output.txt
```

Common causes:
- Node.js download failure (for Claude Code / Codex): Set `SFORGE_NODEJS_MIRROR_URL`
- NPM package timeout: Set `SFORGE_NPM_REGISTRY_URL`
- Agent CLI install failure: use `SFORGE_NODEJS_MIRROR_URL` and `SFORGE_NPM_REGISTRY_URL` for npm-based agents, or pass agent-specific installer env via `SFORGE_AGENT_EXTRA_ENV`

### Agent stuck or not making progress

Check the agent conversation log:

```bash
# Full output
cat logs/runs/<run_id>/<task_id>/agent_output.txt

# Extract assistant text only (Claude Code format)
jq -r 'select(.type == "assistant") | .message.content[] | select(.type == "text") | .text' \
  logs/runs/<run_id>/<task_id>/agent_output.txt

# See what tools the agent is calling in real time
grep -o '"name":"[^"]*"' logs/runs/<run_id>/<task_id>/agent_output.txt
```

### Agent exiting too early

If the agent exits before the timeout and you want it to keep working, make sure the stop hook is enabled (it is enabled by default for `claude-code` and `codex`):

```bash
# Stop hook is enabled by default; do NOT pass --disable-stop-hook
sforge run --task ad_placement_optimization --agent claude-code
```

### No submissions recorded

If the agent ran but no submissions appear in the history:

1. Check that the Judge server was running during the entire agent session
2. Check `agent_output.txt` for `sforge-submit` invocations
3. If auto-eval was disabled and the agent never called `sforge-submit`, no submissions will exist

## Log Directory Structure

```
logs/
├── build_images/
│   ├── base/
│   │   └── <benchmark>.base.<base_image>__<hash>/
│   │       └── build_image.log
│   ├── work/
│   │   └── <benchmark>.work.<task>__<hash>/
│   │       └── build_image.log
│   └── judge/
│       └── <benchmark>.judge.<task>__<hash>/
│           └── build_image.log
└── runs/
    └── <run_id>/
        ├── run_config.json          # Unified config for the entire run
        ├── summary.json             # Multi-task summary (if applicable)
        └── <task_id>/
            ├── run_config.json      # Per-task effective config
            ├── run_agent.log        # Harness-level log
            ├── install_output.txt   # Agent install output
            ├── agent_prompt.md      # Enhanced prompt
            ├── agent_output.txt     # Full agent conversation
            ├── final_archive.tar.gz # Last code snapshot
            ├── final_result.json    # Best score and run metadata
            ├── run_history.json     # All submission entries
            └── submissions/
                ├── agent-1/         # First manual submission
                │   ├── eval_output.txt
                │   └── eval_report.json
                ├── agent-2/
                ├── auto-1/          # First auto-eval submission
                └── ...
```

## Container Cleanup

SForge automatically cleans up containers on exit (improved in v0.2.2). However, if something goes wrong (e.g., the process is killed with `SIGKILL`), containers may be left running.

### Check for leftover containers

```bash
docker ps --filter "name=sforge"
```

### Stop all SForge containers

```bash
docker ps --filter "name=sforge" -q | xargs -r docker stop
docker ps --filter "name=sforge" -aq | xargs -r docker rm
```

### Network isolation cleanup

When using `--disable-internet`, SForge creates iptables rules to block container traffic. These rules are automatically cleaned up on the next run, but you can also remove them manually:

```bash
# List SForge iptables rules
sudo iptables -L DOCKER-USER -n --line-numbers | grep sforge

# Remove specific rule by line number
sudo iptables -D DOCKER-USER <line_number>
```

## FAQ

**Q: When do I need to force rebuild images?**
A: When you modify `setup_cmds` or `base_image` in the task JSON. The content hash changes automatically, so normally SForge detects this and rebuilds. Use `--force-rebuild` if the image is corrupted or you want a completely clean build.

**Q: Does changing `agent_query` require a rebuild?**
A: No. The agent prompt is injected at runtime, not baked into the Docker image. You can change it freely without rebuilding.

**Q: Can I run multiple tasks in parallel?**
A: Yes. Pass multiple task IDs to `--task`:
```bash
sforge run --task ad_placement_optimization gitlet rookiedb --agent claude-code
```
All tasks run in parallel against a single Judge server instance. The Judge server handles concurrent submissions via threading.

**Q: How do I compare results across runs?**
A: Use the visualizer:
```bash
sforge visualizer --runs-dir logs/runs
```
Or inspect `final_result.json` in each run directory.

**Q: The agent is running but I see no output.**
A: For multi-task runs, verbose output is disabled automatically. Check the per-task log files in `logs/runs/<run_id>/<task_id>/`. For single-task runs, make sure `--silent` is not set.

**Q: How do I increase the evaluation timeout?**
A: The evaluation timeout is set per-task in the JSON (`judge.eval_timeout`). The agent timeout is set via `--timeout` on the CLI. These are independent --- `eval_timeout` controls how long a single test run can take, while `--timeout` controls how long the agent has to work overall.


**Q: What should I do if Docker pull fails?**
A: Configure Docker daemon proxy or registry mirrors. See the "Build Recipe" section above or [Network & Mirrors](/en/configuration/network-setup).
