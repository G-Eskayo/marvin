#!/usr/bin/env bash
# Build the two benchmark profiles fresh. Credentials are materialized from the
# macOS keychain at run time and never committed (see ../.gitignore).
#
#   ./setup.sh              -> rebuild both profiles
#
# clean  = base Claude Code: auth + account marker only. No CLAUDE.md, skills,
#          hooks, or memory. This is the control.
# marvin = a symlinked view of the live ~/.claude + ~/.agents setup (the
#          treatment). We don't copy it so it always reflects current state.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
KEYCHAIN_SERVICE="Claude Code-credentials"

# --- credential (shared, read once) ---
CRED="$(security find-generic-password -s "$KEYCHAIN_SERVICE" -w 2>/dev/null || true)"
if [ -z "$CRED" ]; then
  echo "ERROR: could not read keychain item '$KEYCHAIN_SERVICE'." >&2
  echo "Run 'claude' once interactively to log in, then retry." >&2
  exit 1
fi

# --- purge poisoned path-specific keychain entries ---
# Claude Code 2.x stores per-config-dir credentials at
# "Claude Code-credentials-<sha256[:8] of abs path>". A failed auth attempt
# writes a BLANK entry that permanently blocks future .credentials.json reads
# for that path. Delete any blank entries for our bench profile paths before
# materializing credentials so setup.sh is idempotent.
purge_blank_entry() {
  local abs_path="$1"
  local suffix
  suffix=$(python3 -c "import hashlib,sys; print(hashlib.sha256(sys.argv[1].encode()).hexdigest()[:8])" "$abs_path")
  local svc="Claude Code-credentials-${suffix}"
  local content
  content=$(security find-generic-password -s "$svc" -w 2>/dev/null || true)
  if [ -n "$content" ]; then
    local access_token
    access_token=$(python3 -c "import json,sys; d=json.loads(sys.argv[1]); print(d.get('claudeAiOauth',{}).get('accessToken',''))" "$content" 2>/dev/null || true)
    if [ -z "$access_token" ]; then
      security delete-generic-password -s "$svc" 2>/dev/null && echo "purged blank keychain entry: $svc" || true
    fi
  fi
}
purge_blank_entry "$HERE/clean"
purge_blank_entry "$HERE/marvin"
purge_blank_entry "$HERE/lean"

# --- clean profile ---
CLEAN="$HERE/clean"
rm -rf "$CLEAN"; mkdir -p "$CLEAN"
cat > "$CLEAN/settings.json" <<'JSON'
{
  "permissions": {
    "allow": [
      "Bash(~/.agents/venv/bin/python ~/.agents/skills/qa-agent/scripts/qa_query.py:*)",
      "Bash(/Users/gileskayo/.agents/venv/bin/python /Users/gileskayo/.agents/skills/qa-agent/scripts/qa_query.py:*)"
    ]
  }
}
JSON
printf '%s' "$CRED" > "$CLEAN/.credentials.json"; chmod 600 "$CLEAN/.credentials.json"
# minimal account marker: strip everything except identity/onboarding
python3 - "$HOME/.claude.json" "$CLEAN/.claude.json" <<'PY'
import json, os, sys
src, dst = sys.argv[1], sys.argv[2]
d = json.load(open(src)) if os.path.exists(src) else {}
keep = {k: d[k] for k in ("userID","oauthAccount","hasCompletedOnboarding",
        "numStartups","installMethod","firstStartTime","customApiKeyResponses") if k in d}
keep["projects"] = {}
json.dump(keep, open(dst, "w"))
PY
echo "built clean profile -> $CLEAN"

# --- marvin profile ---
# A symlink overlay of the live ~/.claude (so it always reflects current state),
# plus a materialized credential. We never write a token into the real ~/.claude.
# Claude Code reads .credentials.json from CLAUDE_CONFIG_DIR when it is set
# explicitly (the keychain path is only used for the default dir).
MARVIN="$HERE/marvin"
rm -rf "$MARVIN"; mkdir -p "$MARVIN"
shopt -s dotglob
for item in "$HOME/.claude"/*; do
  base="$(basename "$item")"
  # don't symlink a stale credential or account marker; we provide our own
  [ "$base" = ".credentials.json" ] && continue
  [ "$base" = ".claude.json" ] && continue
  ln -s "$item" "$MARVIN/$base"
done
shopt -u dotglob
printf '%s' "$CRED" > "$MARVIN/.credentials.json"; chmod 600 "$MARVIN/.credentials.json"
# faithful account marker: copy the live home-level .claude.json verbatim
[ -f "$HOME/.claude.json" ] && cp "$HOME/.claude.json" "$MARVIN/.claude.json"
echo "built marvin profile-> $MARVIN (symlinks to live ~/.claude + credential)"

# --- lean profile ---
# Symlink overlay of ~/.claude-lean (13-line CLAUDE.md, no memory hooks).
# Same account identity as marvin; just a lighter config dir.
LEAN="$HERE/lean"
rm -rf "$LEAN"; mkdir -p "$LEAN"
shopt -s dotglob
for item in "$HOME/.claude-lean"/*; do
  base="$(basename "$item")"
  [ "$base" = ".credentials.json" ] && continue
  [ "$base" = ".claude.json" ] && continue
  ln -s "$item" "$LEAN/$base"
done
shopt -u dotglob
printf '%s' "$CRED" > "$LEAN/.credentials.json"; chmod 600 "$LEAN/.credentials.json"
[ -f "$HOME/.claude.json" ] && cp "$HOME/.claude.json" "$LEAN/.claude.json"
echo "built lean profile  -> $LEAN (symlinks to live ~/.claude-lean + credential)"
echo "done."
