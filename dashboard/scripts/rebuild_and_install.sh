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

echo "${LOG_PREFIX} building..."
npm run build:mac

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

echo "${LOG_PREFIX} done."
