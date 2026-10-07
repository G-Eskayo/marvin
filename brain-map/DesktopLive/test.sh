#!/usr/bin/env bash
# Compile and run DesktopLive's tests (bare swiftc, no package).
set -euo pipefail
cd "$(dirname "$0")"
out="$(mktemp -d)"
cp tests/EventLogTests.swift "$out/main.swift"
swiftc EventLog.swift "$out/main.swift" -o "$out/eventlog-tests"
"$out/eventlog-tests"
mkdir "$out/recovery" && cp tests/RecoveryTests.swift "$out/recovery/main.swift"
swiftc Recovery.swift "$out/recovery/main.swift" -o "$out/recovery-tests"
"$out/recovery-tests"
swiftc -typecheck main.swift EventLog.swift Recovery.swift
echo "main.swift typechecks"
