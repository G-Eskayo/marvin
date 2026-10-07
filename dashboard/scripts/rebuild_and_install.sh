#!/bin/bash
# Rebuilds the MARVIN Metrics dashboard and installs it over the running
# copy in /Applications, so a merged PR actually shows up in the app people
# use day-to-day instead of only existing in dist/. Triggered by
# webhook-server/merge.js after a merge that touched dashboard/ files;
# safe to run by hand too.
set -euo pipefail
cd "$(dirname "$0")/.."

APP_NAME="MARVIN Metrics.app"
SRC="dist/mac-arm64/${APP_NAME}"
DEST="/Applications/${APP_NAME}"
LOG_PREFIX="[rebuild-and-install]"

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
osascript -e 'quit app "MARVIN Metrics"' 2>/dev/null || true
sleep 1

echo "${LOG_PREFIX} installing to $DEST..."
rm -rf "$DEST"
cp -R "$SRC" "$DEST"

echo "${LOG_PREFIX} relaunching..."
open -a "$DEST"
sleep 6
if ! pgrep -f "$DEST/Contents/MacOS" >/dev/null; then
  echo "${LOG_PREFIX} the app did not start after the install" >&2
  exit 1
fi

echo "${LOG_PREFIX} done."
