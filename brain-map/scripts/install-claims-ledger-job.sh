#!/bin/bash
# Install claims ledger nightly job on this machine.
#
# Usage:
#   bash brain-map/scripts/install-claims-ledger-job.sh
#
# The job runs once daily at 02:30 local time on the mac-mini only (primary automation host).
# It verifies that the MARVIN page's factual claims are still true:
# machine count, merge gate status, repo visibility, and scheduled jobs' health.
#
# See brain-map/launchd/com.marvin.claims-ledger-nightly.plist for details.

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LAUNCHD_DIR="$HOME/Library/LaunchAgents"

# Detect machine (primary automation host vs. others)
HOSTNAME=$("$HOME/.agents/venv/bin/python" -c "import sys; sys.path.insert(0, '$SCRIPT_DIR/../lib'); import machine_profile; print(machine_profile.registry_id())" 2>/dev/null || hostname -s)
IS_MINI=0
case "$HOSTNAME" in
  mac-mini-*) IS_MINI=1 ;;
esac

mkdir -p "$LAUNCHD_DIR"

echo "Installing claims ledger nightly job..."
# Mini only: the nightly scheduler runs there, and the dashboard content evaluation is mini-hosted (ADR 0057, #281).
# lib/health_checks.py JOB_PLACEMENT says "mini" for this job, so the Health tab flags it anywhere else.
if [ "$IS_MINI" -ne 1 ]; then
  echo "Not the mac-mini ($HOSTNAME): skipping. The claims ledger job runs on the mini only."
  exit 0
fi

CLAIMS_JOB="$SCRIPT_DIR/launchd/com.marvin.claims-ledger-nightly.plist"
if [ -f "$CLAIMS_JOB" ]; then
  echo "Installing claims ledger nightly job (02:30, mini only)..."
  cp "$CLAIMS_JOB" "$LAUNCHD_DIR/"
  launchctl bootstrap "gui/$(id -u)" "$LAUNCHD_DIR/com.marvin.claims-ledger-nightly.plist" 2>/dev/null || \
    launchctl load "$LAUNCHD_DIR/com.marvin.claims-ledger-nightly.plist" 2>/dev/null || \
    echo "  Note: job may already be loaded"
else
  echo "ERROR: $CLAIMS_JOB not found"
  exit 1
fi

echo "Done. Job installed:"
echo "  - com.marvin.claims-ledger-nightly (runs at 02:30)"

echo ""
echo "To verify installation:"
echo "  launchctl list | grep claims-ledger"
echo ""
echo "To view logs:"
echo "  tail -f ~/.claude/logs/claims-ledger-nightly*.log"
echo ""
echo "To test manually:"
echo "  ~/.agents/venv/bin/python ~/.agents/brain-map/scripts/claims.py --json"
