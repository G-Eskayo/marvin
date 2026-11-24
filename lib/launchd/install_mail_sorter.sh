#!/bin/bash
# Install MARVIN's mail sorter for one account (part of #1357), from the repo template. Run on ONE machine only (the
# Mini): two sorters would both alert. Needs instance/config/mail/<account>.json + rules.json, and the app password in
# Keychain (in your own terminal, because it prompts; over SSH, unlock first):
#   security unlock-keychain ~/Library/Keychains/login.keychain-db && \
#   security add-generic-password -s marvin-mail-<account> -a <address> -w
# Checks the config and a live sign-in (`run --once`) before loading, so a bad setup fails here, not silently.
# Usage: bash ~/.agents/lib/launchd/install_mail_sorter.sh [gmail|icloud|...]      Remove: ... <account> --remove
set -euo pipefail
ACCOUNT="${1:-gmail}"
[[ "$ACCOUNT" =~ ^[a-z0-9-]+$ ]] || { echo "bad account name: $ACCOUNT" >&2; exit 2; }
LABEL="com.marvin.mail-sorter.$ACCOUNT"
SRC="$HOME/.agents/lib/launchd/com.marvin.mail-sorter.ACCOUNT.plist"
DEST="$HOME/Library/LaunchAgents/$LABEL.plist"
UID_NUM=$(id -u)
PY="$HOME/.agents/venv/bin/python"

# The slice-1 job was a single label for Gmail; it's now com.marvin.mail-sorter.gmail.
LEGACY="$HOME/Library/LaunchAgents/com.marvin.mail-sorter.plist"
if [ "$ACCOUNT" = gmail ] && [ -f "$LEGACY" ]; then
  launchctl bootout "gui/$UID_NUM/com.marvin.mail-sorter" 2>/dev/null || true
  mv "$LEGACY" "$LEGACY.bak-$(date +%Y%m%d%H%M%S)"
  echo "retired legacy com.marvin.mail-sorter"
fi

if [ "${2:-}" = "--remove" ]; then
  launchctl bootout "gui/$UID_NUM/$LABEL" 2>/dev/null || true
  rm -f "$DEST"
  echo "removed $LABEL"
  exit 0
fi

mkdir -p "$HOME/.claude/logs" "$HOME/Library/LaunchAgents"
"$PY" "$HOME/.agents/lib/mail_sorter.py" run --once --account "$ACCOUNT"
[ -f "$DEST" ] && cp "$DEST" "$DEST.bak-$(date +%Y%m%d%H%M%S)"
sed -e "s#__HOME__#$HOME#g" -e "s#__ACCOUNT__#$ACCOUNT#g" "$SRC" > "$DEST.new"
plutil -lint "$DEST.new" >/dev/null
mv "$DEST.new" "$DEST"
launchctl bootout "gui/$UID_NUM/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$UID_NUM" "$DEST"
launchctl print "gui/$UID_NUM/$LABEL" | grep -E "state =" | head -1
echo "installed $LABEL"
