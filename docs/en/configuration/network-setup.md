---
title: Network Setup
---

# Network Setup

## Default: No Extra Setup

SForge assumes the host and containers can access the public internet. In a normal network environment, you do not need proxy variables, mirror sources, DNS overrides, or Docker registry mirrors.

The default setup is:

```bash
sforge fetch-tasks edgebench
sforge pull --task ad_placement_optimization --registry seededge
sforge serve

export SFORGE_AGENT_API_KEY="sk-ant-xxxx"
sforge run --task ad_placement_optimization --agent claude-code
```

Use `sforge build --task ad_placement_optimization` instead of `sforge pull ...` only when you need to build images locally.

Use the options below only when your environment cannot reach a required service directly.

## What Needs Network Access

| Stage | Network Access |
|-------|----------------|
| `sforge fetch-tasks` | Downloading benchmark task definitions |
| `sforge pull` | Pulling pre-built Docker task images |
| `sforge build` | Optional local fallback: pulling Docker base images and downloading task dependencies such as PyPI, Maven, Go modules, APT packages, or Git repositories |
| `sforge run` | Installing the selected agent if needed, and calling the configured LLM API |
| `sforge serve` | No public internet access required for normal local use |

## Optional: Mirrors for Package Downloads

If package downloads are slow or blocked in your environment, configure only the mirror you need:

```bash
export SFORGE_PYPI_INDEX_URL="https://pypi.example.com/simple/"
export SFORGE_APT_MIRROR_URL="https://apt.example.com"
export SFORGE_MAVEN_MIRROR_URL="https://maven.example.com/repository/public"
export SFORGE_GO_PROXY="https://goproxy.example.com"
export SFORGE_NODEJS_MIRROR_URL="https://nodejs.example.com/download/release/"
export SFORGE_NPM_REGISTRY_URL="https://npm.example.com"
```

These variables are not required on an unrestricted network. Build-stage mirrors affect image construction; `SFORGE_NODEJS_MIRROR_URL` and `SFORGE_NPM_REGISTRY_URL` are mainly useful when agent installation happens during `sforge run`.

## Optional: Direct Proxies

SForge can pass proxy variables into Docker builds and work containers:

```bash
export SFORGE_HTTP_PROXY="http://proxy.example:8080"
export SFORGE_HTTPS_PROXY="http://proxy.example:8080"
export SFORGE_NO_PROXY="localhost,127.0.0.1,host.docker.internal"
```

Use direct proxies only when the host or container cannot reach external services directly. Direct run-time proxies are **not recommended** for normal agent runs because they give the work container proxy-mediated network access.

Direct proxy configuration is also incompatible with network isolation (`--disable-internet`). If the agent needs LLM API access through an upstream proxy while network isolation is enabled, use `sforge proxy` instead.

## LLM API Access with `sforge proxy`

Use `sforge proxy` when both conditions are true:

- the work container should run with `--disable-internet`
- the LLM API is reachable from the host only through an upstream proxy

```bash
# Terminal 1: start the API proxy on the host
export HTTPS_PROXY="http://corp-proxy.example:8080"
sforge proxy --target https://api.anthropic.com --port 9090

# Terminal 2: run the agent with network isolation
export SFORGE_AGENT_API_KEY="sk-ant-xxxx"
export SFORGE_AGENT_API_BASE_URL="http://host.docker.internal:9090"
sforge run --task ad_placement_optimization --agent claude-code --disable-internet
```

The proxy runs on the host, forwards requests through the upstream proxy, and exposes only the target API endpoint to the container.

## Optional: DNS Overrides

If DNS resolution is unreliable, use `SFORGE_EXTRA_HOSTS` to inject static host entries:

```bash
export SFORGE_EXTRA_HOSTS="github.com:140.82.114.4,raw.githubusercontent.com:185.199.108.133"
```

These entries are passed as Docker `--add-host` settings and apply during both build and run.

## Troubleshooting

| Symptom | Likely Cause | Fix |
|---------|--------------|-----|
| `docker pull` times out | Docker Hub or registry is unreachable from the host | Check host Docker networking; configure a Docker daemon proxy or registry mirror only if your environment requires it |
| `pip install` fails during build | PyPI is unreachable | Set `SFORGE_PYPI_INDEX_URL` to an accessible mirror |
| `git clone` fails during build | Git host is unreachable or DNS is broken | Check host access first; then use `SFORGE_HTTP_PROXY` / `SFORGE_HTTPS_PROXY` or `SFORGE_EXTRA_HOSTS` if needed |
| Maven or Go dependencies time out | Public package registry is unreachable | Set `SFORGE_MAVEN_MIRROR_URL` or `SFORGE_GO_PROXY` |
| Agent install fails while downloading Node.js or npm packages | Node.js or npm registry is unreachable | Set `SFORGE_NODEJS_MIRROR_URL` or `SFORGE_NPM_REGISTRY_URL` |
| Agent cannot reach the LLM API | API key/base URL is wrong, the API is unreachable, or network isolation blocks direct access | Check your API key and `SFORGE_AGENT_API_BASE_URL`; use `sforge proxy` with `--disable-internet` when an upstream proxy is required |
