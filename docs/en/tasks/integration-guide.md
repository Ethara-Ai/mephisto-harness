# Benchmark & Task Integration

This guide covers everything you need to know to add a new evaluation task to SForge.

## Overview

The core work of integrating a new task is writing a task JSON that uses `setup_cmds` to precisely control the contents of the Work and Judge images, then building images and running an agent to verify.

Typical workflow:

1. **Design the task** — prepare a code repository with skeleton code, documentation, and a test suite.
2. **Write the task JSON** — create `tasks/<task_id>.json` describing:
   - `work.setup_cmds`: clone the repo, install dependencies, **delete test scripts**, reset git history.
   - `judge.setup_cmds`: clone the same repo, install dependencies, but **keep the full test suite**.
   - `eval_cmd`: the command to run tests inside the judge container.
   - `agent_query`: the prompt given to the agent.
3. **Build images** — `sforge build --task <task_id>` builds the base/work/judge images.
4. **Start the judge server** — `sforge serve`.
5. **Run an agent to verify** — `sforge run --task <task_id> --agent claude-code` and confirm the evaluation pipeline works end-to-end.

A benchmark directory contains a `BENCHMARK.yaml` (defining shared base images) plus multiple task JSON files. Each task JSON defines a two-container evaluation setup: a Work image for the agent and a Judge image for grading, fully isolated from each other.

## `BENCHMARK.yaml`

A benchmark directory contains many task JSON files plus one `BENCHMARK.yaml`. The YAML file defines benchmark-level metadata used by every task in that directory.

Typical structure:

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

Key roles:

- `name` becomes the benchmark prefix in image names, e.g. `edgebench.work.ad_placement_optimization:<tag>`.
- `base_images` is the registry of allowed `base_image` keys for task JSON files. A task with `"base_image": "cpp"` resolves that key through `BENCHMARK.yaml`.
- The selected base image entry participates in the base/work/judge image hash. Changing a base image definition changes downstream image hashes.
- `extra_packages`, `user_directive`, and `post_install_directive` let benchmark maintainers customize the shared runtime environment without changing SForge code.

In short: task JSON files describe individual tasks; `BENCHMARK.yaml` describes shared benchmark-level runtime definitions.


## Task JSON Structure

A complete task definition with all available fields:

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
    "agent_query": "Read the project documentation and implement all modules under src/. Call sforge-submit to submit for evaluation when ready."
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

## Field Reference

### Top-Level Fields

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `task_id` | `string` | Yes | -- | Unique identifier. Used in image names (`<benchmark>.work.<task_id>`), CLI flags, and log directories. Use lowercase with underscores. |
| `name` | `string` | Yes | -- | Human-readable display name. |
| `base_image` | `string` | Yes | -- | Base image key, e.g. `python`. Must match a key in `tasks/BENCHMARK.yaml`. |
| `platform` | `string` | Yes | -- | Docker platform. Typically `linux/amd64`. |
| `cwd` | `string` | Yes | -- | Working directory inside both containers. All relative paths in `eval_cmd` resolve from here. |
| `submit_paths` | `list[str]` | Yes | -- | Paths (relative to `cwd`) to include in submission archives. Use `["."]` for everything, or specific paths like `["src/", "main.py"]`. |
| `submit_exclude` | `list[str]` | No | `["tests/"]` | Paths to exclude from submission archives. Critical for preventing accidental test file overwrites in the judge container. |
| `internet` | `bool` | No | `true` | Whether the work container has internet access. Set to `false` for tasks that must be solved offline. |
| `game_mode` | `bool` | No | `false` | Enable interactive game mode. When `true`, a game server runs inside the judge container and the agent interacts via HTTP instead of submitting archives. |

### Work Fields (`work.*`)

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `setup_cmds` | `list[str]` | Yes* | Shell commands executed during image build. Must clone/copy the project, install dependencies, and **delete test files**. Either `setup_cmds` or `image_tag` is required. |
| `image_tag` | `string` | No | Pre-built work image tag. When used with `setup_cmds`, it must match the computed 12-character hash. When used alone, build is skipped and the image must already exist or be pulled with `sforge pull`. |
| `specs_dir` | `string` | Yes | Directory containing specification/documentation files visible to the agent. |
| `agent_query` | `string` | Yes | The prompt given to the agent. Should describe the task, expected output, and constraints. |
| `cpu_limit` | `int` | No | Per-task CPU limit for the work container. CLI/env limits override this. |
| `mem_limit` | `string` | No | Per-task memory limit for the work container, e.g. `"8g"`. CLI/env limits override this. |

### Judge Fields (`judge.*`)

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `setup_cmds` | `list[str]` | Yes* | -- | Shell commands for the judge image. Typically clones/copies the same repo **without** deleting tests, and installs test dependencies. Either `setup_cmds` or `image_tag` is required. |
| `image_tag` | `string` | No | -- | Pre-built judge image tag. When used with `setup_cmds`, it must match the computed 12-character hash. When used alone, build is skipped and the image must already exist or be pulled with `sforge pull`. |
| `eval_cmd` | `string` | Yes | -- | Command to run tests. Must produce output parseable by the specified `parser`. |
| `eval_timeout` | `int` | No | `600` | Maximum seconds for `eval_cmd` to run before being killed. |
| `parser` | `string` | Yes | -- | Parser name for test output. One of: `structured_json`, `pytest_v`, `score_sum`. See [Test Output Parsers](./parsers). |
| `score_direction` | `string` | No | `"maximize"` | Whether higher scores (`"maximize"`) or lower scores (`"minimize"`) are better. Only relevant for score-based tasks. |
| `selection` | `string` | No | `"pass_rate_first"` | How the best submission is selected: `"pass_rate_first"` (default -- highest pass rate wins; score breaks ties at 100%), `"score_first"` (best score wins directly), or `"valid_then_score"` (filter invalid, then best score). |
| `game_server_cmd` | `string` | No | `null` | Command to start the game server inside the judge container. Only used when `game_mode: true`. |
| `cpu_limit` | `int` | No | -- | Per-task CPU limit for judge containers. CLI/env limits override this. |
| `mem_limit` | `string` | No | -- | Per-task memory limit for judge containers, e.g. `"4g"`. CLI/env limits override this. |

## `setup_cmds` and `image_tag`

`setup_cmds` and `image_tag` control whether SForge can build an image locally or should rely on a pre-built image. The same rules apply independently to `work` and `judge`.

| Case | Meaning | Can `sforge build` debug it? | Typical use |
|------|---------|------------------------------|-------------|
| `setup_cmds` only | SForge computes the image hash from `setup_cmds` and builds the image locally. | Yes | Developing or debugging a new task |
| `image_tag` only | The task references an already-built image tag. SForge cannot reconstruct the image because build commands are absent. | No; use `sforge pull` or provide `setup_cmds` | Released benchmark tasks with pre-built images |
| Both `setup_cmds` and `image_tag` | SForge validates that `image_tag` equals the first 12 chars of the hash computed from `setup_cmds`. | Yes | Publishing tasks while keeping reproducible build commands |
| Neither | Invalid. Task loading fails. | No | -- |

Important details from the implementation:

- Task loading fails if both fields are missing.
- If both fields are present but the tag does not match the computed hash, task loading fails.
- `sforge build` requires `setup_cmds`. If an image is missing and only `image_tag` is provided, build fails with a message telling you to pull the image first.
- Therefore, tasks that need local build/debug must include `setup_cmds` for both `work` and `judge`.
- `image_tag`-only task JSON is suitable for evaluation users who consume released tasks with pre-built images via `sforge pull`.

## The `setup_cmds` Pattern

### Work Container

The work `setup_cmds` must follow this pattern:

```json
"setup_cmds": [
  "mkdir -p /home/workspace && cd /home/workspace && git clone <repo_url>",
  "cd /home/workspace/my_project && pip install -r requirements.txt",
  "rm -rf /home/workspace/my_project/tests",
  "cd /home/workspace/my_project && rm -rf .git && git init && git config user.email 'sforge@local' && git config user.name 'sforge' && git add -A && git commit -m 'init'"
]
```

**Test removal is critical and must not be skipped:**

1. **Delete test files** -- The agent must never see the test suite. Remove all test directories and files. If the project has tests scattered across modules, be thorough.

2. **Initialize a fresh git repo when useful** -- This is recommended for agents that inspect diffs, but it is no longer required for submission. `sforge-submit` archives `submit_paths` with `tar`, applying `submit_exclude` rules directly.

### Judge Container

The judge `setup_cmds` are similar but **keep the tests** and **skip the git init**:

```json
"setup_cmds": [
  "mkdir -p /home/workspace && cd /home/workspace && git clone <repo_url>",
  "cd /home/workspace/my_project && pip install -r requirements.txt && pip install pytest"
]
```

## Base Image Registry

Each `base_image` value maps to an entry in the benchmark `BENCHMARK.yaml`. Standard base image keys are:

| Key | Typical Docker Image | Typical Use |
|-----|----------------------|-------------|
| `python` | `python:3.11` | Python tasks |
| `cpp` | `ubuntu:22.04` | C/C++ tasks |
| `java` | `maven:3.9-eclipse-temurin-17` | Java/Maven tasks |
| `go` | `golang:1.22` | Go tasks |
| `rust` | `rust:1.78` | Rust tasks |

## Selection Strategies

| Policy | Behavior |
|--------|----------|
| `pass_rate_first` | Compare by `pass_rate`; when both reach 100%, compare by `score` using `score_direction`. Default for test-driven tasks. |
| `score_first` | Compare directly by `score` using `score_direction`. Useful for optimization tasks. |
| `valid_then_score` | Filter out submissions with `valid: false`, then apply `score_first`. |

`score_direction` is `maximize` by default; set it to `minimize` for metrics such as error or runtime.

## Image Hashes

SForge uses content hashes for image names:

| Image | Hash input |
|-------|------------|
| Base | `base_image` key + the matching `BENCHMARK.yaml` entry |
| Work | `base_hash`, `platform`, `cwd`, and `work.setup_cmds` |
| Judge | `base_hash`, `platform`, `cwd`, and `judge.setup_cmds` |

The image tag is the first 12 characters of the hash, for example `<benchmark>.work.ad_placement_optimization:a1b2c3d4e5f6`. Changing `agent_query`, `eval_cmd`, or `parser` does not change the image hash because those are runtime inputs rather than baked image setup commands.

## Design Guidelines

### Test File Isolation

The agent must never see the test scripts. This is the fundamental principle of SForge evaluation. Ensure that:

- All test files are removed in work `setup_cmds`
- `submit_exclude` blocks test directories from being overwritten in the judge container
- The agent prompt does not reveal specific test names or logic

::: warning
If `submit_exclude` is not configured correctly, an agent could submit files that overwrite the judge's test suite, making the evaluation meaningless.
:::

### Feedback Granularity

The amount of information returned to the agent affects task difficulty:

| Level | What the agent sees | Difficulty |
|-------|---------------------|------------|
| Score only | `pass_rate: 0.65` | Hardest |
| Failed test names | `FAILED: test_add, test_mul` | Medium |
| Full stack traces | Complete pytest output | Easiest |

By default, `sforge-submit` shows the pass rate and up to 10 failed test names. For harder tasks, consider a custom eval script that outputs less information.

### Writing `agent_query`

The agent prompt should include:

1. **Role** -- What the agent is (e.g., "You are an expert systems programmer...")
2. **Overview** -- What the project does and what needs to be built
3. **Workflow** -- Step-by-step instructions (read docs first, implement module by module, etc.)
4. **Constraints** -- What the agent must not do (don't modify tests, don't change interfaces)
5. **File structure** -- Where to find specifications and where to write code

Keep the prompt concise but complete. The agent also receives instructions about `sforge-submit` automatically.

### Choosing `submit_paths`

- Use `["."]` when the agent may need to modify files anywhere in the project
- Use specific paths like `["src/", "main.py"]` to restrict what gets submitted
- Always pair with `submit_exclude` to protect test files

### Evaluation Command Requirements

The `eval_cmd` must produce output compatible with the chosen parser:

| Parser | Required output format |
|--------|-----------------------|
| `structured_json` | JSON with `valid`, `score`, `summary`, `details`, etc. (recommended) |
| `pytest_v` | `pytest -v` (verbose mode required) |
| `score_sum` | `CASE <id> <status> score=<n>` and `TOTAL_SCORE <n>` lines |

See [Test Output Parsers](./parsers) for detailed format specifications.

### Avoiding Common Pitfalls

- **Do not hardcode mirrors or proxies.** Use `${SFORGE_PYPI_INDEX_URL}`, `${SFORGE_MAVEN_MIRROR_URL}`, etc. These are injected as build args and container env vars automatically.
- **Do not embed base64 blobs in JSON.** If you need to deploy scripts to the judge, write them inline with heredocs or clone them from a repository.
- **Set appropriate `eval_timeout`.** For CPU-intensive evaluation (compiling large projects, running many test cases), increase the timeout. Default is 600 seconds.
- **Do not use tokens directly.** Use `${SFORGE_GIT_USER}` and `${SFORGE_GIT_TOKEN}` for private repositories.

## Integration Steps

### Step 1: Create the Task JSON

Create `tasks/<task_id>.json` with all required fields. Start from an existing task that is similar to yours.

### Step 2: Register a New Language (If Needed)

If your task requires a base image not already in the registry, add it to `BENCHMARK.yaml` in the `tasks/` directory:

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

Then set `base_image` in your task JSON to `"my_language"`.

### Step 3: Add a New Parser (If Needed)

If your test runner produces output that no existing parser handles:

1. Create `sforge/harness/log_parsers/my_parser.py` with a function `parse_my_parser(test_output: str) -> list[dict]`
2. Each dict must have `{"name": str, "status": "PASSED"|"FAILED"|"ERROR"}`
3. Register it in `sforge/harness/log_parsers/__init__.py`:

```python
from sforge.harness.log_parsers.my_parser import parse_my_parser

MAP_TASK_TO_PARSER["my_parser"] = parse_my_parser
```

### Step 4: Build and Test Images

```bash
# Build base + work + judge images
sforge build --task my_task

# Force rebuild if setup_cmds changed
sforge build --task my_task --force-rebuild
```

### Step 5: Verify Evaluation

Test the evaluation pipeline end-to-end:

```bash
# Start the judge server
sforge serve --port 8080

# Run an agent (or use a known solution for testing)
sforge run --task my_task --agent claude-code

# Or evaluate a pre-made archive directly
sforge eval --task my_task --archive solution.tar.gz --json
```

Check that:
- The work container builds without errors
- The judge container builds without errors
- Evaluation produces expected pass/fail results
- The parser correctly identifies test names and statuses
- Score direction and selection policy work as intended

