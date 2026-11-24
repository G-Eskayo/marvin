#!/bin/bash
# Rebuilds the MARVIN dashboard app and either swaps it into place (if not running)
# or stages it and notifies the running app to restart after the user is idle
# (see dashboard/electron/main/app_update.js for the update flow).
# Triggered by webhook-server/merge.js after a merge that touched dashboard/ files,
# and by lib/dashboard_rebuild.py when the app is behind origin/main; safe to run by hand too.
set -euo pipefail

on_error() {
  local code=$? line=$1
  "$HOME/.agents/venv/bin/python" "$HOME/.agents/lib/error_log.py" record --source rebuild \
    --message "dashboard rebuild failed (exit $code at line $line)" \
    --raw "$(tail -n 20 "$HOME/.claude/logs/dashboard-rebuild.log" 2>/dev/null)" >/dev/null 2>&1 || true
  date +%s > "$HOME/.claude/logs/dashboard-rebuild-failed" 2>/dev/null || true
}
trap 'on_error $LINENO' ERR
cd "$(dirname "$0")/.."

APP_NAME="MARVIN.app"
LEGACY_DEST="/Applications/MARVIN Metrics.app"
SRC="dist/mac-arm64/${APP_NAME}"
DEST="/Applications/${APP_NAME}"
LOG_PREFIX="[rebuild-and-install]"
DEMO_HOLD="$HOME/.claude/logs/dashboard-demo-hold"
STAGED_BUILT="$HOME/.claude/logs/dashboard-staged-built"

# (a) Check demo-hold flag first
if [ -f "$DEMO_HOLD" ]; then
  echo "${LOG_PREFIX} demo hold is active; skipping rebuild"
  exit 0
fi

# (b) Self-heal a leftover ${DEST}.old.* backup if ${DEST} is missing
if [ ! -d "$DEST" ] && ls "${DEST}".old.* >/dev/null 2>&1; then
  echo "${LOG_PREFIX} restoring backup after missing live app..."
  for backup in "${DEST}".old.*; do
    mv "$backup" "$DEST" && break
  done
fi

# (c) Wait for any other running rebuild to finish
echo "${LOG_PREFIX} checking for other running rebuilds..."
"$HOME/.agents/venv/bin/python" "$HOME/.agents/lib/rebuild_wait.py" || true

# Build what was just merged, not whatever this checkout had
echo "${LOG_PREFIX} pulling the merged code..."
"$HOME/.agents/venv/bin/python" "$HOME/.agents/lib/code_sync.py" pull "$HOME/.agents" || echo "${LOG_PREFIX} pull failed; building what is here" >&2

# Install first: a rebuild must not assume node_modules is current
echo "${LOG_PREFIX} installing dependencies..."
npm install --no-audit --no-fund

# (d) Build/sign/verify into dist/ only
echo "${LOG_PREFIX} building..."
if ! npm run build:mac; then
  # Signing needs the login keychain, which is locked in an SSH session or just after a reboot
  # A stale app is worse than an ad-hoc-signed one, so build again without the identity and sign ad hoc
  echo "${LOG_PREFIX} signed build failed; retrying with an ad-hoc signature" >&2
  rm -rf "dist/mac-arm64"
  npx electron-builder --mac --dir -c.mac.identity=-
  codesign --force --deep -s - "$SRC"
fi

# A build with no signing identity (the mac-mini has none) leaves Electron's signature invalid
# A valid ad-hoc signature is enough to run it here
if [ -d "$SRC" ] && ! codesign --verify --deep --strict "$SRC" >/dev/null 2>&1; then
  echo "${LOG_PREFIX} signature invalid after the build; signing ad hoc" >&2
  codesign --force --deep -s - "$SRC"
fi

if [ ! -d "$SRC" ]; then
  echo "${LOG_PREFIX} build did not produce $SRC" >&2
  exit 1
fi

# (e) Stage into ${DEST}.staged
STAGED="${DEST}.staged"
echo "${LOG_PREFIX} staging to $STAGED..."
rm -rf "$STAGED"
cp -R "$SRC" "$STAGED"

# (f/g) Check if app is running and either swap or notify
if pgrep -f "$DEST/Contents/MacOS" >/dev/null; then
  # App is running: notify it to restart after idle
  echo "${LOG_PREFIX} app is running; notifying for deferred update..."
  REFRESH_PORT="${MARVIN_DASHBOARD_REFRESH_PORT:-7879}"
  COMMIT_SHA=$(git -C "$HOME/.agents" rev-parse --short HEAD 2>/dev/null || echo 'unknown')
  if curl -s -X POST "http://localhost:${REFRESH_PORT}" \
    -H "Content-Type: application/json" \
    -d "{\"topics\":[\"update\"],\"source\":\"rebuild\",\"sha\":\"$COMMIT_SHA\"}" \
    >/dev/null 2>&1; then
    # Mark staged build only on successful notification
    date +%s > "$STAGED_BUILT" 2>/dev/null || true
  else
    echo "${LOG_PREFIX} could not notify app of update; will retry at next dashboard change" >&2
  fi
else
  # App is not running: swap staged into place and launch
  echo "${LOG_PREFIX} app is not running; swapping staged build into place..."

  # Two-step atomic swap with backup: move live away, move staged in place
  if [ -d "$DEST" ]; then
    BACKUP="${DEST}.old.$(date +%s)"
    mv "$DEST" "$BACKUP"
    echo "${LOG_PREFIX} backed up old app to $BACKUP"
  fi
  mv "$STAGED" "$DEST"

  if [ -d "$LEGACY_DEST" ]; then
    echo "${LOG_PREFIX} removing the old MARVIN Metrics.app..."
    rm -rf "$LEGACY_DEST"
  fi

  echo "${LOG_PREFIX} relaunching..."
  open -a "$DEST"
  sleep 6
  if ! pgrep -f "$DEST/Contents/MacOS" >/dev/null; then
    echo "${LOG_PREFIX} the app did not start after the install" >&2
    exit 1
  fi
  date +%s > "$STAGED_BUILT" 2>/dev/null || true
fi

# Restart the merge server on the new code
if launchctl print "gui/$(id -u)/com.marvin.dashboard-webhook" >/dev/null 2>&1; then
  echo "${LOG_PREFIX} waiting for any running merges to finish..."
  "$HOME/.agents/venv/bin/python" "$HOME/.agents/lib/merge_server_wait.py" || true
  echo "${LOG_PREFIX} restarting the merge server on the new code..."
  launchctl kickstart -k "gui/$(id -u)/com.marvin.dashboard-webhook" || echo "${LOG_PREFIX} merge server restart failed" >&2
fi

rm -f "$HOME/.claude/logs/dashboard-rebuild-failed"
echo "${LOG_PREFIX} done."
