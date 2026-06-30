#!/usr/bin/env bash
# Install MARVIN daily-digest as a launchd agent (runs at 08:30 daily).
set -euo pipefail

PLIST_SRC="$HOME/.agents/skills/improve/com.marvin.daily-digest.plist"
PLIST_DEST="$HOME/Library/LaunchAgents/com.marvin.daily-digest.plist"
LOG_DIR="$HOME/.claude/logs"

mkdir -p "$LOG_DIR"

# Unload first if already installed (allows re-install)
if launchctl list | grep -q "com.marvin.daily-digest"; then
    launchctl unload "$PLIST_DEST" 2>/dev/null || true
    echo "Unloaded existing agent."
fi

cp "$PLIST_SRC" "$PLIST_DEST"
launchctl load "$PLIST_DEST"

echo "✓ com.marvin.daily-digest installed."
echo "  Runs daily at 08:30. Logs → $LOG_DIR/daily-digest.log"
echo "  To run immediately: ~/.agents/venv/bin/python ~/.agents/skills/improve/scripts/daily_digest.py"
echo "  To uninstall:       launchctl unload $PLIST_DEST && rm $PLIST_DEST"
