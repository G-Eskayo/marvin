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
  # Release the rebuild lock on failure.
  if [ -n "${LOCK_DIR:-}" ]; then
    "$HOME/.agents/venv/bin/python" "$HOME/.agents/lib/rebuild_lock.py" release "$LOCK_DIR" 2>/dev/null || true
  fi
}
trap 'on_error $LINENO' ERR
cd "$(dirname "$0")/.."

# Demo hold: if the flag file is present, skip the rebuild entirely (demo mode).
if [ -f "$HOME/.claude/logs/dashboard-demo-hold" ]; then
  echo "[rebuild-and-install] demo hold is active; skipping rebuild" >&2
  exit 0
fi

# Acquire the rebuild lock before pulling; if already held, exit cleanly.
export LOCK_DIR="$HOME/.claude/logs"
lock_result=$("$HOME/.agents/venv/bin/python" "$HOME/.agents/lib/rebuild_lock.py" acquire "$LOCK_DIR" 2>/dev/null || echo "BUSY")
if [ "$lock_result" = "BUSY" ]; then
  echo "[rebuild-and-install] a rebuild is already running; exiting cleanly" >&2
  exit 0
fi

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

echo "${LOG_PREFIX} installing to $DEST (atomic swap)..."
# Atomic swap: move the old bundle aside, install the new one, then delete the old one.
# This ensures $DEST is never half-deleted (closes the other half of #392).
if [ -d "$DEST" ]; then
  DEST_OLD="${DEST}.bak"
  mv "$DEST" "$DEST_OLD"
else
  DEST_OLD=""
fi
mv "$SRC" "$DEST"
if [ -n "$DEST_OLD" ]; then
  rm -rf "$DEST_OLD"
fi
if [ -d "$LEGACY_DEST" ]; then
  echo "${LOG_PREFIX} removing the old MARVIN Metrics.app (renamed to MARVIN.app)..."
  rm -rf "$LEGACY_DEST"
fi

# Check whether the app was already running before we started the build.
app_was_running=false
if pgrep -f "$DEST/Contents/MacOS" >/dev/null 2>&1; then
  app_was_running=true
fi

# Re-check loop: after installing, re-fetch/compare origin/main's dashboard-relevant commit.
# If it moved, loop and rebuild again before notifying -- "second build wins, one prompt".
max_loops=3
loop_count=0
while [ $loop_count -lt $max_loops ]; do
  loop_count=$((loop_count + 1))

  # Fetch latest and check the newest dashboard commit.
  "$HOME/.agents/venv/bin/python" "$HOME/.agents/lib/code_sync.py" pull "$HOME/.agents" 2>/dev/null || true
  current_sha=$(git -C "$HOME/.agents" rev-parse origin/main -- 2>/dev/null | head -c 7 || echo "unknown")

  if [ $loop_count -eq 1 ]; then
    echo "${LOG_PREFIX} built and installed (sha: $current_sha)"
  else
    echo "${LOG_PREFIX} re-check loop #$loop_count: code is current"
  fi

  # On the final loop iteration or if no more code landed, write the ready file and exit.
  if [ $loop_count -eq $max_loops ]; then
    echo "${LOG_PREFIX} final loop iteration; marking ready"
    break
  fi

  # Check if newer code landed; if not, we're done.
  newest=$(git -C "$HOME/.agents" log -1 --format=%ct origin/main -- dashboard/src dashboard/electron dashboard/index.html dashboard/package.json dashboard/package-lock.json dashboard/electron.vite.config.js dashboard/tailwind.config.js dashboard/postcss.config.js dashboard/resources 2>/dev/null || echo "")
  if [ -z "$newest" ] || [ "$newest" -eq "$(git -C "$HOME/.agents" log -1 --format=%ct origin/main~1 -- dashboard/src dashboard/electron dashboard/index.html dashboard/package.json dashboard/package-lock.json dashboard/electron.vite.config.js dashboard/tailwind.config.js dashboard/postcss.config.js dashboard/resources 2>/dev/null || echo 0)" ]; then
    echo "${LOG_PREFIX} no newer code; ready"
    break
  fi

  # Newer code landed; rebuild.
  echo "${LOG_PREFIX} newer dashboard code detected; rebuilding..."
  npm install --no-audit --no-fund 2>/dev/null || true
  npm run build:mac 2>/dev/null || {
    # Signed build failed; try again ad-hoc.
    rm -rf "dist/mac-arm64"
    npx electron-builder --mac --dir -c.mac.identity=- 2>/dev/null || true
    codesign --force --deep -s - "$SRC" 2>/dev/null || true
  }
  if [ ! -d "$SRC" ]; then
    echo "${LOG_PREFIX} rebuild failed" >&2
    exit 1
  fi
  # Atomic swap again.
  DEST_OLD="${DEST}.bak"
  mv "$DEST" "$DEST_OLD"
  mv "$SRC" "$DEST"
  rm -rf "$DEST_OLD"
done

# If the app was running before, do not quit/relaunch -- just write the ready file.
# If the app was not running (fresh/offline install), launch it.
if ! $app_was_running && ! pgrep -f "$DEST/Contents/MacOS" >/dev/null 2>&1; then
  echo "${LOG_PREFIX} launching app..."
  open -a "$DEST"
  sleep 6
  if ! pgrep -f "$DEST/Contents/MacOS" >/dev/null; then
    echo "${LOG_PREFIX} the app did not start after the install" >&2
    exit 1
  fi
elif $app_was_running; then
  echo "${LOG_PREFIX} app was already running; will restart via ready-file trigger"
fi

# The merge server is a long-running node process: it keeps the code it started with until restarted (it ran Oct 5 code
# on Oct 8, so a merged fix to the merge flow didn't apply). This script runs detached, so restarting it is safe.
if launchctl print "gui/$(id -u)/com.marvin.dashboard-webhook" >/dev/null 2>&1; then
  echo "${LOG_PREFIX} waiting for any running merges to finish..."
  "$HOME/.agents/venv/bin/python" "$HOME/.agents/lib/merge_server_wait.py" || true
  echo "${LOG_PREFIX} restarting the merge server on the new code..."
  launchctl kickstart -k "gui/$(id -u)/com.marvin.dashboard-webhook" || echo "${LOG_PREFIX} merge server restart failed" >&2
fi

# Write the ready file: { sha, installedAt }.
# This triggers the dashboard's rebuild handlers and shows the update-ready banner.
mkdir -p "$HOME/.claude/logs"
readonly READY_FILE_TMP="$HOME/.claude/logs/dashboard-build-ready.json.tmp"
readonly READY_FILE="$HOME/.claude/logs/dashboard-build-ready.json"
sha=$(git -C "$HOME/.agents" rev-parse origin/main 2>/dev/null | head -c 40 || echo "unknown")
printf '{"sha":"%s","installedAt":%d}' "$sha" "$(date +%s)" > "$READY_FILE_TMP"
mv "$READY_FILE_TMP" "$READY_FILE"

rm -f "$HOME/.claude/logs/dashboard-rebuild-failed"  # a good install clears any earlier failure (#443)
"$HOME/.agents/venv/bin/python" "$HOME/.agents/lib/rebuild_lock.py" release "$HOME/.claude/logs" 2>/dev/null || true
echo "${LOG_PREFIX} done."
