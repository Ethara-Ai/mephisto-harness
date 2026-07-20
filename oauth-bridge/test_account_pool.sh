#!/usr/bin/env bash
#
# test_account_pool.sh — validate a multi-account credential pool WITHOUT
# exposing any token. Prints only redacted status (account labels, token
# prefixes, expiry, availability). Run this privately; it never sends the
# tokens anywhere except Anthropic's own refresh endpoint during --check.
#
# Prerequisites:
#   1. Put each account's credential JSON somewhere git-ignored, e.g.
#        ~/.mephisto-secrets/account1.json ... account5.json
#      Each file has the same shape as ~/.claude/.credentials.json:
#        {"claudeAiOauth":{"accessToken":"sk-ant-oat01-...",
#                          "refreshToken":"sk-ant-ort01-...",
#                          "expiresAt":<unix-ms>,"scopes":[...],
#                          "subscriptionType":"max"}}
#      Lock them:  chmod 600 ~/.mephisto-secrets/*.json
#
#   2. Point the pool at them (colon-separated absolute paths):
#        export WCB_CC_ACCOUNT_POOL="$HOME/.mephisto-secrets/account1.json:...:account5.json"
#
# Usage:
#   export WCB_CC_ACCOUNT_POOL="/abs/a1.json:/abs/a2.json:/abs/a3.json:/abs/a4.json:/abs/a5.json"
#   ./test_account_pool.sh

set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

if [ -z "${WCB_CC_ACCOUNT_POOL:-}" ]; then
  echo "ERROR: WCB_CC_ACCOUNT_POOL is not set." >&2
  echo "  export WCB_CC_ACCOUNT_POOL=\"/abs/a1.json:/abs/a2.json:...\"" >&2
  exit 1
fi

echo "== Step 1: each pool file exists, is private (0600), and is valid JSON =="
IFS=':' read -r -a _paths <<< "$WCB_CC_ACCOUNT_POOL"
n=0
for p in "${_paths[@]}"; do
  [ -z "$p" ] && continue
  n=$((n + 1))
  if [ ! -f "$p" ]; then
    echo "  [$n] MISSING: $p"; continue
  fi
  perm=$(stat -f "%A" "$p" 2>/dev/null || stat -c "%a" "$p" 2>/dev/null)
  ok_json=$(python3 -c "import json,sys;d=json.load(open(sys.argv[1]));print('yes' if d.get('claudeAiOauth',{}).get('accessToken') else 'no')" "$p" 2>/dev/null || echo "no")
  prefix=$(python3 -c "import json,sys;print(json.load(open(sys.argv[1]))['claudeAiOauth']['accessToken'][:14])" "$p" 2>/dev/null || echo "??")
  echo "  [$n] perm=$perm  valid=$ok_json  token=${prefix}...  $(basename "$p")"
done
echo "  pool size: $n account(s)"

echo ""
echo "== Step 2: pool parses via load_account_pool (no tokens printed) =="
PYTHONPATH=. python3 - <<'PY'
import os
from claude_oauth.credentials import load_account_pool
pool = load_account_pool(os.environ["WCB_CC_ACCOUNT_POOL"])
if pool is None:
    raise SystemExit("  FAIL: pool spec yielded no slots")
snap = pool.snapshot()
print(f"  parsed {len(snap)} slot(s):")
for s in snap:
    print(f"    - label={s['label']}  token={s.get('token_prefix')}  "
          f"available={s['available']}  invalid={s['invalid']}")
PY

echo ""
echo "== Step 3: each account authenticates (refresh check, tokens stay hidden) =="
fail=0
idx=0
for p in "${_paths[@]}"; do
  [ -z "$p" ] && continue
  idx=$((idx + 1))
  if WCB_CC_CREDS_PATH="$p" PYTHONPATH=. python3 -m claude_oauth --check >/tmp/_poolchk 2>&1; then
    echo "  [$idx] OK    $(basename "$p")"
  else
    echo "  [$idx] FAILED $(basename "$p") -> $(tail -1 /tmp/_poolchk)"
    fail=$((fail + 1))
  fi
done
rm -f /tmp/_poolchk

echo ""
if [ "$fail" -eq 0 ]; then
  echo "RESULT: all $n account(s) valid + authenticated. Pool is ready."
else
  echo "RESULT: $fail account(s) failed. Fix those before a 12h run." >&2
  exit 1
fi
