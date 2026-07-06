---
title: "全部任务 (Kubernetes)"
---

# 全部任务 (Kubernetes)

使用 Kubernetes 集群运行完整的 EdgeBench 任务套件（约 50 个任务）。

::: tip 官方 leaderboard 配置
本示例中的 experiment YAML 就是 **EdgeBench leaderboard 的官方配置**（单任务 12 小时预算、启用 stop hook 与 auto-eval、按文件中的资源限额）。若希望结果与 leaderboard 可比，请只修改 `env`、`model` 和镜像仓库地址，其余保持不变。
:::

::: warning 费用
使用前沿模型（如 Claude Opus）时，单个任务跑满 12 小时预算的 API 费用可达**数百甚至上千美元**，完整跑一遍约 50 个任务是数万美元量级的开销。请先用单任务 + 较短 `--timeout` 摸清费用水平。
:::

## 前提条件

| 要求 | 验证方式 |
|------|----------|
| 已配置 `kubectl` 的 Linux 主机 | `kubectl cluster-info` |
| NetworkPolicy 支持（网络隔离需要） | CNI 支持并执行 NetworkPolicy；kubeconfig 有在目标 namespace 创建/删除 `NetworkPolicy` 的权限 |
| Docker Engine（用于推送镜像） | `docker run hello-world` |
| Python >= 3.10 | `python --version` |
| K8s 节点可访问的容器镜像仓库 | 如 `<registry-ip>:5000` |

## 操作步骤

### 1. 安装 SForge

```bash
pip install sforge
```

### 2. 获取任务定义

```bash
sforge fetch-tasks edgebench
sforge list            # 确认任务可见
```

### 3. 推送镜像到集群仓库

K8s Pod 在运行时拉取镜像。从 Docker Hub 等公共仓库拉取速度太慢，会严重影响
Agent 性能——每个任务的镜像拉取可能需要数分钟，占用评测时间预算。应当事先将
所有镜像推送到与 K8s 集群**在同一 VPC 内**的私有仓库。

```bash
# 从公共仓库拉取预构建镜像
sforge pull --all --registry seededge

# 推送到私有仓库
sforge push --all --registry <registry-ip>:5000
```

验证镜像是否已入库：

```bash
curl -s http://<registry-ip>:5000/v2/_catalog | head
```

<details>
<summary>自建私有 Docker Registry</summary>

如果还没有私有仓库，可以用一行命令启动：

```bash
docker run -d -p 5000:5000 --restart=always --name registry registry:2
```

**配置信任 HTTP 仓库：** Docker 默认只信任 HTTPS 仓库。对于局域网内的 HTTP
仓库，需要在每台推送/拉取的机器（包括 K8s 节点）上配置信任：

1. 编辑 `/etc/docker/daemon.json`（不存在则创建）：

   ```json
   {
     "insecure-registries": ["<registry-ip>:5000"]
   }
   ```

2. 重启 Docker：

   ```bash
   sudo systemctl restart docker
   ```

3. 使用 containerd 的 K8s 节点，需要在**集群内每个节点**上修改
   `/etc/containerd/config.toml`（Pod 可能被调度到任意节点）：

   ```toml
   [plugins."io.containerd.grpc.v1.cri".registry.configs."<registry-ip>:5000".tls]
     insecure_skip_verify = true
   ```

   然后重启 containerd：`sudo systemctl restart containerd`

</details>

### 4. 启动 Judge 服务器

启动 Judge 服务器，`--judge-url` 设置为本机 IP 地址，确保 K8s Pod 可以
访问（不能用 `localhost` 或 `host.docker.internal`）：

```bash
sforge serve --port 8080
```

### 5. 配置 LLM 评分任务

`college_english_exam_bank` 任务使用 LLM 评分，其 Judge 容器需要调用模型
API。通过 `SFORGE_JUDGE_EXTRA_ENV` 传入凭证。

**在启动 Judge 服务器前设置**：

```bash
export SFORGE_JUDGE_EXTRA_ENV="SFORGE_JUDGE_API_KEY=your-key,SFORGE_JUDGE_API_BASE_URL=https://api.openai.com/v1,SFORGE_JUDGE_MODEL=gpt-5.5"
sforge serve --port 8080
```

| 变量（Judge 容器内） | 用途 |
|----------------------|------|
| `SFORGE_JUDGE_API_KEY` | 评分脚本调用 LLM 的 API 密钥 |
| `SFORGE_JUDGE_API_BASE_URL` | 评分用 LLM 端点的 Base URL |
| `SFORGE_JUDGE_MODEL` | 评分脚本使用的模型 ID |

非评分任务会忽略这些变量，因此可以统一设置。

### 6. 运行实验

[`experiment.yaml`](https://github.com/ByteDance-Seed/EdgeBench/blob/main/examples/all-tasks-k8s/experiment.yaml) 定义了完整的 EdgeBench 套件——所有任务、
单任务覆盖、模型配置和资源限制。详见下方
[实验 YAML 说明](#实验-yaml-说明)。

```bash
sforge run --experiment experiment.yaml \
  --judge-url http://<judge-host-ip>:8080 \
  --run-id edgebench-001
```

所有任务会在 600 秒内依次启动（间隔均匀分配给每个任务）。查看进展：

```bash
sforge visualizer
# 打开 http://127.0.0.1:8000
```

也可以查看特定任务的日志：

```bash
tail -f logs/runs/*/ad_placement_optimization/agent_output.txt
```


## 实验 YAML 说明

实验 YAML（[示例](https://github.com/ByteDance-Seed/EdgeBench/blob/main/examples/all-tasks-k8s/experiment.yaml)）中有详细注释。关键部分：

### `env:`

在解析其余配置前注入到宿主机进程的环境变量。K8s 最重要的配置：

```yaml
env:
  SFORGE_K8S_IMAGE_REGISTRY: "<registry-ip>:5000"   # K8s 必须
```

### `stagger:`

所有任务启动的总间隔秒数，均匀分配给每个任务。50+ 个任务同时启动会导致 API
限流和 K8s 调度压力。600 秒（10 分钟）是安全的默认值。设为 `0` 可同时启动
所有任务。

### `model:`

```yaml
model:
  api_key: "sk-xxxx"
  model: claude-opus-4-8

  # 仅第三方/自建端点需要，使用 Anthropic API 时省略
  # api_base_url: "https://api.deepseek.com/anthropic"
```

### `defaults:`

应用于所有任务，除非被单任务覆盖。

### 单任务覆盖

```yaml
tasks:
  smt_solver:
    work_cpu_limit: 16       # 需要比默认 4 核更多的 CPU
    work_mem_limit: "16g"
  anchorhead_text_adventure:
    submission_cooldown: 0   # 游戏模式任务，无需冷却
  carleson_formalization: *lean_task   # YAML 锚点引用
```

### YAML 锚点

用 `x-` 前缀定义共享覆盖块，用 `*` 引用：

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


## 其他实验配置

示例目录中提供了其他 Agent 和第三方模型的实验配置：

- [`experiment-codex.yaml`](https://github.com/ByteDance-Seed/EdgeBench/blob/main/examples/all-tasks-k8s/experiment-codex.yaml) — Codex + GPT-5.5
- [`experiment-deepseek.yaml`](https://github.com/ByteDance-Seed/EdgeBench/blob/main/examples/all-tasks-k8s/experiment-deepseek.yaml) — Claude Code + DeepSeek V4 Pro（1M 上下文）
- [`experiment-glm.yaml`](https://github.com/ByteDance-Seed/EdgeBench/blob/main/examples/all-tasks-k8s/experiment-glm.yaml) — Claude Code + GLM 5.1（200K 上下文）

```bash
sforge run --experiment experiment-codex.yaml \
  --judge-url http://<judge-host-ip>:8080 \
  --run-id edgebench-codex-001
```

Claude Code 使用第三方模型时需要额外配置（缓存优化、模型路由变量、上下文窗口），详见[单任务运行 (Docker) — 使用第三方模型](/zh/examples/single-task-docker#使用第三方模型)。

## K8s 专用环境变量

| 变量 | 是否必需 | 用途 |
|------|----------|------|
| `SFORGE_K8S_IMAGE_REGISTRY` | **是** | K8s Pod 拉取镜像的仓库地址，不设置后端初始化会报错 |
| `SFORGE_K8S_NAMESPACE` | 否（默认 `default`） | Kubernetes 命名空间 |
| `SFORGE_K8S_KUBECONFIG` | 否 | kubeconfig 文件路径（省略则使用默认上下文） |
| `SFORGE_K8S_NODE_SELECTOR` | 否 | Pod 节点选择器，格式：`"key1=val1,key2=val2"` |

其他环境变量请参见[环境变量](/zh/configuration/environment-variables)。
