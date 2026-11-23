#!/bin/bash
# Install MARVIN's mail sorter (#1405) from the repo template. Run on ONE machine only (the Mini): two sorters would
# both alert. Needs instance/config/mail/{gmail,rules}.json and the app password in Keychain:
#   security add-generic-password -s marvin-mail-gmail -a <address> -w   (prompts; never put it on the command line)
# Checks the config and a live sign-in (`run --once`) before loading, so a bad setup fails here, not silently.
# Usage: bash ~/.agents/lib/launchd/install_mail_sorter.sh        Remove: ... --remove
set -euo pipefail
LABEL=com.marvin.mail-sorter
SRC="$HOME/.agents/lib/launchd/$LABEL.plist"
DEST="$HOME/Library/LaunchAgents/$LABEL.plist"
UID_NUM=$(id -u)
PY="$HOME/.agents/venv/bin/python"

if [ "${1:-}" = "--remove" ]; then
  launchctl bootout "gui/$UID_NUM/$LABEL" 2>/dev/null || true
  rm -f "$DEST"
  echo "removed $LABEL"
  exit 0
fi

mkdir -p "$HOME/.claude/logs" "$HOME/Library/LaunchAgents"
"$PY" "$HOME/.agents/lib/mail_sorter.py" run --once --account gmail
[ -f "$DEST" ] && cp "$DEST" "$DEST.bak-$(date +%Y%m%d%H%M%S)"
sed "s#__HOME__#$HOME#g" "$SRC" > "$DEST.new"
plutil -lint "$DEST.new" >/dev/null
mv "$DEST.new" "$DEST"
launchctl bootout "gui/$UID_NUM/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$UID_NUM" "$DEST"
launchctl print "gui/$UID_NUM/$LABEL" | grep -E "state =" | head -1
echo "installed $LABEL"
