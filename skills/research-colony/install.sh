#!/usr/bin/env bash
# Install MARVIN research colony as a launchd agent (runs daily at 09:00).
set -euo pipefail

PLIST_SRC="$HOME/.agents/skills/research-colony/com.marvin.research-colony.plist"
PLIST_DEST="$HOME/Library/LaunchAgents/com.marvin.research-colony.plist"
LOG_DIR="$HOME/.claude/logs"

mkdir -p "$LOG_DIR"
mkdir -p "$HOME/.claude/research-digest"
mkdir -p "$HOME/.claude/research-feed"

# Unload first if already installed (allows re-install)
if launchctl list | grep -q "com.marvin.research-colony"; then
    launchctl unload "$PLIST_DEST" 2>/dev/null || true
    echo "Unloaded existing agent."
fi

cp "$PLIST_SRC" "$PLIST_DEST"
launchctl load "$PLIST_DEST"

echo "✓ com.marvin.research-colony installed."
echo "  Runs daily at 09:00. Logs → $LOG_DIR/research-colony.log"
echo "  To run immediately: ~/.agents/venv/bin/python ~/.agents/skills/research-colony/scripts/run_colony.py"
echo "  To uninstall:       launchctl unload $PLIST_DEST && rm $PLIST_DEST"
