# Benchmark 与任务接入

本文档详细介绍如何为 SForge 添加新的评测任务。

## 概述

接入一个新任务的核心工作是编写一份任务 JSON，通过 `setup_cmds` 精确控制 Work 和 Judge 两个镜像中的内容，然后用 SForge 构建镜像、运行 Agent 来验证。

典型流程：

1. **设计题目** — 准备好项目代码仓库（含骨架代码、文档和测试套件）。
2. **编写任务 JSON** — 在 `tasks/<task_id>.json` 中描述：
   - `work.setup_cmds`：克隆仓库、安装依赖、**删除测试脚本**、重置 git 记录。
   - `judge.setup_cmds`：克隆同一仓库、安装依赖，但**保留完整测试套件**。
   - `eval_cmd`：Judge 容器中运行测试的命令。
   - `agent_query`：传递给 Agent 的任务 prompt。
3. **构建镜像** — `sforge build --task <task_id>` 构建 base/work/judge 三个镜像。
4. **启动 Judge 服务器** — `sforge serve`。
5. **运行 Agent 验证** — `sforge run --task <task_id> --agent claude-code`，确认评测流程端到端通畅。

一个 benchmark 目录包含 `BENCHMARK.yaml`（定义共享基础镜像）以及多个任务 JSON 文件。每个任务 JSON 定义了双容器评测架构：Work 镜像供 Agent 工作，Judge 镜像供评测，两者完全隔离。

## `BENCHMARK.yaml`

一个 benchmark 目录通常包含多个任务 JSON 文件，以及一个 `BENCHMARK.yaml`。该 YAML 文件定义所有任务共享的 benchmark 级元数据。

典型结构：

```yaml
name: edgebench
base_images:
  python:
    official_image: python:3.11
    extra_packages:
      - git
      - curl
      - jq
      - build-essential
  cpp:
    official_image: ubuntu:22.04
    extra_packages:
      - git
      - curl
      - jq
      - build-essential
      - cmake
      - gcc
      - g++
```

主要作用：

- `name` 会成为镜像名前缀，例如 `edgebench.work.ad_placement_optimization:<tag>`。
- `base_images` 是任务 JSON 中可用 `base_image` 键名的注册表。任务里的 `"base_image": "cpp"` 会通过 `BENCHMARK.yaml` 解析到具体基础镜像。
- 被选中的基础镜像条目会参与 base/work/judge 镜像哈希计算。修改基础镜像定义会改变下游镜像哈希。
- `extra_packages`、`user_directive`、`post_install_directive` 可用于定制 benchmark 共享运行环境，而不需要修改 SForge 框架代码。

简而言之：任务 JSON 描述单个任务；`BENCHMARK.yaml` 描述 benchmark 级共享运行环境定义。


## 任务 JSON 结构

完整的任务定义及所有可用字段：

```json
{
  "task_id": "my_task",
  "name": "My Task",
  "base_image": "python",
  "platform": "linux/amd64",
  "cwd": "/home/workspace/my_project",
  "submit_paths": ["src/", "main.py"],
  "submit_exclude": ["tests/"],
  "internet": true,
  "game_mode": false,
  "work": {
    "setup_cmds": [
      "git clone https://github.com/example/my_project.git /home/workspace/my_project",
      "cd /home/workspace/my_project && pip install -e .",
      "rm -rf /home/workspace/my_project/tests /home/workspace/my_project/test_*.py",
      "cd /home/workspace/my_project && rm -rf .git && git init && git config user.email 'sforge@local' && git config user.name 'sforge' && git add -A && git commit -m 'init'"
    ],
    "specs_dir": "/home/workspace/my_project",
    "agent_query": "阅读项目文档，在 src/ 目录下实现所有模块。完成后调用 sforge-submit 提交评测。"
  },
  "judge": {
    "setup_cmds": [
      "git clone https://github.com/example/my_project.git /home/workspace/my_project",
      "cd /home/workspace/my_project && pip install -e . && pip install pytest"
    ],
    "eval_cmd": "cd /home/workspace/my_project && python -m pytest tests/ -v",
    "eval_timeout": 600,
    "parser": "pytest_v",
    "score_direction": "maximize",
    "selection": "pass_rate_first"
  }
}
```

## 字段说明

### 顶层字段

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `task_id` | `string` | 是 | -- | 唯一标识符，用于镜像名称（`<benchmark>.work.<task_id>`）、CLI 参数和日志目录。请使用小写字母加下划线。 |
| `name` | `string` | 是 | -- | 任务的展示名称。 |
| `base_image` | `string` | 是 | -- | 基础镜像键名，如 `python`。必须与 `tasks/BENCHMARK.yaml` 中的某个键匹配。 |
| `platform` | `string` | 是 | -- | Docker 平台，通常为 `linux/amd64`。 |
| `cwd` | `string` | 是 | -- | 两个容器中的工作目录。`eval_cmd` 中的相对路径以此目录为基准解析。 |
| `submit_paths` | `list[str]` | 是 | -- | 提交归档中包含的路径（相对于 `cwd`）。用 `["."]` 表示包含整个项目，或指定具体路径如 `["src/", "main.py"]`。 |
| `submit_exclude` | `list[str]` | 否 | `["tests/"]` | 提交归档中排除的路径。用于防止 Agent 意外覆盖 Judge 容器中的测试文件。 |
| `internet` | `bool` | 否 | `true` | Work 容器是否可访问网络。对于必须离线完成的任务设为 `false`。 |
| `game_mode` | `bool` | 否 | `false` | 是否启用交互式游戏模式。开启后 Agent 通过 HTTP 与游戏服务器交互，而非提交代码归档。 |

### Work 字段（`work.*`）

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `setup_cmds` | `list[str]` | 是* | 镜像构建时执行的 Shell 命令。必须克隆/复制项目、安装依赖并**删除测试文件**。`setup_cmds` 或 `image_tag` 二者必须指定其一。 |
| `image_tag` | `string` | 否 | 预构建 Work 镜像标签。与 `setup_cmds` 同时使用时，必须匹配计算出的 12 位哈希；单独使用时会跳过构建，镜像必须已存在或通过 `sforge pull` 拉取。 |
| `specs_dir` | `string` | 是 | 包含规格说明和文档的目录路径，Agent 可见。 |
| `agent_query` | `string` | 是 | 传递给 Agent 的 prompt，应描述任务内容、预期输出和约束条件。 |
| `cpu_limit` | `int` | 否 | Work 容器的任务级 CPU 限制。CLI/环境变量限制会覆盖它。 |
| `mem_limit` | `string` | 否 | Work 容器的任务级内存限制，如 `"8g"`。CLI/环境变量限制会覆盖它。 |

### Judge 字段（`judge.*`）

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `setup_cmds` | `list[str]` | 是* | -- | Judge 镜像的构建命令。通常克隆/复制同一仓库但**保留测试文件**，并安装测试依赖。`setup_cmds` 或 `image_tag` 二者必须指定其一。 |
| `image_tag` | `string` | 否 | -- | 预构建 Judge 镜像标签。与 `setup_cmds` 同时使用时，必须匹配计算出的 12 位哈希；单独使用时会跳过构建，镜像必须已存在或通过 `sforge pull` 拉取。 |
| `eval_cmd` | `string` | 是 | -- | 评测命令。输出必须能被指定的 `parser` 解析。 |
| `eval_timeout` | `int` | 否 | `600` | `eval_cmd` 的最大运行时间（秒）。超时会被终止。 |
| `parser` | `string` | 是 | -- | 解析器名称：`structured_json`、`pytest_v`、`score_sum`。详见[测试输出解析器](./parsers)。 |
| `score_direction` | `string` | 否 | `"maximize"` | 分数方向：分数越高越好（`"maximize"`）或分数越低越好（`"minimize"`）。仅对连续评分任务有意义。 |
| `selection` | `string` | 否 | `"pass_rate_first"` | 最优提交选择策略：`"pass_rate_first"`（默认，通过率优先；100% 时再比分数）、`"score_first"`（直接比较分数）、`"valid_then_score"`（过滤无效提交后比较分数）。 |
| `game_server_cmd` | `string` | 否 | `null` | 在 Judge 容器中启动游戏服务器的命令。仅在 `game_mode: true` 时使用。 |
| `cpu_limit` | `int` | 否 | -- | Judge 容器的任务级 CPU 限制。CLI/环境变量限制会覆盖它。 |
| `mem_limit` | `string` | 否 | -- | Judge 容器的任务级内存限制，如 `"4g"`。CLI/环境变量限制会覆盖它。 |

## `setup_cmds` 与 `image_tag`

`setup_cmds` 和 `image_tag` 决定 SForge 是可以本地构建镜像，还是只能依赖预构建镜像。规则对 `work` 和 `judge` 分别独立生效。

| 情况 | 含义 | 能否用 `sforge build` 调试？ | 典型用途 |
|------|------|------------------------------|----------|
| 只有 `setup_cmds` | SForge 根据 `setup_cmds` 计算镜像哈希，并在本地构建镜像。 | 可以 | 开发或调试新任务 |
| 只有 `image_tag` | 任务引用已经构建好的镜像标签；因为没有构建命令，SForge 无法还原镜像。 | 不可以；需要 `sforge pull`，或补充 `setup_cmds` | 发布后的 benchmark 任务，供评测用户拉取预构建镜像 |
| 同时有 `setup_cmds` 和 `image_tag` | SForge 会校验 `image_tag` 是否等于根据 `setup_cmds` 计算出的哈希前 12 位。 | 可以 | 发布任务时同时保留可复现的构建命令 |
| 两者都没有 | 非法，任务加载会失败。 | 不可以 | -- |

实现层面的关键点：

- 两者都缺失时，任务加载失败。
- 两者同时存在但 `image_tag` 与计算哈希不一致时，任务加载失败。
- `sforge build` 必须依赖 `setup_cmds`。如果本地镜像不存在且任务只有 `image_tag`，build 会失败并提示先 pull 镜像。
- 因此，需要本地 build/debug 的任务，`work` 和 `judge` 都必须提供 `setup_cmds`。
- 只有 `image_tag` 的任务 JSON 更适合发布后的评测用户，通过 `sforge pull` 使用预构建镜像。

## `setup_cmds` 编写规范

### Work 容器

Work 容器的 `setup_cmds` 必须遵循以下模式：

```json
"setup_cmds": [
  "mkdir -p /home/workspace && cd /home/workspace && git clone <repo_url>",
  "cd /home/workspace/my_project && pip install -r requirements.txt",
  "rm -rf /home/workspace/my_project/tests",
  "cd /home/workspace/my_project && rm -rf .git && git init && git config user.email 'sforge@local' && git config user.name 'sforge' && git add -A && git commit -m 'init'"
]
```

**删除测试文件至关重要，不可省略：**

1. **删除测试文件** -- Agent 绝对不能看到测试套件。必须删除所有测试目录和文件。如果测试文件分散在多个模块中，要确保全部清除。

2. **按需初始化新的 git 仓库** -- 对需要查看 diff 的 Agent 很有帮助，但提交本身不再依赖 git。`sforge-submit` 现在使用 `tar` 归档 `submit_paths`，并直接应用 `submit_exclude` 规则。

### Judge 容器

Judge 容器的 `setup_cmds` 类似，但**保留测试文件**且**不需要 git init**：

```json
"setup_cmds": [
  "mkdir -p /home/workspace && cd /home/workspace && git clone <repo_url>",
  "cd /home/workspace/my_project && pip install -r requirements.txt && pip install pytest"
]
```

## 基础镜像注册表

每个 `base_image` 值对应 benchmark 的 `BENCHMARK.yaml` 中的一个条目。标准基础镜像键名包括：

| 键名 | 典型 Docker 镜像 | 典型用途 |
|------|------------------|----------|
| `python` | `python:3.11` | Python 任务 |
| `cpp` | `ubuntu:22.04` | C/C++ 任务 |
| `java` | `maven:3.9-eclipse-temurin-17` | Java/Maven 任务 |
| `go` | `golang:1.22` | Go 任务 |
| `rust` | `rust:1.78` | Rust 任务 |

## 选择策略

| 策略 | 行为 |
|------|------|
| `pass_rate_first` | 按 `pass_rate` 比较；当两者都达到 100% 时，按 `score` 比较（遵循 `score_direction`）。测试驱动任务的默认策略。 |
| `score_first` | 直接按 `score` 比较（遵循 `score_direction`）。适用于优化类任务。 |
| `valid_then_score` | 先过滤掉 `valid: false` 的提交，再对剩余条目使用 `score_first`。 |

`score_direction` 默认为 `maximize`；对于误差、耗时等指标可设置为 `minimize`。

## 镜像哈希

SForge 使用内容哈希生成镜像名称：

| 镜像 | 哈希输入 |
|------|----------|
| Base | `base_image` 键名 + 对应的 `BENCHMARK.yaml` 条目 |
| Work | `base_hash`、`platform`、`cwd` 和 `work.setup_cmds` |
| Judge | `base_hash`、`platform`、`cwd` 和 `judge.setup_cmds` |

镜像标签使用哈希值前 12 个字符，例如 `<benchmark>.work.ad_placement_optimization:a1b2c3d4e5f6`。修改 `agent_query`、`eval_cmd` 或 `parser` 不会改变镜像哈希，因为它们是运行时输入，不属于镜像构建命令。

## 设计指南

### 测试文件隔离

测试脚本对 Agent 不可见是 SForge 评测的基本原则。请确保：

- 在 Work 的 `setup_cmds` 中删除所有测试文件
- 通过 `submit_exclude` 阻止 Agent 覆盖 Judge 容器中的测试文件
- Agent prompt 中不要透露具体的测试名称或逻辑

::: warning
如果 `submit_exclude` 配置不当，Agent 可能提交覆盖 Judge 测试套件的文件，导致评测失效。
:::

### 反馈粒度

返回给 Agent 的信息量会影响任务难度：

| 级别 | Agent 看到的内容 | 难度 |
|------|-----------------|------|
| 仅分数 | `pass_rate: 0.65` | 最难 |
| 失败测试名 | `FAILED: test_add, test_mul` | 中等 |
| 完整错误栈 | 完整 pytest 输出 | 最容易 |

默认情况下，`sforge-submit` 会显示通过率和最多 10 个失败测试名。对于更高难度的任务，可以编写自定义评测脚本来控制输出信息量。

### 编写 `agent_query`

Agent prompt 应包含以下内容：

1. **角色定义** -- Agent 扮演什么角色（如"你是一位资深系统开发工程师..."）
2. **项目概述** -- 项目功能及需要完成的工作
3. **实施步骤** -- 分步指导（先读文档、逐模块实现等）
4. **约束条件** -- Agent 不能做什么（不要修改测试、不要改接口）
5. **目录结构** -- 在哪里查看规格说明、在哪里编写代码

Prompt 要简洁但完整。Agent 还会自动收到关于 `sforge-submit` 的使用说明。

### 选择 `submit_paths`

- 当 Agent 可能需要修改项目中任意位置的文件时，使用 `["."]`
- 用具体路径如 `["src/", "main.py"]` 来限制提交范围
- 始终配合 `submit_exclude` 保护测试文件

### 评测命令输出要求

`eval_cmd` 的输出必须与所选解析器兼容：

| 解析器 | 要求的输出格式 |
|--------|---------------|
| `structured_json` | 包含 `valid`、`score`、`summary`、`details` 等字段的 JSON（推荐） |
| `pytest_v` | `pytest -v`（必须开启 verbose 模式） |
| `score_sum` | `CASE <id> <status> score=<n>` 和 `TOTAL_SCORE <n>` 格式 |

详见[测试输出解析器](./parsers)。

### 避免常见问题

- **不要硬编码镜像源或代理。** 使用 `${SFORGE_PYPI_INDEX_URL}`、`${SFORGE_MAVEN_MIRROR_URL}` 等变量。这些会作为构建参数和容器环境变量自动注入。
- **不要在 JSON 中嵌入 base64 数据。** 如果需要部署脚本到 Judge 容器，用 heredoc 内联编写或从仓库克隆。
- **合理设置 `eval_timeout`。** 对于计算密集型评测（编译大型项目、运行大量测试用例），需要增大超时值。默认为 600 秒。
- **不要直接使用 Token。** 对于私有仓库，使用 `${SFORGE_GIT_USER}` 和 `${SFORGE_GIT_TOKEN}` 环境变量。

## 集成步骤

### 第 1 步：创建任务 JSON

在 `tasks/<task_id>.json` 中编写完整的任务定义。建议从已有的类似任务复制修改。

### 第 2 步：注册新语言（如有需要）

如果任务需要的基础镜像不在现有注册表中，在 `tasks/` 目录下的 `BENCHMARK.yaml` 中添加：

```yaml
base_images:
  my_language:
    official_image: "python:3.12"
    extra_packages:
      - git
      - curl
      - jq
      - build-essential
```

然后在任务 JSON 中设置 `base_image` 为 `"my_language"`。

### 第 3 步：添加新解析器（如有需要）

如果现有解析器都无法处理你的测试输出格式：

1. 在 `sforge/harness/log_parsers/` 下新建文件，编写解析函数 `parse_my_parser(test_output: str) -> list[dict]`
2. 每个字典必须包含 `{"name": str, "status": "PASSED"|"FAILED"|"ERROR"}`
3. 在 `sforge/harness/log_parsers/__init__.py` 中注册：

```python
from sforge.harness.log_parsers.my_parser import parse_my_parser

MAP_TASK_TO_PARSER["my_parser"] = parse_my_parser
```

### 第 4 步：构建和测试镜像

```bash
# 构建基础 + Work + Judge 镜像
sforge build --task my_task

# 如果 setup_cmds 有变更，强制重建
sforge build --task my_task --force-rebuild
```

### 第 5 步：验证评测流程

端到端测试评测流程：

```bash
# 启动 Judge 服务器
sforge serve --port 8080

# 运行 Agent（或使用已知解法进行测试）
sforge run --task my_task --agent claude-code

# 或直接评测一个归档文件
sforge eval --task my_task --archive solution.tar.gz --json
```

检查以下各项：
- Work 容器构建无报错
- Judge 容器构建无报错
- 评测产生预期的通过/失败结果
- 解析器正确识别测试名和状态
- 分数方向和选择策略按预期工作

