#!/bin/bash
# Start the live brain-map wallpaper on mac-mini-2012 (ADR 0069). One copy per session (the app enforces it too).
cd "$HOME/.agents" || exit 1
exec dashboard/node_modules/.bin/electron brain-map/desktop-live-linux/main.js >> "$HOME/.claude/logs/desktoplive-linux.out" 2>&1
