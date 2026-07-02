---
title: 网络配置
---

# 网络配置

## 默认不需要额外配置

SForge 默认假设宿主机和容器都可以访问公网。在正常外网环境下，不需要配置代理、镜像源、DNS 覆盖或 Docker registry mirror。

默认流程就是：

```bash
sforge fetch-tasks edgebench
sforge pull --task ad_placement_optimization --registry seededge
sforge serve

export SFORGE_AGENT_API_KEY="sk-ant-xxxx"
sforge run --task ad_placement_optimization --agent claude-code
```

只有需要本地构建镜像时，才用 `sforge build --task ad_placement_optimization` 替代 `sforge pull ...`。

只有当你的环境无法直连某个外部服务时，才需要使用下面的可选配置。

## 哪些阶段需要网络

| 阶段 | 网络访问 |
|------|----------|
| `sforge fetch-tasks` | 下载 benchmark 任务定义 |
| `sforge pull` | 拉取预构建 Docker 任务镜像 |
| `sforge build` | 可选本地 fallback：拉取 Docker base image，以及下载任务依赖，例如 PyPI、Maven、Go modules、APT 包或 Git 仓库 |
| `sforge run` | 必要时安装所选 Agent，并调用配置的 LLM API |
| `sforge serve` | 本地正常使用时不需要公网访问 |

## 可选：包下载镜像源

如果你的环境里包下载很慢或不可达，只配置实际需要的镜像源即可：

```bash
export SFORGE_PYPI_INDEX_URL="https://pypi.example.com/simple/"
export SFORGE_APT_MIRROR_URL="https://apt.example.com"
export SFORGE_MAVEN_MIRROR_URL="https://maven.example.com/repository/public"
export SFORGE_GO_PROXY="https://goproxy.example.com"
export SFORGE_NODEJS_MIRROR_URL="https://nodejs.example.com/download/release/"
export SFORGE_NPM_REGISTRY_URL="https://npm.example.com"
```

这些变量在公网可直连时都不是必需项。构建阶段镜像源影响镜像构建；`SFORGE_NODEJS_MIRROR_URL` 和 `SFORGE_NPM_REGISTRY_URL` 主要用于 `sforge run` 阶段安装 Agent。

## 可选：直接代理

SForge 可以把代理变量传入 Docker 构建和 Work 容器：

```bash
export SFORGE_HTTP_PROXY="http://proxy.example.com:8080"
export SFORGE_HTTPS_PROXY="http://proxy.example.com:8080"
export SFORGE_NO_PROXY="localhost,127.0.0.1,host.docker.internal"
```

只有当宿主机或容器无法直连外部服务时才需要直接代理。运行阶段直接代理**不推荐**用于常规 Agent 运行，因为它会让 Work 容器通过代理获得网络访问能力。

直接代理也不兼容网络隔离模式（`--disable-internet`）。如果需要在网络隔离下通过上游代理访问 LLM API，请使用 `sforge proxy`。

## 使用 `sforge proxy` 访问 LLM API

同时满足以下条件时使用 `sforge proxy`：

- Work 容器需要以 `--disable-internet` 运行
- 宿主机访问 LLM API 时必须经过上游代理

```bash
# 终端 1：在宿主机启动 API 代理
export HTTPS_PROXY="http://corp-proxy.example.com:8080"
sforge proxy --target https://api.anthropic.com --port 9090

# 终端 2：以网络隔离模式运行 Agent
export SFORGE_AGENT_API_KEY="sk-ant-xxxx"
export SFORGE_AGENT_API_BASE_URL="http://host.docker.internal:9090"
sforge run --task ad_placement_optimization --agent claude-code --disable-internet
```

这个代理运行在宿主机上，通过上游代理转发请求，并且只把目标 API 端点暴露给容器。

## 可选：DNS 覆盖

如果 DNS 解析不稳定，可以使用 `SFORGE_EXTRA_HOSTS` 注入静态 host 记录：

```bash
export SFORGE_EXTRA_HOSTS="github.com:140.82.114.4,raw.githubusercontent.com:185.199.108.133"
```

这些记录会作为 Docker `--add-host` 配置传入，在构建和运行阶段都生效。

## 常见问题排查

| 现象 | 可能原因 | 处理方式 |
|------|----------|----------|
| `docker pull` 超时 | 宿主机无法访问 Docker Hub 或目标 registry | 先检查宿主机 Docker 网络；只有环境需要时再配置 Docker daemon 代理或 registry mirror |
| 构建时 `pip install` 失败 | PyPI 不可达 | 设置 `SFORGE_PYPI_INDEX_URL` 为可访问的镜像源 |
| 构建时 `git clone` 失败 | Git 服务不可达或 DNS 异常 | 先检查宿主机是否可访问；必要时使用 `SFORGE_HTTP_PROXY` / `SFORGE_HTTPS_PROXY` 或 `SFORGE_EXTRA_HOSTS` |
| Maven 或 Go 依赖下载超时 | 公共包仓库不可达 | 设置 `SFORGE_MAVEN_MIRROR_URL` 或 `SFORGE_GO_PROXY` |
| Agent 安装时下载 Node.js 或 npm 包失败 | Node.js 或 npm registry 不可达 | 设置 `SFORGE_NODEJS_MIRROR_URL` 或 `SFORGE_NPM_REGISTRY_URL` |
| Agent 无法访问 LLM API | API key/base URL 错误、API 不可达，或网络隔离阻断了直接访问 | 检查 API key 和 `SFORGE_AGENT_API_BASE_URL`；需要上游代理且启用 `--disable-internet` 时使用 `sforge proxy` |
