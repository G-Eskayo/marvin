#!/usr/bin/env bash
# Install MARVIN morning-brief as a launchd agent on both Mac Mini and MacBook.
# Mini runs primary at 09:45; MacBook runs fallback at 10:45 (ADR 0067).
set -euo pipefail

PLIST_SRC="$HOME/.agents/config/launchd/com.marvin.morning-brief.plist"
PLIST_DEST="$HOME/Library/LaunchAgents/com.marvin.morning-brief.plist"
LOG_DIR="$HOME/.claude/logs"

mkdir -p "$LOG_DIR"

# Unload first if already installed (allows re-install)
if launchctl list | grep -q "com.marvin.morning-brief"; then
    launchctl unload "$PLIST_DEST" 2>/dev/null || true
    echo "Unloaded existing agent."
fi

cp "$PLIST_SRC" "$PLIST_DEST"
launchctl load "$PLIST_DEST"

echo "✓ com.marvin.morning-brief installed."
echo "  Primary (Mini):   runs daily at 09:45"
echo "  Fallback (MacBook): runs daily at 10:45"
echo "  Logs → $LOG_DIR/morning-brief.log"
echo "  To run immediately: ~/.agents/venv/bin/python ~/.agents/lib/morning_brief.py build"
echo "  To uninstall:       launchctl unload $PLIST_DEST && rm $PLIST_DEST"
