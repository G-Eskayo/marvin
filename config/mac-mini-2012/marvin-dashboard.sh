#!/bin/bash
# Start the MARVIN dashboard on mac-mini-2012's desktop (ADR 0069). Rebuilds first, so it always matches the code the
# mirror last pulled (about 6 s on this CPU); a failed build still opens the last good build if there is one.
cd "$HOME/.agents/dashboard" || exit 1
log="$HOME/.claude/logs/dashboard-linux.log"
npx --no-install electron-vite build >> "$log" 2>&1 || echo "$(date -Is) build failed, opening the last build" >> "$log"
[ -f out/main/index.js ] || exit 1
exec node_modules/.bin/electron . >> "$log" 2>&1
