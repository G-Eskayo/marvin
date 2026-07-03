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
APP_BUNDLE="$BRAIN_MAP_DIR/DesktopLive/DesktopLive.app"
APP_BIN_DIR="$APP_BUNDLE/Contents/MacOS"
mkdir -p "$APP_BIN_DIR"
( cd "$BRAIN_MAP_DIR/DesktopLive" && swiftc -O main.swift -o "$APP_BIN_DIR/DesktopLive" )

# A bare binary (no .app bundle) leaves LSUIElement/accessory status to a
# runtime NSApp.setActivationPolicy() call inside applicationDidFinishLaunching
# — which runs *after* the OS has already registered the process, so there's
# a real window where it can flash into the Dock/menu bar (seen live on two
# machines). Info.plist's LSUIElement is read before the app's own code runs
# at all, closing that gap for good.
cat > "$APP_BUNDLE/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleExecutable</key>
    <string>DesktopLive</string>
    <key>CFBundleIdentifier</key>
    <string>com.marvin.desktoplive</string>
    <key>CFBundleName</key>
    <string>DesktopLive</string>
    <key>CFBundlePackageType</key>
    <string>APPL</string>
    <key>CFBundleShortVersionString</key>
    <string>1.0</string>
    <key>LSUIElement</key>
    <true/>
</dict>
</plist>
PLIST

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
