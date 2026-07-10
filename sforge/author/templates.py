from __future__ import annotations


TASK_MD_TEMPLATE = """# Task: {name}

**Task ID:** `{task_id}`
**Category:** {category}
**Language:** {lang}
**Source:** {repo} @ `{commit}`

## What to do

Reimplement the functions that have been gutted (replaced with stub bodies that
return zero values and a `not implemented` error so the code compiles but tests
fail).

## Where the stubs are

The following files contain gutted functions:

{gut_files}

## How to test locally

From `{cwd}` inside the container, run:

```
{test_cmd}
```

## Grading formula

The judge counts subtests whose names match the regex `{test_filter}`:

```
score = passed / total * 100
```

## Constraints

- Only edit the files listed above.
- Do not add new imports beyond the {lang} standard library.
- Do not modify test files.
- Only the files listed above are collected at submission time; changes elsewhere are discarded.

{extra_notes}
"""


SETUP_WORKSPACE_SH_TEMPLATE = r"""mkdir -p {cwd}
git clone {repo} /tmp/src
git -C /tmp/src checkout {commit}
cp -a /tmp/src/. {cwd}
rm -rf /tmp/src
{prepared_files_bash}
cat > {cwd}/TASK.md <<'TASKMD_EOF'
{task_md}
TASKMD_EOF
cd {cwd}
rm -rf .git
git init -q
git config user.email 'sforge@local'
git config user.name 'sforge'
git add -A
git commit -q -m 'initial workspace (functions gutted)'
"""


SETUP_JUDGE_SH_TEMPLATE = r"""mkdir -p {cwd}
git clone {repo} /tmp/src
git -C /tmp/src checkout {commit}
cp -a /tmp/src/. {cwd}
rm -rf /tmp/src
{cache_warm_cmd}
cat > /tmp/score.sh <<'SCORE_EOF'
{score_sh}
SCORE_EOF
chmod +x /tmp/score.sh
"""


SCORE_SH_TEMPLATE = r"""#!/bin/bash
set -uo pipefail
cd {cwd}
emit_zero() {{
  cat <<'EOF'
>>>>> Start Structured Result
{{"score": 0, "raw_passed": 0, "raw_total": 0, "raw_failed": 0, "raw_skipped": 0, "pass_rate": 0.0, "summary": "build failed", "details": []}}
>>>>> End Structured Result
EOF
  exit 0
}}
if ! {build_cmd} > /tmp/build.log 2>&1; then
  emit_zero
fi
{test_cmd} > /tmp/test.out 2>&1 || true
python3 <<'PYEOF'
import json, re
go_pat = re.compile(r'^\s*--- (PASS|FAIL|SKIP):\s+(\S+)\s+\(')
py_pat = re.compile(r'^(\S+)\s+(PASSED|FAILED|SKIPPED|ERROR)(?:\s|$)')
py_status = {{'PASSED': 'PASS', 'FAILED': 'FAIL', 'SKIPPED': 'SKIP', 'ERROR': 'FAIL'}}
filt = re.compile({test_filter_pyrepr})
passed = failed = skipped = 0
details = []
with open('/tmp/test.out') as f:
    for line in f:
        m = go_pat.match(line)
        if m:
            status, name = m.group(1), m.group(2)
        else:
            m = py_pat.match(line)
            if not m:
                continue
            name = m.group(1)
            status = py_status[m.group(2)]
        if not filt.search(name):
            continue
        if status == 'PASS':
            passed += 1
            details.append({{"name": name, "status": "PASS"}})
        elif status == 'FAIL':
            failed += 1
            details.append({{"name": name, "status": "FAIL"}})
        else:
            skipped += 1
            details.append({{"name": name, "status": "SKIP"}})
total = passed + failed + skipped
score = round(passed * 100 / total, 2) if total else 0.0
rate = round(passed / total, 4) if total else 0.0
print('>>>>> Start Structured Result')
print(json.dumps({{"score": score, "raw_passed": passed, "raw_total": total, "raw_failed": failed, "raw_skipped": skipped, "pass_rate": rate, "summary": f"{{passed}}/{{total}} passed", "details": details}}))
print('>>>>> End Structured Result')
PYEOF
"""


def render(template: str, **kwargs: str) -> str:
    return template.format(**kwargs)
