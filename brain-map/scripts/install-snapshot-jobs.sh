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
# Which machine this is, by hardware id in ~/.claude/marvin-network.json (hostname -s says just "Mac" on the mini).
HOSTNAME=$("$HOME/.agents/venv/bin/python" -c "import sys; sys.path.insert(0, '$SCRIPT_DIR/../lib'); import machine_profile; print(machine_profile.registry_id())" 2>/dev/null || hostname -s)
IS_MINI=0
case "$HOSTNAME" in
  mac-mini-*) IS_MINI=1 ;;
esac

mkdir -p "$LAUNCHD_DIR"

echo "Installing snapshot deployment jobs..."
# Mini only: the dev site runs there, and the nightly job also publishes the map to production (ADR 0057).
# lib/health_checks.py JOB_PLACEMENT says "mini" for both, so the Health tab flags them anywhere else.
if [ "$IS_MINI" -ne 1 ]; then
  echo "Not the mac-mini ($HOSTNAME): skipping. The snapshot jobs run on the mini only."
  exit 0
fi

# Always install the nightly job
NIGHTLY_JOB="$SCRIPT_DIR/launchd/com.marvin.snapshot-deploy-nightly.plist"
if [ -f "$NIGHTLY_JOB" ]; then
  echo "Installing nightly job (02:00, mini only)..."
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
