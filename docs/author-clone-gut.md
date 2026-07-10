# sforge author-clone-gut — Task-authoring pipeline

## Purpose

Automate the ~70% mechanical work of authoring a clone-and-gut EdgeBench task. Turn what took a full session for `goawk_printf_reimplementation` into a single CLI invocation with a calibration gate that refuses to ship a broken task.

## Non-goals (v1)

- Not authoring **contest-replay**, **LLM-graded**, or **multi-file reconstruction** archetypes. Only clone-and-gut.
- Not drafting `TASK.md` via an LLM. v1 renders a placeholder skeleton the author fills in.
- Not auto-inferring which subtests to grade. Author supplies `--test-filter`.
- Not supporting **commit-range** or **PR revert** mode in v1. Language plugins and CLI surface must be structured so v2 can add them without refactor.
- Not adding non-Go language plugins in v1 code. Rust/Python/TypeScript get stub plugin files that raise `NotImplementedError` so the dispatcher wiring is testable.

## User-facing CLI

```
sforge author-clone-gut \
  --task-id <slug> \
  --name "<display name>" \
  --category <string>           # e.g. code_reconstruction
  --repo <git url> \
  --commit <sha>                # required in v1 (single-commit mode)
  --base <benchmark yaml key>   # e.g. go
  --lang <go|rust|python|typescript>  # v1: only 'go' works; others raise
  --gut <relpath>:<func1>[,<func2>...]  # repeatable
  --cwd </absolute/inside/container>    # e.g. /home/workspace/goawk
  --test-cmd '<full go test command>'   # e.g. "go test -count=1 -timeout=300s -awk= -v -run '^(TestInterp|TestCharsMode)$' ./interp/"
  --test-filter '<substring or /regex/>' # subtest names containing this get counted
  [--internet]                          # default False
  [--tier auto|toy|standard|extreme]    # default 'auto' — classify from LOC+tests
  [--min-tests <N>]                     # default 20 — abort if grading covers fewer
  [--allow-precutoff]                   # bypass contamination check
  [--model-cutoff YYYY-MM-DD]           # default 2025-04-01 (Claude 4.7-family cutoff, per plan)
  [--no-calibrate]                      # skip docker build + judge run
  [--gutted-max <int>]                  # default 5   — gutted score must be ≤ this
  [--golden-min <int>]                  # default 95  — golden score must be ≥ this
  [--eval-timeout <sec>]                # default 600
  [--out-dir tasks/]                    # default tasks/
  [--dry-run]                           # print plan, don't write manifest or build
  [--force]                             # overwrite existing tasks/<id>.json
```

Exit codes:
- `0` — manifest written, calibration passed
- `1` — user error (missing arg, bad path, unknown lang)
- `2` — clone/gut error (repo unreachable, function not found, gut invariant broken)
- `3` — contamination gate failed (commit predates cutoff)
- `4` — calibration failed (gutted score too high or golden score too low)
- `5` — tier gate failed (explicit tier didn't match observed metrics)

## Package layout

```
sforge/author/
  __init__.py                # empty (re-exports optional)
  cli_entry.py               # cmd_author_clone_gut(args) + argparse registration
  config.py                  # AuthorConfig dataclass parsed from argparse.Namespace
  workspace.py               # clone/checkout/temp-dir mgmt
  commit_info.py             # git show, commit date, contamination check
  gutters/
    __init__.py              # get_gutter(lang) -> BaseGutter
    base.py                  # BaseGutter ABC + GutSpec + GutResult
    go.py                    # tree-sitter Go implementation
    rust.py                  # raise NotImplementedError (v1 stub)
    python.py                # raise NotImplementedError
    typescript.py            # raise NotImplementedError
  templates.py               # TASK.md skeleton, setup_workspace.sh, setup_judge.sh, score.sh
  manifest.py                # build manifest dict + write tasks/<id>.json
  benchmark_yaml.py          # add-or-verify base entry in tasks/BENCHMARK.yaml
  calibrate.py               # docker build + judge on gutted / golden
  tier.py                    # classify_tier(loc_gutted, tests_covered) + gate
  errors.py                  # AuthorError hierarchy (CloneError, GutError, CalibrationError, ...)

tests/author/
  test_config.py             # argparse -> AuthorConfig round-trip
  test_gutter_go.py          # gut two funcs in a Go file, verify diff
  test_templates.py          # render each template with fixture, snapshot compare
  test_manifest.py           # emit manifest, load via make_task_spec, assert equality
  test_benchmark_yaml.py     # add new key idempotently; refuse conflict
  test_tier.py               # thresholds
  test_e2e_goawk.py          # end-to-end regeneration of goawk_printf_reimplementation
```

## Dependencies to add to top-level `pyproject.toml` / `requirements`

- `tree_sitter>=0.24`
- `tree_sitter_go>=0.25`
- (Optional dev-only) `tree_sitter_rust`, `tree_sitter_python`, `tree_sitter_typescript` — declared in extras so v2 has them ready.
- `pyyaml` — likely already present (BENCHMARK.yaml is YAML). Verify before adding.

Ship a single `sforge/author/deps.py` that imports lazily and gives clear error messages when a language plugin's tree-sitter module is missing.

## Data model

`sforge/author/config.py`:

```python
@dataclass
class GutTarget:
    rel_path: str              # e.g. "interp/functions.go"
    funcs: list[str]           # e.g. ["parseFmtTypes", "sprintf"]

@dataclass
class AuthorConfig:
    task_id: str
    name: str
    category: str
    repo: str
    commit: str                # v1: required single sha
    base: str                  # BENCHMARK.yaml key
    lang: str                  # go|rust|python|typescript
    gut_targets: list[GutTarget]
    cwd: str
    test_cmd: str
    test_filter: str
    internet: bool = False
    tier: str = "auto"         # auto|toy|standard|extreme
    min_tests: int = 20
    allow_precutoff: bool = False
    model_cutoff: date = date(2025, 4, 1)
    no_calibrate: bool = False
    gutted_max: int = 5
    golden_min: int = 95
    eval_timeout: int = 600
    out_dir: Path = Path("tasks")
    dry_run: bool = False
    force: bool = False
```

`sforge/author/gutters/base.py`:

```python
@dataclass
class GutSpec:
    rel_path: str
    funcs: list[str]

@dataclass
class FunctionInfo:
    name: str
    signature: str             # e.g. "func (p *interp) sprintf(format string, args []value) (string, error)"
    body_start_byte: int
    body_end_byte: int
    body_loc: int              # lines
    receiver: str | None       # e.g. "p *interp"
    params: list[str]          # e.g. ["format string", "args []value"]
    returns: list[str]         # e.g. ["string", "error"]

@dataclass
class GutResult:
    gutted_source: str
    functions: list[FunctionInfo]  # metadata for what was gutted (drives TASK.md skeleton)
    total_loc_gutted: int

class BaseGutter(ABC):
    lang: ClassVar[str]

    @abstractmethod
    def parse_functions(self, source: str) -> list[FunctionInfo]: ...

    @abstractmethod
    def gut(self, source: str, spec: GutSpec) -> GutResult: ...

    @abstractmethod
    def stub_body(self, fn: FunctionInfo) -> str:
        """Return replacement body text (between the { and }) that compiles."""
```

## Component design

### 1. `workspace.py`

- `clone(repo: str, commit: str, work_dir: Path) -> Path` — `git clone --no-checkout` then `git fetch` + `git checkout <sha>`. Uses `subprocess.run(check=True, capture_output=True, timeout=180)`. Returns the checkout path.
- `count_repo_loc(path: Path, lang: str) -> int` — walks source files by extension; feeds tier classification.
- `temp_workspace()` context manager: `tempfile.TemporaryDirectory(prefix="sforge-author-")`.

### 2. `commit_info.py`

- `get_commit_date(repo_path: Path, sha: str) -> date` — `git show -s --format=%ci <sha>`; parses to `date`.
- `check_contamination(commit_date: date, cutoff: date, allow: bool) -> None` — raises `ContaminationError` if `commit_date <= cutoff` and not `allow`. Warning-only if `allow=True`.
- Default cutoff **2025-04-01** — conservative for Claude Sonnet 4.5/Opus 4.7 era. Configurable via `--model-cutoff`. Document the source of the date in a comment; explicitly state the cutoff is a rough gate, not a guarantee.

### 3. `gutters/go.py`

Uses `tree_sitter` + `tree_sitter_go`. Walk pattern:

```python
lang = Language(tree_sitter_go.language())
parser = Parser(lang)
tree = parser.parse(source.encode())

query = lang.query('''
  (function_declaration
    name: (identifier) @name
    body: (block) @body) @func
  (method_declaration
    name: (field_identifier) @name
    body: (block) @body) @func
''')
```

For each capture, extract:
- Signature = bytes from func's `.start_byte` to body's `.start_byte`
- Body braces = body's `.start_byte..end_byte` (inclusive of `{` and `}`)
- Params/returns via child field names

Stub body for Go:
```go
{
    // TODO(agent): reimplement per TASK.md.
    _ = <param1>
    _ = <param2>
    return <zero-values>, errors.New("<funcName>: not implemented")
}
```

Zero-values: `""` for `string`, `nil` for pointers/slices/maps/interfaces, `false` for `bool`, `0` for numerics. If the last return type contains `error`, replace with `errors.New(...)`. Detect via signature parsing; if uncertain, produce `errors.New(...)` for last position and `default_zero(t)` for the rest.

Apply edits in reverse byte order to keep offsets valid.

Import safety: `errors` must be in the import block already for the stub to compile. Gutter must:
1. Parse import block.
2. If `errors` isn't imported and the stub uses it, add `errors` to the import list.
3. If parsing/injection fails, error with clear message ("could not find import block").

The `goawk_printf` case already imports `errors`, so this path is a nice-to-have safety net for other repos.

Sanity check post-gut: run `tree_sitter` parser again on the gutted source; if the resulting tree has **any** ERROR nodes not present in the original, fail loudly (this catches broken brace matching).

### 4. `gutters/{rust,python,typescript}.py`

Each module defines a class that inherits `BaseGutter` and raises `NotImplementedError(f"{lang} gutter not implemented in v1")` when instantiated. Dispatcher registers them so `sforge author-clone-gut --lang rust` produces a clean "not implemented in v1" error, not an import failure.

### 5. `templates.py`

Four templates as `str.format`-style strings (with `{{` / `}}` escaping for bash braces):

- `TASK_MD_TEMPLATE` — starts with a header noting **"[AUTHOR: fill in the contract below]"** followed by an auto-generated section listing each gutted function's signature and containing file. Author edits before shipping. Do NOT pretend the pipeline can write a correct behavioral spec.
- `SETUP_WORKSPACE_SH_TEMPLATE` — clones repo, pins SHA, writes TASK.md + gut script via heredocs, executes gutter, sanity-greps for stub markers, `rm -rf .git && git init && git add -A && git commit`.
- `SETUP_JUDGE_SH_TEMPLATE` — clones repo, pins SHA, warms build cache with two commands the author supplies (via `--build-warm-cmd`, defaults to `go build ./...` and `go test -run '^$' <pkg>`), writes `/tmp/score.sh` via heredoc.
- `SCORE_SH_TEMPLATE` — the Go-test-output parser I already validated. Runs `--test-cmd`, greps `--- (PASS|FAIL|SKIP):`, filters by `--test-filter`, emits `>>>>> Start Structured Result` JSON. Language-independent — if a v2 language plugin needs a different scorer, add a template registry keyed by lang.

Renderer: `render(template_name, **kwargs) -> str`. Kwargs are validated against a per-template allowlist to catch typos.

### 6. `manifest.py`

`build_manifest(cfg: AuthorConfig, gut_results: list[GutResult], setup_workspace: str, setup_judge: str) -> dict`:

- Uses `sforge.harness.task_spec.TaskSpec` construction path — but writes a **dict** matching what `make_task_spec` expects to load.
- Round-trip validation: `write manifest to temp path → make_task_spec(temp_path, benchmark) → assert no exceptions`. Refuses to emit invalid manifests.
- `write_manifest(manifest: dict, out_path: Path, force: bool) -> None` — errors if file exists and `not force`.

Agent query template baked in:
```
Read `TASK.md` in the working directory for the full specification.
Your goal is to reimplement the functions marked with `TODO(agent):` in the files listed in TASK.md.
You may run tests locally with: {test_cmd}
Only the following paths will be graded: {submit_paths}
```

### 7. `benchmark_yaml.py`

- `ensure_base(bench_path: Path, key: str, official_image: str, extra_packages: list[str], user_directive: str | None, post_install_directive: str | None) -> Literal["added","exists","conflict"]`
- If key exists and spec is identical → returns `"exists"`.
- If key exists and spec differs → returns `"conflict"` (CLI aborts with clear message).
- If key absent → append to `base_images` map preserving surrounding YAML formatting via `ruamel.yaml` OR (if unavailable) via `yaml.safe_load` + `yaml.safe_dump` with `sort_keys=False`. Prefer `ruamel.yaml` for round-trip fidelity; if the project doesn't want another dep, use `yaml` and warn on comment loss. Decision: **use pyyaml (already needed elsewhere)** — accept comment-loss risk since BENCHMARK.yaml has minimal comments. Document in code.
- v1 does not auto-add bases; if `--base` is not present in the YAML, abort with a message telling the author to add it first (safer default — this only bites first-time author for a new language, and my goawk work already added `go`).

### 8. `calibrate.py`

Sequence:
1. Validate manifest via `make_task_spec` on the freshly-written file.
2. Build all three images via `sforge.harness.docker_build.build_all_images(task_spec, config, docker_client, force_rebuild=False, force_rebuild_base=False, verbose=True)`.
3. Package the **gutted** `interp/functions.go` from the freshly-gutted source (already available in memory from the workspace step) as a tar.gz archive with the same layout as `submit_paths`.
4. Call `judge_submission(task_spec, gutted_archive, config, backend, submission_id="calib-gutted", timeout=cfg.eval_timeout, log_dir=<per-run>, verbose=True)`. Assert `report.score_0_100 <= cfg.gutted_max`.
5. Package the **golden** original source (also in memory from the workspace step, saved before gutting) as tar.gz. Call `judge_submission(..., submission_id="calib-golden", ...)`. Assert `report.score_0_100 >= cfg.golden_min`.
6. If either fails, print the log paths from the report and exit with code 4.

Backend: use `create_backend_from_config(config)` with the default Docker backend. Print a clear "calibration requires Docker" error if backend init fails.

Archive helper: `pack_submission(files: dict[str, str], submit_paths: list[str]) -> bytes` — builds a tar.gz where keys are paths relative to `cwd`. Uses `tarfile` in-memory (`io.BytesIO`).

### 9. `tier.py`

```python
def classify_tier(loc_gutted: int, tests_covered: int) -> Literal["toy","standard","extreme"]:
    if loc_gutted < 200 and tests_covered < 100: return "toy"
    if loc_gutted < 2000 and tests_covered < 500: return "standard"
    return "extreme"
```

Enforcement:
- `tier=auto` → classify and print (informational only)
- `tier=<explicit>` → classify; if mismatch, exit code 5 with an explanatory message. Reports show `expected/observed` metrics.

**Tests covered** in v1: count of subtest lines in judge test output that match `--test-filter`. Requires running the golden calibration once. If `--no-calibrate` is set, tier gate is skipped with a warning.

### 10. `cli_entry.py`

Two exports:
1. `register(subparsers)` — adds the `author-clone-gut` subparser to sforge's top-level argparse, mirrors existing style (see `p_build` block in cli.py around line 895).
2. `cmd_author_clone_gut(args)` — the handler.

Wiring into `sforge/cli.py`:
- Import at top: `from sforge.author.cli_entry import register as _register_author`
- Right before `args = parser.parse_args()`: `_register_author(subparsers)`
- No changes to other commands.

Handler flow (all errors surface with `print("Error: ...", file=sys.stderr); sys.exit(<code>)`):

```
1. Parse args -> AuthorConfig
2. Load BENCHMARK.yaml, verify --base key exists
3. temp_workspace() context:
   a. clone repo, checkout commit
   b. get_commit_date; check_contamination
   c. for each gut_target: read file; get_gutter(lang); parse+gut; save gutted+original bytes
   d. render setup_workspace.sh (embedding TASK.md + gut script + gutted files)
   e. render setup_judge.sh (embedding score.sh)
   f. build_manifest
   g. dry-run: print manifest path + calibration plan, exit 0
   h. write manifest to out_dir/<task_id>.json
4. if --no-calibrate: print "manifest written; skipped calibration"; exit 0
5. calibrate:
   - build images
   - run gutted judge
   - run golden judge
   - assert score bounds
6. tier gate
7. print summary + exit 0
```

## Templates & script content — key invariants

`SCORE_SH_TEMPLATE` (renders as `/tmp/score.sh` in judge image) must:
- Run `set -uxo pipefail` (not `-e` — we want the emit-zero fallback to run even if go build fails).
- `cd {cwd}` first.
- On `go build ./...` failure: emit the JSON `{"score": 0, ...}` between markers, exit 0.
- Wrap the test invocation with `stdbuf -oL` if available (nice-to-have; skip if it complicates portability).
- Use inline `python3 <<'PYEOF'` block for parsing so the whole judge stays in one file.
- Handle three-argument test name filter (substring OR /regex/).

`SETUP_WORKSPACE_SH_TEMPLATE` must:
- Clone into a scratch dir, `cp -a`, then `rm -rf .git && git init && git add -A && git commit`.
- Delete `.github/` (avoid confusing agent with CI config) — configurable via `--keep-dot-github`.
- Write TASK.md at repo root (not `cwd/TASK.md` if different — clarify in code that `cwd` == repo root in v1).

## Sequencing and gates

1. Config parse + BENCHMARK check (fast)
2. Clone + commit-date check (network; ~10s)
3. Contamination gate (blocks here on failure)
4. Gut (fast, in-memory)
5. Manifest write + reload validation (fast)
6. `--dry-run`? print + exit
7. Docker build (SLOW: 3-15 min on M-series via emulation for `golang:1.22`)
8. Calibration gutted (30-120 s judge run)
9. Calibration golden (30-120 s judge run)
10. Tier gate (uses golden run output)
11. Success summary

Rollback: if any step after manifest-write fails, do **not** delete the manifest by default (author may want to inspect). If `--force` is set and calibration fails, mark manifest with a `_calibration_status` sidecar file at `<task_id>.calibration.json` recording pass/fail scores; do not embed in the manifest itself (sforge would reject unknown fields).

## Verification (end-to-end)

Success criterion for v1: **`sforge author-clone-gut` regenerates the working `goawk_printf_reimplementation` task in a single invocation**.

Test command (goes into `tests/author/test_e2e_goawk.py` and is also the human smoke test):

```bash
.venv/bin/python -m sforge author-clone-gut \
  --task-id goawk_printf_reimplementation_v2 \
  --name "GoAWK printf/sprintf reimplementation (regenerated)" \
  --category code_reconstruction \
  --repo https://github.com/benhoyt/goawk \
  --commit 4c907fb2838a4f819252cc3030e898eebf8a1c10 \
  --base go \
  --lang go \
  --gut interp/functions.go:parseFmtTypes,sprintf \
  --cwd /home/workspace/goawk \
  --test-cmd "go test -count=1 -timeout=300s -v -run '^(TestInterp|TestCharsMode)\$' ./interp/ -awk=" \
  --test-filter printf|sprintf \
  --eval-timeout 600 \
  --gutted-max 5 \
  --golden-min 95
```

Expected output:
- Contamination check: FAIL (commit is 2023-04-01, well before 2025-04-01 cutoff). Test invocation must include `--allow-precutoff` to proceed. This is a **feature demo**: goawk_printf is admittedly contaminated; documenting this in the smoke test proves the gate works.
- Manifest written at `tasks/goawk_printf_reimplementation_v2.json`.
- Docker calibration: gutted `1.82 ≤ 5`, golden `100 ≥ 95`. Pass.
- Tier: `toy` (correct — 2 funcs, ~110 LOC, 55 tests).

Compare emitted manifest byte-for-byte to the one authored manually (allowing whitespace-only differences). Any semantic difference is a bug.

## Implementation waves (for delegation)

**Wave A — foundation** (blocks nothing, no docker required):
- `errors.py`, `config.py`, `commit_info.py`, `workspace.py`, `benchmark_yaml.py`, `tier.py`, `gutters/base.py`, dispatcher.
- Unit tests for each.

**Wave B — Go gutter** (depends on A):
- `gutters/go.py` (full impl)
- `gutters/{rust,python,typescript}.py` (stub only)
- `tests/author/test_gutter_go.py` with fixtures from a checked-in mini Go file.

**Wave C — templates + manifest** (depends on A):
- `templates.py` (all four templates)
- `manifest.py` (build + round-trip validate)
- Snapshot tests against expected output on the goawk case.

**Wave D — CLI + calibration** (depends on A/B/C):
- `cli_entry.py` (argparse + handler)
- `calibrate.py` (docker build + judge_submission)
- Wire into `sforge/cli.py`.

**Wave E — verification**:
- Run `test_e2e_goawk.py` end to end.
- Compare to manual manifest.

## Risks & mitigations

| Risk | Mitigation |
|---|---|
| tree-sitter Go grammar mismatch with `golang:1.22` syntax | pin `tree_sitter_go>=0.25.0`; add `test_gutter_go.py` fixture that exercises method receivers, generics, and multi-line signatures |
| Import injection breaks source | v1 only supports repos where required imports are already present. Detect + error early |
| BENCHMARK.yaml round-trip loses comments | pyyaml → warn; suggest `ruamel.yaml` upgrade path |
| Calibration is slow (docker emulation on Mac) | make `--no-calibrate` easy; document a fast-loop workflow (author manifest offline, calibrate on Linux CI) |
| Contamination cutoff drifts with new models | `--model-cutoff` flag; default documented as "Claude 4.7 family, adjust for other targets" |
| Score parser doesn't handle non-Go test output | v1 explicitly single-language (Go). v2 must add per-lang score.sh templates. Document the coupling |
| Author accidentally overwrites existing task | `--force` required if `tasks/<id>.json` exists |
| Judge container needs network for `go mod download` | goawk has zero deps → works offline. For other repos: gate `--internet` flag on this; document that internet-off calibration will fail if the repo needs deps |

## Deliverables checklist

- [ ] `sforge/author/` package with all modules above
- [ ] `sforge/cli.py` registers `author-clone-gut` subcommand
- [ ] `tests/author/` with unit + e2e tests
- [ ] `pyproject.toml` (or wherever deps live) adds `tree_sitter` + `tree_sitter_go`
- [ ] End-to-end: regenerates `goawk_printf_reimplementation` with matching semantics
- [ ] `README.md` snippet or `docs/author-clone-gut.md` documenting the CLI (single page, no marketing)
