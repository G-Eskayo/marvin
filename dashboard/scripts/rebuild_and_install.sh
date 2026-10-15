#!/bin/bash
# Rebuilds the MARVIN dashboard app and installs it over the running
# copy in /Applications, so a merged PR actually shows up in the app people
# use day-to-day instead of only existing in dist/. Triggered by
# webhook-server/merge.js after a merge that touched dashboard/ files, and by
# lib/dashboard_rebuild.py when the app is behind origin/main (#443: any merge
# path, within minutes); safe to run by hand too.
set -euo pipefail
# marvin#422: a failed rebuild is recorded in the one error log Health shows (it used to look "passed" once launched).
on_error() {
  local code=$? line=$1
  "$HOME/.agents/venv/bin/python" "$HOME/.agents/lib/error_log.py" record --source rebuild \
    --message "dashboard rebuild failed (exit $code at line $line)" \
    --raw "$(tail -n 20 "$HOME/.claude/logs/dashboard-rebuild.log" 2>/dev/null)" >/dev/null 2>&1 || true
  # #443: dashboard_rebuild.py backs off only after a failure, until newer code lands; a success clears this mark.
  date +%s > "$HOME/.claude/logs/dashboard-rebuild-failed" 2>/dev/null || true
}
trap 'on_error $LINENO' ERR
cd "$(dirname "$0")/.."

APP_NAME="MARVIN.app"
# #442: the app was "MARVIN Metrics.app" until 2026-10-14; an install replaces it, so a machine never has both.
LEGACY_DEST="/Applications/MARVIN Metrics.app"
SRC="dist/mac-arm64/${APP_NAME}"
DEST="/Applications/${APP_NAME}"
LOG_PREFIX="[rebuild-and-install]"

# Build what was just merged, not whatever this checkout had: the merge happens on GitHub and code-sync pulls it a little
# later, so a rebuild started right after a merge raced the pull and reinstalled the old app (2026-10-08, PR #317).
echo "${LOG_PREFIX} pulling the merged code..."
"$HOME/.agents/venv/bin/python" "$HOME/.agents/lib/code_sync.py" pull "$HOME/.agents" || echo "${LOG_PREFIX} pull failed; building what is here" >&2

# Install first: a rebuild must not assume node_modules is current. The laptop's
# build failed on a missing dependency (react-markdown) added on another machine.
echo "${LOG_PREFIX} installing dependencies..."
npm install --no-audit --no-fund

echo "${LOG_PREFIX} building..."
if ! npm run build:mac; then
  # Signing needs the login keychain, which is locked in an SSH session or just after a reboot (errSecInternalComponent).
  # A stale app is worse than an ad-hoc-signed one, so build again without the identity and sign ad hoc.
  echo "${LOG_PREFIX} signed build failed; retrying with an ad-hoc signature" >&2
  rm -rf "dist/mac-arm64"
  npx electron-builder --mac --dir -c.mac.identity=-
  codesign --force --deep -s - "$SRC"
fi

# A build with no signing identity (the mac-mini has none) is "skipped", not failed -- and it leaves Electron's own signature
# invalid for the repacked app, which macOS then refuses to open (2026-10-06: the dashboard vanished after a rebuild). A valid
# ad-hoc signature is enough to run it here.
if [ -d "$SRC" ] && ! codesign --verify --deep --strict "$SRC" >/dev/null 2>&1; then
  echo "${LOG_PREFIX} signature invalid after the build; signing ad hoc" >&2
  codesign --force --deep -s - "$SRC"
fi

if [ ! -d "$SRC" ]; then
  echo "${LOG_PREFIX} build did not produce $SRC" >&2
  exit 1
fi

echo "${LOG_PREFIX} quitting running app if open..."
osascript -e 'quit app "MARVIN"' 2>/dev/null || true
osascript -e 'quit app "MARVIN Metrics"' 2>/dev/null || true
sleep 1

echo "${LOG_PREFIX} installing to $DEST..."
rm -rf "$DEST"
cp -R "$SRC" "$DEST"
if [ -d "$LEGACY_DEST" ]; then
  echo "${LOG_PREFIX} removing the old MARVIN Metrics.app (renamed to MARVIN.app)..."
  rm -rf "$LEGACY_DEST"
fi

echo "${LOG_PREFIX} relaunching..."
open -a "$DEST"
sleep 6
if ! pgrep -f "$DEST/Contents/MacOS" >/dev/null; then
  echo "${LOG_PREFIX} the app did not start after the install" >&2
  exit 1
fi

# The merge server is a long-running node process: it keeps the code it started with until restarted (it ran Oct 5 code
# on Oct 8, so a merged fix to the merge flow didn't apply). This script runs detached, so restarting it is safe.
if launchctl print "gui/$(id -u)/com.marvin.dashboard-webhook" >/dev/null 2>&1; then
  echo "${LOG_PREFIX} restarting the merge server on the new code..."
  launchctl kickstart -k "gui/$(id -u)/com.marvin.dashboard-webhook" || echo "${LOG_PREFIX} merge server restart failed" >&2
fi

rm -f "$HOME/.claude/logs/dashboard-rebuild-failed"  # a good install clears any earlier failure (#443)
echo "${LOG_PREFIX} done."
