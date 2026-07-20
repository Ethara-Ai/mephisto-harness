#!/usr/bin/env bash
#
# export_my_claude_cred.sh — a colleague runs this on THEIR Mac to export their
# own Claude Code subscription credential to a single file they can send back.
# Tries the macOS Keychain first, then ~/.claude/.credentials.json. Validates
# the shape and prints only redacted prefixes (never the full token to screen).
#
# Usage on the colleague's Mac:
#   ./export_my_claude_cred.sh            # writes ./claude-cred-<user>.json
#   ./export_my_claude_cred.sh alice      # writes ./claude-cred-alice.json
#
# They then send you the resulting file over a SECURE channel (not email/Slack
# plaintext) and you drop it in ~/.mephisto-secrets/accountN.json on your box.

set -euo pipefail

label="${1:-$(whoami)}"
out="./claude-cred-${label}.json"

echo "Exporting Claude Code credential for: $label"

raw=""
if command -v security >/dev/null 2>&1 \
   && security find-generic-password -s "Claude Code-credentials" -w >/dev/null 2>&1; then
  raw="$(security find-generic-password -s "Claude Code-credentials" -w 2>/dev/null)"
  src="macOS Keychain"
elif [ -f "$HOME/.claude/.credentials.json" ]; then
  raw="$(cat "$HOME/.claude/.credentials.json")"
  src="~/.claude/.credentials.json"
else
  echo "ERROR: no Claude Code credential found." >&2
  echo "  Are you logged in?  Run:  claude login   then retry." >&2
  exit 1
fi

printf '%s' "$raw" | python3 -c "
import sys, json
raw = sys.stdin.read()
d = json.loads(raw)
o = d.get('claudeAiOauth') or d
missing = [k for k in ('accessToken','refreshToken','expiresAt') if not o.get(k)]
if missing:
    print('  INVALID: missing field(s): ' + ', '.join(missing)); sys.exit(1)
json.dump({'claudeAiOauth': {
    'accessToken':      o['accessToken'],
    'refreshToken':     o['refreshToken'],
    'expiresAt':        int(o['expiresAt']),
    'scopes':           o.get('scopes') or [],
    'subscriptionType': o.get('subscriptionType'),
}}, open('$out','w'))
print('  source      :', '$src')
print('  accessToken :', o['accessToken'][:14] + '...')
print('  refreshToken:', o['refreshToken'][:14] + '...')
print('  expiresAt   :', o['expiresAt'])
print('  subscription:', o.get('subscriptionType'))
"

chmod 600 "$out"
echo "  wrote       : $out  (chmod 600)"
echo ""
echo "Send $out to the run owner over a secure channel."
echo "They will place it as ~/.mephisto-secrets/accountN.json on the run machine."
