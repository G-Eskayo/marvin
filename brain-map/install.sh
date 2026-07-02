#!/usr/bin/env bash
# Build DesktopLive and install it as a launchd agent — the MARVIN brain map
# rendered as live desktop wallpaper (RunAtLoad + KeepAlive, survives logout).
set -euo pipefail

BRAIN_MAP_DIR="$HOME/.agents/brain-map"
PLIST_SRC="$BRAIN_MAP_DIR/launchd/com.marvin.desktoplive.plist"
PLIST_DEST="$HOME/Library/LaunchAgents/com.marvin.desktoplive.plist"
LOG_DIR="$HOME/.claude/logs"

mkdir -p "$LOG_DIR"

echo "→ Generating the graph from the live manifest..."
~/.agents/venv/bin/python "$BRAIN_MAP_DIR/generate.py"

echo "→ Compiling DesktopLive..."
( cd "$BRAIN_MAP_DIR/DesktopLive" && swiftc -O main.swift -o DesktopLive )

# Unload first if already installed (allows re-install)
if launchctl list | grep -q "com.marvin.desktoplive"; then
    launchctl bootout "gui/$(id -u)/com.marvin.desktoplive" 2>/dev/null || true
    echo "Unloaded existing agent."
fi

cp "$PLIST_SRC" "$PLIST_DEST"
launchctl bootstrap "gui/$(id -u)" "$PLIST_DEST"

echo "✓ com.marvin.desktoplive installed."
echo "  Runs at every login, restarts on crash. Logs → $LOG_DIR/desktoplive*.log"
echo "  Regenerate the graph after skill changes: ~/.agents/venv/bin/python $BRAIN_MAP_DIR/generate.py"
echo "  (this now also runs automatically via the rebuild-manifest hook — see architecture.md ADR notes)"
echo "  Showcase without touching anything real: ~/.agents/venv/bin/python $BRAIN_MAP_DIR/demo.py"
echo "  To uninstall: launchctl bootout gui/\$(id -u)/com.marvin.desktoplive && rm $PLIST_DEST"
