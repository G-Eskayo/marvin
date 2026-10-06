#!/bin/bash
# Install the mobile-backend launchd service from the repo template.
# Usage: bash ~/.agents/dashboard/mobile-backend/install.sh
set -euo pipefail
LABEL=com.marvin.mobile-backend
SRC="$HOME/.agents/dashboard/mobile-backend/$LABEL.plist"
DEST="$HOME/Library/LaunchAgents/$LABEL.plist"
UID_NUM=$(id -u)

mkdir -p "$HOME/.claude/logs" "$HOME/Library/LaunchAgents"
[ -f "$DEST" ] && cp "$DEST" "$DEST.bak-$(date +%Y%m%d%H%M%S)"
sed "s#__HOME__#$HOME#g" "$SRC" > "$DEST.new"
plutil -lint "$DEST.new" >/dev/null
mv "$DEST.new" "$DEST"
launchctl bootout "gui/$UID_NUM/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$UID_NUM" "$DEST"
launchctl print "gui/$UID_NUM/$LABEL" | grep -E "state =|exit code" | head -2
echo "installed $LABEL from repo template"
