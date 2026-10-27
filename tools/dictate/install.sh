#!/bin/bash
# Builds MARVIN Dictate (marvin#730), signs it and installs it to ~/Applications, then starts it.
# Signing with a stable identity keeps macOS's Accessibility, Input Monitoring and Microphone permissions across
# rebuilds; an unsigned (ad-hoc) build has to be allowed again every time. MARVIN_DICTATE_SIGN_IDENTITY overrides the
# identity, MARVIN_DICTATE_APP the install path, MARVIN_DICTATE_NO_OPEN=1 skips starting it.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
app="${MARVIN_DICTATE_APP:-$HOME/Applications/MARVIN Dictate.app}"

swift build -c release --package-path "$here"
bin="$(swift build -c release --package-path "$here" --show-bin-path)/MarvinDictate"

identity="${MARVIN_DICTATE_SIGN_IDENTITY:-$(security find-identity -v -p codesigning 2>/dev/null \
  | awk -F'"' '/Apple Development|Developer ID Application/ {print $2; exit}')}"
identity="${identity:--}"

pkill -x MarvinDictate 2>/dev/null || true
mkdir -p "$app/Contents/MacOS"
cp "$here/Resources/Info.plist" "$app/Contents/Info.plist"
cp "$bin" "$app/Contents/MacOS/MarvinDictate"
codesign --force --sign "$identity" --identifier dev.marvin.dictate "$app"
codesign --verify "$app"
[ "$identity" = "-" ] && echo "Signed ad-hoc: macOS will ask for permissions again after each rebuild."

echo "Installed $app"
[ -n "${MARVIN_DICTATE_NO_OPEN:-}" ] || open "$app"
