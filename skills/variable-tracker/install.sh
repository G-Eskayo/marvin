#!/usr/bin/env bash
# Install variable-tracker alias into ~/.zshrc
# Re-running is safe — adds alias only if not already present.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TRACK_VARS="$HOME/.agents/venv/bin/python $SCRIPT_DIR/scripts/track_vars.py"
ZSHRC="$HOME/.zshrc"

already_installed() {
  grep -q "alias track-vars=" "$ZSHRC" 2>/dev/null
}

if already_installed; then
  echo "track-vars alias already in $ZSHRC — nothing to do."
  exit 0
fi

echo "" >> "$ZSHRC"
echo "# Variable tracker alias (added by ~/.agents/skills/variable-tracker/install.sh)" >> "$ZSHRC"
echo "alias track-vars='$TRACK_VARS'" >> "$ZSHRC"

echo "Alias installed in $ZSHRC:"
echo "  alias track-vars='$TRACK_VARS'"
echo ""
echo "Reload your shell to activate: source $ZSHRC"
echo "Or start a new terminal window."
