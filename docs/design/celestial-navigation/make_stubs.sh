#!/bin/bash
# Preview icon variants on the real OS: one stub app per variant, for iOS (simulator) and macOS.
# usage: make_stubs.sh <variant>...   (each variant needs png/<variant>.png at 1024x1024)
# Installs the iOS stubs on the booted iPhone simulator, screenshots its home screen, and renders the macOS icons
# exactly as macOS draws them (NSWorkspace, which honours tinted icon mode).
set -euo pipefail
P="$(cd "$(dirname "$0")" && pwd)"; S="$P/stub"; U="${SIM_UDID:-F0AD7DDE-45FF-4450-AC01-5D12B4DBB0BB}"
OSICON="${OSICON:-/private/tmp/claude-501/-Users-gileskayo/7d7a57bd-8ec1-46e4-a059-71223f09ba73/scratchpad/osicon.swift}"
VS=("$@"); TAG="${TAG:-$(date +%H%M)}"
rm -rf "$S"/ios* "$S"/mac* "$S/build" "$S/IconPreview.xcodeproj"; mkdir -p "$S/Shared" "$P/shots"
[ -f "$S/Shared/App.swift" ] || printf 'import SwiftUI\n@main struct StubApp: App { var body: some Scene { WindowGroup { Text("MARVIN icon preview").padding(40) } } }\n' > "$S/Shared/App.swift"
{
  echo "name: IconPreview"; echo "options: {bundleIdPrefix: me.gileskayo.iconpreview}"
  echo "settings: {base: {GENERATE_INFOPLIST_FILE: YES, MARKETING_VERSION: '1.0', CURRENT_PROJECT_VERSION: '1', CODE_SIGN_STYLE: Automatic, CODE_SIGN_IDENTITY: '-', ASSETCATALOG_COMPILER_APPICON_NAME: AppIcon}}"
  echo "targets:"
  for v in "${VS[@]}"; do
    d="$S/ios$v/Assets.xcassets/AppIcon.appiconset"; mkdir -p "$d"; cp "$P/png/$v.png" "$d/icon.png"
    printf '{"images":[{"filename":"icon.png","idiom":"universal","platform":"ios","size":"1024x1024"}],"info":{"author":"xcode","version":1}}' > "$d/Contents.json"
    printf '{"info":{"author":"xcode","version":1}}' > "$S/ios$v/Assets.xcassets/Contents.json"
    d="$S/mac$v/Assets.xcassets/AppIcon.appiconset"; mkdir -p "$d"; imgs=""
    for s in 16 32 128 256 512; do for sc in 1 2; do px=$((s*sc)); f="icon_${s}x${s}@${sc}x.png"
      sips -z $px $px "$P/png/$v.png" --out "$d/$f" >/dev/null
      imgs="$imgs{\"filename\":\"$f\",\"idiom\":\"mac\",\"scale\":\"${sc}x\",\"size\":\"${s}x${s}\"},"; done; done
    printf '{"images":[%s],"info":{"author":"xcode","version":1}}' "${imgs%,}" > "$d/Contents.json"
    printf '{"info":{"author":"xcode","version":1}}' > "$S/mac$v/Assets.xcassets/Contents.json"
    cat <<EOF
  ios$v:
    type: application
    platform: iOS
    deploymentTarget: "26.0"
    sources: [Shared, ios$v]
    settings: {base: {PRODUCT_BUNDLE_IDENTIFIER: me.gileskayo.iconpreview.ios$v, INFOPLIST_KEY_CFBundleDisplayName: "MARVIN $v", INFOPLIST_KEY_UILaunchScreen_Generation: YES, CODE_SIGNING_ALLOWED: NO}}
  mac$v:
    type: application
    platform: macOS
    deploymentTarget: "26.0"
    sources: [Shared, mac$v]
    settings: {base: {PRODUCT_BUNDLE_IDENTIFIER: me.gileskayo.iconpreview.mac$v, PRODUCT_NAME: "MARVIN $v", INFOPLIST_KEY_CFBundleDisplayName: "MARVIN $v"}}
EOF
  done
} > "$S/project.yml"
cd "$S"; xcodegen generate >/dev/null; D="$S/build"
xcrun simctl boot "$U" 2>/dev/null || true; xcrun simctl bootstatus "$U" >/dev/null 2>&1
# clear previous preview stubs off the home screen so only this round shows
for b in $(xcrun simctl listapps "$U" 2>/dev/null | grep -oE 'me\.gileskayo\.iconpreview\.[A-Za-z0-9]+' | sort -u); do xcrun simctl uninstall "$U" "$b" || true; done
for v in "${VS[@]}"; do
  xcodebuild -project IconPreview.xcodeproj -scheme "ios$v" -destination 'generic/platform=iOS Simulator' -derivedDataPath "$D" -quiet build 2>&1 | grep " error" || true
  xcodebuild -project IconPreview.xcodeproj -scheme "mac$v" -destination 'platform=macOS' -derivedDataPath "$D" -quiet build 2>&1 | grep " error" || true
  xcrun simctl install "$U" "$D/Build/Products/Debug-iphonesimulator/ios$v.app"
done
sleep 2; xcrun simctl io "$U" screenshot "$P/shots/ios-home-$TAG.png" >/dev/null 2>&1
apps=(); for v in "${VS[@]}"; do apps+=("$D/Build/Products/Debug/MARVIN $v.app"); done
swift "$OSICON" 256 "$P/shots/mac-icons-$TAG.png" "${apps[@]}" /System/Applications/Calendar.app
echo "shots/ios-home-$TAG.png shots/mac-icons-$TAG.png"
