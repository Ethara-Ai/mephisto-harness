---
title: 容器后端
---

# 容器后端

SForge 通过容器后端创建 Work 容器和 Judge 容器。默认后端是本机 Docker；当需要把运行负载放到 Kubernetes 集群中时，可以切换到 `k8s` 后端。

## 如何选择后端

| 后端 | 适合场景 | 主要要求 |
|------|----------|----------|
| `docker` | 本地开发、调试任务、单机评测、小规模实验 | 本机 Docker daemon 可用 |
| `k8s` | 共享集群、批量并发评测、希望让 Work/Judge Pod 在集群中运行 | `kubectl` 可访问集群，镜像在集群中可拉取，Judge URL 可从 Pod 访问 |

如果只是本地试跑任务，优先使用默认的 Docker 后端。Kubernetes 后端更适合已经有集群和镜像仓库的团队环境。

::: warning Docker 后端不适合大批量运行
每个任务会占用一个 Work 容器外加临时 Judge 容器，各自有独立的 CPU/内存限额。单机并发运行大量任务（约 **20 个以上**）即使是高性能服务器也会出现严重的资源争抢。大批量运行请使用 `k8s` 后端。
:::

## 配置方式

后端可以通过 CLI、环境变量或实验 YAML 配置：

```bash
# 单次运行覆盖
sforge run \
  --task ad_placement_optimization \
  --agent claude-code \
  --backend k8s \
  --judge-url http://10.0.0.12:8080 --backend k8s

# 环境变量覆盖
export SFORGE_BACKEND=k8s
sforge run \
  --task ad_placement_optimization \
  --agent claude-code \
  --backend k8s \
  --judge-url http://10.0.0.12:8080
```

实验配置中也可以设置默认后端：

```yaml
defaults:
  agent: claude-code
  backend: k8s

tasks:
  ad_placement_optimization: {}
```

## Docker backend

Docker 是默认后端，不需要显式配置：

```bash
sforge build --task ad_placement_optimization
sforge serve

export SFORGE_AGENT_API_KEY="sk-..."
sforge run \
  --task ad_placement_optimization \
  --agent claude-code \
  --backend k8s \
  --judge-url http://10.0.0.12:8080
```

Docker 后端会：

- 使用本机 Docker daemon 构建和运行镜像
- 在本机 Docker 中启动 Work 容器和 Judge 容器
- 通过默认的 `http://host.docker.internal:8080` 让容器访问宿主机上的 Judge HTTP server
- 在启用 `--disable-internet` 时使用宿主机侧网络隔离能力

资源限制可以通过 CLI 或环境变量设置：

```bash
sforge run \
  --task ad_placement_optimization \
  --agent claude-code \
  --work-cpu-limit 4 \
  --work-mem-limit 8g \
  --judge-cpu-limit 2 \
  --judge-mem-limit 4g
```

## Kubernetes backend

Kubernetes 后端通过 `kubectl` 创建 Pod。每个 SForge 容器会对应到集群中的一个 Pod，容器名为 `work`，Pod 使用标签 `app=sforge` 和 `sforge-pod=<pod-name>`。

### 前置条件

使用 `k8s` 后端前，请确认：

1. 本机已安装 `kubectl`，并且可以访问目标集群。
2. 目标 namespace 已存在，且当前 kubeconfig 有创建、查询、删除 Pod 的权限。
3. Work/Judge 镜像已经推送到 Kubernetes 节点可访问的镜像仓库。
4. SForge Judge HTTP server 对集群中的 Pod 可访问。
5. 如果使用 `--disable-internet`，集群需要支持并执行 Kubernetes `NetworkPolicy`。

可以先检查集群连通性：

```bash
kubectl -n <namespace> cluster-info
kubectl -n <namespace> get pods
```

### Kubernetes 相关环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `SFORGE_BACKEND` | `docker` | 设置为 `k8s` 后启用 Kubernetes 后端 |
| `SFORGE_K8S_NAMESPACE` | `default` | 创建 Pod 和 NetworkPolicy 的 namespace |
| `SFORGE_K8S_IMAGE_REGISTRY` | --- | Pod 拉取镜像时添加到镜像名前的 registry 前缀 |
| `SFORGE_K8S_KUBECONFIG` | --- | kubeconfig 文件路径；未设置时使用 `kubectl` 默认配置 |
| `SFORGE_K8S_NODE_SELECTOR` | --- | Pod 的 node selector，格式为 `"key1=val1,key2=val2"` |

### 镜像准备

Kubernetes 节点不能直接使用你本机 Docker daemon 里的本地镜像。使用 k8s 后端时，通常需要先构建并推送镜像：

```bash
# 本机构建镜像
sforge build --task ad_placement_optimization

# 推送到集群可访问的 registry
sforge push --task ad_placement_optimization --registry registry.example.com/sforge
```

然后让 k8s 后端使用同一个 registry 前缀：

```bash
export SFORGE_K8S_IMAGE_REGISTRY=registry.example.com/sforge
```

Kubernetes 后端会把内部镜像名解析为：

```text
${SFORGE_K8S_IMAGE_REGISTRY}/<sforge-image-name>:<tag>
```

::: tip
`sforge build` 仍然使用本机 Docker 构建镜像；`k8s` 后端负责运行 Work/Judge Pod，不负责在集群中构建镜像。
:::

### Judge URL

`--judge-url` 是 Work 容器或 Pod 里看到的 Judge server 地址。Docker 默认值 `http://host.docker.internal:8080` 通常只适合本机 Docker，不适合 Kubernetes Pod。

使用 k8s 后端时，应通过 `--judge-url` 传入一个 Pod 可访问的地址，例如宿主机内网 IP、LoadBalancer、Ingress 或集群内 Service。

启动本机 Judge server：

```bash
sforge serve --host 0.0.0.0 --port 8080
```

然后运行：

```bash
sforge run \
  --task ad_placement_optimization \
  --agent claude-code \
  --backend k8s \
  --judge-url http://10.0.0.12:8080
```

### 完整示例

```bash
# 1. 构建并推送镜像
sforge build --task ad_placement_optimization
sforge push --task ad_placement_optimization --registry registry.example.com/sforge

# 2. 配置 k8s 后端
export SFORGE_BACKEND=k8s
export SFORGE_K8S_NAMESPACE=sforge
export SFORGE_K8S_IMAGE_REGISTRY=registry.example.com/sforge
export SFORGE_K8S_KUBECONFIG=$HOME/.kube/config

# 可选：只调度到指定节点池
export SFORGE_K8S_NODE_SELECTOR="pool=sforge"

# 3. 启动 Judge server，确保集群 Pod 可以访问这个地址
sforge serve --host 0.0.0.0 --port 8080

# 4. 另一个终端运行 Agent
export SFORGE_AGENT_API_KEY="sk-..."
sforge run \
  --task ad_placement_optimization \
  --agent claude-code \
  --backend k8s \
  --judge-url http://10.0.0.12:8080
```

### 资源限制

Work/Judge 的 CPU 和内存限制同样适用于 k8s 后端。SForge 会把它们转换为 Pod 的 resource requests/limits：

```bash
sforge run \
  --task ad_placement_optimization \
  --agent claude-code \
  --backend k8s \
  --work-cpu-limit 4 \
  --work-mem-limit 8g \
  --judge-cpu-limit 2 \
  --judge-mem-limit 4g
```

内存格式会从 Docker 风格转换为 Kubernetes 风格，例如 `8g` 转为 `8Gi`，`512m` 转为 `512Mi`。

### 网络隔离

在 Docker 后端中，`--disable-internet` 使用宿主机侧网络隔离；在 Kubernetes 后端中，SForge 会创建 Kubernetes `NetworkPolicy` 限制 Pod egress，只允许访问 Judge server、配置的 LLM API 端点和 DNS。

注意：

- 集群的 CNI 必须支持并执行 `NetworkPolicy`，否则策略可能不会生效。
- 当前 kubeconfig 需要有创建和删除 `NetworkPolicy` 的权限。
- 不同集群的默认 DNS、出口网关和策略实现可能不同，建议先用小任务验证隔离效果。

## 常见问题

| 现象 | 可能原因 | 处理方式 |
|------|----------|----------|
| `kubectl cluster-info failed` | kubeconfig 不正确、集群不可达或 namespace 参数有误 | 检查 `kubectl -n <namespace> cluster-info`；必要时设置 `SFORGE_K8S_KUBECONFIG` 和 `SFORGE_K8S_NAMESPACE` |
| Pod 一直无法 Running | 镜像拉取失败、调度失败或资源不足 | 使用 `kubectl -n <namespace> describe pod <pod>` 查看事件 |
| Pod 拉不到镜像 | 镜像没有推送到集群可访问的 registry，或 registry 凭证未配置 | 先 `sforge push`；确认 `SFORGE_K8S_IMAGE_REGISTRY` 正确；为 namespace 配置 image pull secret |
| Work Pod 无法提交评测 | `--judge-url` 不是 Pod 可访问地址，或 Judge server 没有监听外部地址 | 用 `--host 0.0.0.0` 启动 `sforge serve`，并通过 `--judge-url` 设置 Pod 可访问的 IP/Service URL |
| `--disable-internet` 没有效果 | 集群 CNI 不支持 NetworkPolicy 或策略权限不足 | 确认 CNI 支持 NetworkPolicy，并检查当前身份是否能创建 NetworkPolicy |
| node selector 后 Pod Pending | 没有节点匹配 selector | 检查 `SFORGE_K8S_NODE_SELECTOR` 和节点标签 |
