#!/bin/bash
# Install the code-sync launchd job from the repo template, identically on any
# machine (replaces whatever hand-made plist was there; keeps a timestamped backup).
# Usage: bash ~/.agents/lib/launchd/install_code_sync.sh
set -euo pipefail
LABEL=com.marvin.code-sync-push
SRC="$HOME/.agents/lib/launchd/$LABEL.plist"
DEST="$HOME/Library/LaunchAgents/$LABEL.plist"
UID_NUM=$(id -u)

mkdir -p "$HOME/.claude/logs" "$HOME/Library/LaunchAgents"
[ -f "$DEST" ] && cp "$DEST" "$DEST.bak-$(date +%Y%m%d%H%M%S)"
sed "s#__HOME__#$HOME#g" "$SRC" > "$DEST.new"
plutil -lint "$DEST.new" >/dev/null
mv "$DEST.new" "$DEST"
launchctl bootout "gui/$UID_NUM/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$UID_NUM" "$DEST"
launchctl print "gui/$UID_NUM/$LABEL" | grep -E "run interval|state =" | head -2
echo "installed $LABEL from repo template"
