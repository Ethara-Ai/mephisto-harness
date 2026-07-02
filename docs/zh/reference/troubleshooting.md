---
title: 故障排除
---

# 故障排除

## 网络问题（最常见）

SForge 绝大多数失败都是由 Docker 镜像构建或 Agent 运行时的网络连接问题引起的。下表列出了常见问题与对应的解决方案：

| 现象 | 阶段 | 解决方案 |
|------|------|----------|
| Docker Hub 拉取超时 | 构建 | 配置 Docker daemon 代理或在 `/etc/docker/daemon.json` 中设置 registry mirrors |
| `pip install` 超时 | 构建 | 设置 `SFORGE_PYPI_INDEX_URL`（参见下方镜像源表） |
| `apt-get update` 超时 | 构建 | 设置 `SFORGE_APT_MIRROR_URL`（参见下方镜像源表） |
| `git clone` GitHub 超时 | 构建 | 设置 `SFORGE_HTTP_PROXY` / `SFORGE_HTTPS_PROXY`，或使用 `SFORGE_EXTRA_HOSTS` 进行 DNS 覆盖 |
| Maven 下载超时 | 构建 | 设置 `SFORGE_MAVEN_MIRROR_URL` |
| Node.js 安装失败 | 运行 | 设置 `SFORGE_NODEJS_MIRROR_URL` |
| Agent 无法连接 API | 运行 | 检查 `SFORGE_AGENT_API_BASE_URL`，确保端点从容器内可达 |
| `sforge-submit` 连接失败 | 运行 | 确认 Judge 服务器正在运行（`sforge serve`），检查 `--judge-url` 是否正确 |
| 构建成功但运行时网络报错 | 运行 | 构建和运行的配置是独立的——代理/镜像源需要分别配置 |

### 各环境镜像源推荐

| 用途 | 推荐镜像源 |
|------|-----------|
| PyPI | `https://mirrors.aliyun.com/pypi/simple/` |
| APT | `https://mirrors.aliyun.com` |
| Maven | `https://maven.aliyun.com/repository/public` |
| Go | `https://goproxy.cn` |
| Node.js | `https://mirrors.aliyun.com/nodejs-release/` |
| NPM | `https://registry.npmmirror.com`（通常不需要单独配置） |

### 构建配方

```bash
# 火山云 ECS 通常可直连 Docker Hub，配置 registry mirrors 即可
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

# SForge 构建环境变量
export SFORGE_PYPI_INDEX_URL="https://mirrors.ivolces.com/pypi/simple/"
export SFORGE_APT_MIRROR_URL="http://mirrors.ivolces.com"
export SFORGE_MAVEN_MIRROR_URL="https://maven.aliyun.com/repository/public"
export SFORGE_GO_PROXY="https://goproxy.cn"

sforge build --task ad_placement_optimization
```

### 运行阶段配方（通用）

运行阶段通常只需要 API 访问和 Node.js 镜像（用于 Claude Code / Codex Agent 的安装）：

```bash
export SFORGE_AGENT_API_KEY="sk-ant-..."
export SFORGE_AGENT_API_BASE_URL="https://api.anthropic.com"
export SFORGE_NODEJS_MIRROR_URL="https://mirrors.aliyun.com/nodejs-release/"

sforge run --task ad_placement_optimization --agent claude-code
```

详细的网络配置指南请参见[网络与镜像源](/zh/configuration/network-setup)。

## 构建失败

### 查看构建日志

构建日志写入 `logs/build_images/` 目录：

```
logs/build_images/
├── base/<benchmark>.base.<base_image>__<hash>/build_image.log
├── work/<benchmark>.work.<task>__<hash>/build_image.log
└── judge/<benchmark>.judge.<task>__<hash>/build_image.log
```

::: tip
构建失败时，务必先查看日志文件。终端中的错误信息通常被截断，而日志文件包含完整的 Docker build 输出。
:::

### 强制重建

如果镜像看起来已缓存但实际上已损坏，可以强制重建：

```bash
sforge build --task ad_placement_optimization --force-rebuild
```

### 常见构建错误

| 错误 | 原因 | 修复 |
|------|------|------|
| `unable to resolve host` | Docker 构建中 DNS 解析失败 | 设置 `SFORGE_EXTRA_HOSTS` 或配置 Docker daemon DNS |
| `Could not fetch URL`（pip） | PyPI 不可达 | 设置 `SFORGE_PYPI_INDEX_URL` |
| `E: Failed to fetch`（apt） | APT 镜像源不可达 | 设置 `SFORGE_APT_MIRROR_URL` |
| `fatal: unable to access`（git） | GitHub 不可达 | 设置代理或使用 `SFORGE_EXTRA_HOSTS` |
| `COPY failed: file not found` | Dockerfile 上下文问题 | 请提交 bug 报告 |

## Agent 问题

### Agent 安装失败

检查安装日志：

```bash
cat logs/runs/<run_id>/<task_id>/install_output.txt
```

常见原因：
- Node.js 下载失败（Claude Code / Codex 需要）：设置 `SFORGE_NODEJS_MIRROR_URL`
- NPM 包超时：设置 `SFORGE_NPM_REGISTRY_URL`
- Agent CLI 安装失败：npm 类 Agent 使用 `SFORGE_NODEJS_MIRROR_URL` 和 `SFORGE_NPM_REGISTRY_URL`，其他安装器可通过 `SFORGE_AGENT_EXTRA_ENV` 注入所需环境变量

### Agent 卡住或没有进展

检查 Agent 对话日志：

```bash
# 查看完整输出
cat logs/runs/<run_id>/<task_id>/agent_output.txt

# 仅提取 assistant 文本（Claude Code 格式）
jq -r 'select(.type == "assistant") | .message.content[] | select(.type == "text") | .text' \
  logs/runs/<run_id>/<task_id>/agent_output.txt

# 实时查看 Agent 调用的工具
grep -o '"name":"[^"]*"' logs/runs/<run_id>/<task_id>/agent_output.txt
```

### Agent 提前退出

如果 Agent 在超时前退出，而你希望它继续工作，确保 stop hook 已启用（`claude-code` 和 `codex` 默认启用）：

```bash
# Stop hook 默认启用，不要传 --disable-stop-hook
sforge run --task ad_placement_optimization --agent claude-code
```

### 没有提交记录

如果 Agent 运行了但历史中没有提交记录：

1. 确认 Judge 服务器在整个 Agent 会话期间持续运行
2. 检查 `agent_output.txt` 中是否有 `sforge-submit` 调用
3. 如果 auto-eval 被禁用且 Agent 从未调用 `sforge-submit`，则不会有提交记录

## 日志目录结构

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
        ├── run_config.json          # 整次运行的统一配置
        ├── summary.json             # 多任务汇总（如适用）
        └── <task_id>/
            ├── run_config.json      # 每个任务的生效配置
            ├── run_agent.log        # 框架层日志
            ├── install_output.txt   # Agent 安装输出
            ├── agent_prompt.md      # 增强后的 prompt
            ├── agent_output.txt     # Agent 完整对话
            ├── final_archive.tar.gz # 最终代码快照
            ├── final_result.json    # 最优分和运行元数据
            ├── run_history.json     # 所有提交条目
            └── submissions/
                ├── agent-1/         # 第一次手动提交
                │   ├── eval_output.txt
                │   └── eval_report.json
                ├── agent-2/
                ├── auto-1/          # 第一次自动评测
                └── ...
```

## 容器清理

SForge 在退出时会自动清理容器（v0.2.2 改进了此行为）。但如果进程被 `SIGKILL` 强制终止，容器可能会残留。

### 检查残留容器

```bash
docker ps --filter "name=sforge"
```

### 停止所有 SForge 容器

```bash
docker ps --filter "name=sforge" -q | xargs -r docker stop
docker ps --filter "name=sforge" -aq | xargs -r docker rm
```

### 网络隔离清理

使用 `--disable-internet` 时，SForge 会创建 iptables 规则来阻断容器流量。这些规则在下次运行时会自动清理，但你也可以手动删除：

```bash
# 列出 SForge 的 iptables 规则
sudo iptables -L DOCKER-USER -n --line-numbers | grep sforge

# 按行号删除特定规则
sudo iptables -D DOCKER-USER <行号>
```

## 常见问题

**Q：什么时候需要强制重建镜像？**
A：修改任务 JSON 中的 `setup_cmds` 或 `base_image` 后。内容哈希会自动变化，通常 SForge 能检测到并自动重建。如果镜像损坏或需要完全干净的构建，使用 `--force-rebuild`。

**Q：修改 `agent_query` 需要重建镜像吗？**
A：不需要。Agent prompt 在运行时注入，不会烘焙到 Docker 镜像中。可以随意修改。

**Q：可以并行运行多个任务吗？**
A：可以。在 `--task` 后传入多个任务 ID：
```bash
sforge run --task ad_placement_optimization gitlet rookiedb --agent claude-code
```
所有任务并行运行，共用一个 Judge 服务器实例。Judge 服务器通过多线程处理并发提交。

**Q：如何比较不同运行的结果？**
A：使用可视化工具：
```bash
sforge visualizer --runs-dir logs/runs
```
或者检查每个运行目录中的 `final_result.json`。

**Q：Agent 在运行但看不到输出。**
A：多任务运行时，详细输出会被自动禁用。请查看 `logs/runs/<run_id>/<task_id>/` 中的日志文件。单任务运行时，确保没有设置 `--silent`。

**Q：如何增加评测超时时间？**
A：评测超时在任务 JSON 中按任务设置（`judge.eval_timeout`）。Agent 超时通过 CLI 的 `--timeout` 设置。两者独立——`eval_timeout` 控制单次测试运行的时间上限，`--timeout` 控制 Agent 总的工作时间。

**Q：Docker pull 失败怎么办？**
A：需要配置 Docker daemon 代理或 registry mirrors。参见上方"构建配方"章节或[网络与镜像源](/zh/configuration/network-setup)。
