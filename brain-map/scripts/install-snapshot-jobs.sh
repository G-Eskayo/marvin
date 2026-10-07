#!/bin/bash
# Install map snapshot deployment launchd jobs on this machine.
#
# Usage:
#   bash brain-map/scripts/install-snapshot-jobs.sh
#
# The nightly job runs every machine (mac-mini-1 and macbook-pro-1) at 02:00 UTC.
# The hourly reactive job runs only on mac-mini-1 (primary automation host).
#
# See brain-map/launchd/*.plist for configuration details.

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LAUNCHD_DIR="$HOME/Library/LaunchAgents"

# Detect machine (primary automation host vs. others)
HOSTNAME=$(hostname -s)
IS_MINI=0
case "$HOSTNAME" in
  *"mini"* | *"Mac-mini"* | *"mac-mini"*)
    IS_MINI=1
    ;;
esac

mkdir -p "$LAUNCHD_DIR"

echo "Installing snapshot deployment jobs..."

# Always install the nightly job
NIGHTLY_JOB="$SCRIPT_DIR/launchd/com.marvin.snapshot-deploy-nightly.plist"
if [ -f "$NIGHTLY_JOB" ]; then
  echo "Installing nightly job (runs every machine at 02:00)..."
  cp "$NIGHTLY_JOB" "$LAUNCHD_DIR/"
  launchctl bootstrap "gui/$(id -u)" "$LAUNCHD_DIR/com.marvin.snapshot-deploy-nightly.plist" 2>/dev/null || \
    launchctl load "$LAUNCHD_DIR/com.marvin.snapshot-deploy-nightly.plist" 2>/dev/null || \
    echo "  Note: job may already be loaded"
else
  echo "ERROR: $NIGHTLY_JOB not found"
  exit 1
fi

# Install the reactive job only on mac-mini
if [ "$IS_MINI" -eq 1 ]; then
  REACTIVE_JOB="$SCRIPT_DIR/launchd/com.marvin.snapshot-deploy-reactive.plist"
  if [ -f "$REACTIVE_JOB" ]; then
    echo "Installing hourly reactive job (primary automation host only)..."
    cp "$REACTIVE_JOB" "$LAUNCHD_DIR/"
    launchctl bootstrap "gui/$(id -u)" "$LAUNCHD_DIR/com.marvin.snapshot-deploy-reactive.plist" 2>/dev/null || \
      launchctl load "$LAUNCHD_DIR/com.marvin.snapshot-deploy-reactive.plist" 2>/dev/null || \
      echo "  Note: job may already be loaded"
  else
    echo "ERROR: $REACTIVE_JOB not found"
    exit 1
  fi
else
  echo "Skipping reactive job (not primary automation host)"
fi

echo "Done. Jobs installed:"
echo "  - com.marvin.snapshot-deploy-nightly (runs at 02:00)"
if [ "$IS_MINI" -eq 1 ]; then
  echo "  - com.marvin.snapshot-deploy-reactive (runs hourly on :00)"
fi

echo ""
echo "To verify installation:"
echo "  launchctl list | grep snapshot-deploy"
echo ""
echo "To view logs:"
echo "  tail -f ~/.claude/logs/deploy-snapshot*.log"
