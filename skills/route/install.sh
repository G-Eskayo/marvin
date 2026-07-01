#!/usr/bin/env bash
# Install MARVIN routing aliases into ~/.zshrc
# Re-running is safe — adds aliases only if not already present.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROUTE_PY="$HOME/.agents/venv/bin/python $SCRIPT_DIR/scripts/route.py"
ZSHRC="$HOME/.zshrc"

ALIASES=(
  "claude-recall"
  "claude-research"
  "claude-code"
  "claude-arch"
  "route"
)

already_installed() {
  grep -q "alias $1=" "$ZSHRC" 2>/dev/null
}

any_missing=false
for alias in "${ALIASES[@]}"; do
  if ! already_installed "$alias"; then
    any_missing=true
    break
  fi
done

if ! $any_missing; then
  echo "All MARVIN routing aliases already in $ZSHRC — nothing to do."
  exit 0
fi

echo "" >> "$ZSHRC"
echo "# MARVIN profile routing aliases (added by ~/.agents/skills/route/install.sh)" >> "$ZSHRC"
$ROUTE_PY --aliases >> "$ZSHRC"

echo "Aliases installed in $ZSHRC:"
$ROUTE_PY --aliases
echo ""
echo "Reload your shell to activate: source $ZSHRC"
echo "Or start a new terminal window."
