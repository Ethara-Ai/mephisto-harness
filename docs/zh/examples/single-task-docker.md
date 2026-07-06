---
title: "单任务运行 (Docker)"
---

# 单任务运行 (Docker)

使用 Docker 在本地运行一个 EdgeBench 任务（`ad_placement_optimization`）。

::: tip 规模
Docker backend 只适合**小批量任务**试跑。在单机上并发运行大量任务（约 20 个以上）即使是高性能服务器也会被耗尽。完整套件请使用 [Kubernetes 示例](/zh/examples/all-tasks-k8s)中的官方配置。
:::

::: warning 费用
前沿模型的运行费用很高——单个任务跑满官方 12 小时预算，API 费用可达数百甚至上千美元。建议先用较短的 `--timeout`（本示例为 2 小时）试跑，摸清费用水平后再扩大规模。
:::

## 前提条件

| 要求 | 验证方式 |
|------|----------|
| Linux 主机 | - |
| Docker Engine 已运行 | `docker run hello-world` |
| Python >= 3.10 | `python --version` |

> **注意：** Docker 后端需要直接访问宿主机 Docker daemon。
> 在容器内运行 SForge 会产生 Docker-in-Docker 问题。

## 使用 Claude Code + Anthropic API

### 1. 安装 SForge

```bash
pip install sforge
```

### 2. 获取任务定义

```bash
sforge fetch-tasks edgebench
```

将 EdgeBench 任务 JSON 和 `BENCHMARK.yaml` 下载到 `./tasks/`。验证：

```bash
sforge list
```

### 3. 拉取预构建镜像

```bash
sforge pull --task ad_placement_optimization --registry seededge
```

从公共仓库拉取 base、work 和 judge 镜像：

- `edgebench.base.cpp:<hash>`
- `edgebench.work.ad_placement_optimization:<hash>`
- `edgebench.judge.ad_placement_optimization:<hash>`

### 4. 启动 Judge 服务器

打开一个**新终端**：

```bash
sforge serve
```

默认监听 `0.0.0.0:8080`。Judge 服务器接收 Agent 提交的代码压缩包，在临时
Judge 容器中运行隐藏测试套件，并返回分数。

### 5. 运行 Agent

```bash
SFORGE_AGENT_API_KEY="sk-ant-xxxx" \
sforge run --task ad_placement_optimization --agent claude-code \
  --model claude-opus-4-8[1m] \
  --timeout 7200 \
  --run-id ad-placement-optimization-001
```

这会启动 Claude Opus 4.8 处理该任务，持续 2 小时。
你会在 stdout 中实时看到 Agent 的工作输出。

### 6. 查看结果

通过内置 Web UI 实时查看评分进展：

```bash
sforge visualizer
# 打开 http://127.0.0.1:8000
```

也可以直接查看文件：

```bash
ls logs/runs/*/ad_placement_optimization/
cat logs/runs/*/ad_placement_optimization/final_result.json
```


## 使用第三方模型

评测非 Anthropic 模型时，将 API base URL 指向第三方服务，并注意以下三项配置。

### 1. 避免 Prefix Cache Miss (`SFORGE_CLAUDE_CACHE_OPT=1`)

第三方 API 通常不识别 Claude Code 的归属头和动态系统提示词段落。这些内容每次请求都会变化，导致前缀缓存持续失效、浪费 token。设置 `SFORGE_CLAUDE_CACHE_OPT=1` 可以去除这些动态部分，使 prompt 前缀保持稳定、可缓存。

### 2. 覆盖 Claude Code 的默认模型路由

Claude Code 内部会将不同调用分派到 opus/sonnet/haiku 等模型层级（例如 subagent 调用），默认使用 Anthropic 的模型 ID。使用第三方模型时，需要覆盖**所有**这些变量：

| 变量 | 用途 |
|------|------|
| `ANTHROPIC_MODEL` | Claude Code 使用的主模型 |
| `ANTHROPIC_DEFAULT_OPUS_MODEL` | opus 层级调用使用的模型 |
| `ANTHROPIC_DEFAULT_SONNET_MODEL` | sonnet 层级调用使用的模型 |
| `ANTHROPIC_DEFAULT_HAIKU_MODEL` | haiku 层级调用使用的模型 |
| `CLAUDE_CODE_SUBAGENT_MODEL` | subagent 生成使用的模型 |

### 3. 上下文窗口配置

**1M 上下文模型（如 DeepSeek V4 Pro）：** 在模型名后追加 `[1m]` 来启用 Claude Code 的 1M 上下文模式，例如 `deepseek-v4-pro[1m]`。不加此后缀则默认使用 200K 上下文窗口。

**200K 上下文模型（如 GLM 5.1）：** 设置以下变量防止 Claude Code 超出上下文限制：

| 变量 | 值 | 用途 |
|------|-----|------|
| `CLAUDE_CODE_AUTO_COMPACT_WINDOW` | `200000` | 上下文窗口大小（token） |
| `CLAUDE_AUTOCOMPACT_PCT_OVERRIDE` | `80` | 使用量达到 80% 时触发压缩 |

不设置这些变量时，Claude Code 可能会尝试填充更大的默认上下文窗口，导致第三方模型报错。

### 示例 A：DeepSeek V4 Pro（1M 上下文）

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

### 示例 B：GLM 5.1（200K 上下文）

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


## 网络隔离

每个 EdgeBench 任务 JSON 中有 `internet` 字段控制 Agent 是否可以访问公网。
大多数任务设置为 `internet: false`。可以用 CLI 参数全局覆盖：

```bash
# 强制断网（即使任务 JSON 允许联网）
sforge run --task ad_placement_optimization --agent claude-code \
  --disable-internet ...

# 强制联网（即使任务 JSON 禁止联网）
sforge run --task ad_placement_optimization --agent claude-code \
  --enable-internet ...
```

<details>
<summary>Docker 网络隔离实现原理</summary>

断网时，SForge 在宿主机上创建**每容器 iptables 链**
（`SFORGE_<容器 ID 前12位>`），仅放行 Agent 需要的端点（Judge 服务器 + LLM API），
其余全部 DROP。规则位于宿主机网络命名空间，容器内部无法修改（没有 `NET_ADMIN`
权限）。IPv6 完全阻断。

链名格式为 `SFORGE_<容器 ID 前 12 字符>`。跳转规则插入到 `DOCKER-USER`、
`INPUT` 和（IPv6 时）`FORWARD`。

> **注意：** 这仅影响 Docker 后端。K8s 后端使用 Kubernetes NetworkPolicy
> 实现隔离，由集群管理，不会在宿主机上留下残留。

</details>

<details>
<summary>异常退出后清理残留 iptables 规则</summary>

正常结束时 SForge 会自动清理 iptables 链。但如果进程被**异常终止**
（如 `kill -9`、宿主机崩溃、OOM），残留链会留在宿主机 iptables 中。

**自动清理：** 每次 `sforge run` 启动时会检查是否存在残留链（对应的容器已不存在），
并自动删除。因此启动新一轮运行即可清理上次崩溃的残留。

**手动清理：**

```bash
# 查看残留链
sudo iptables -L -n | grep 'Chain SFORGE_'

# 清空并删除每个残留链
sudo iptables -F SFORGE_xxxxxxxxxxxx
sudo iptables -X SFORGE_xxxxxxxxxxxx
```

还需要删除父链（`DOCKER-USER`、`INPUT`、`FORWARD`）中引用该链的跳转规则：

```bash
sudo iptables -S DOCKER-USER | grep SFORGE_
sudo iptables -S INPUT | grep SFORGE_

# 将 -A 替换为 -D 执行删除
sudo iptables -D DOCKER-USER -s 172.17.0.2/32 -j SFORGE_abc123def456
```

一键清理所有残留链：

```bash
for chain in $(sudo iptables -L -n | grep -oP 'SFORGE_[0-9a-f]{12}'); do
  sudo iptables -S DOCKER-USER 2>/dev/null | grep "$chain" | sed 's/^-A/-D/' | while read rule; do sudo iptables $rule; done
  sudo iptables -S INPUT 2>/dev/null | grep "$chain" | sed 's/^-A/-D/' | while read rule; do sudo iptables $rule; done
  sudo iptables -F "$chain" 2>/dev/null
  sudo iptables -X "$chain" 2>/dev/null
done
```

</details>


### LLM 评分任务

部分任务使用 LLM 对提交内容评分，而非确定性测试。EdgeBench 中的
**专业/领域知识类**任务（`college_english_exam_bank`）在 Judge 容器中运行评分脚本
（`grade_with_codex.py`），需要调用模型 API。

这些任务需要通过 `SFORGE_JUDGE_EXTRA_ENV` 将 API 凭证传入 Judge 容器。
**在启动 Judge 服务器前设置**：

```bash
export SFORGE_JUDGE_EXTRA_ENV="SFORGE_JUDGE_API_KEY=your-key,SFORGE_JUDGE_API_BASE_URL=https://api.openai.com/v1,SFORGE_JUDGE_MODEL=gpt-5.5"
sforge serve
```

| 变量（Judge 容器内） | 用途 |
|----------------------|------|
| `SFORGE_JUDGE_API_KEY` | 评分脚本调用 LLM 的 API 密钥 |
| `SFORGE_JUDGE_API_BASE_URL` | 评分用 LLM 端点的 Base URL |
| `SFORGE_JUDGE_MODEL` | 评分脚本使用的模型 ID |

非评分任务（如 `ad_placement_optimization`）会忽略这些变量，
因此可以统一设置。
