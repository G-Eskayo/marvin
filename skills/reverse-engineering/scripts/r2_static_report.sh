#!/bin/bash
# radare2 static analysis report generator
#
# Runs a standard triage sequence on a binary and outputs JSON.
#
# Usage:
#     bash r2_static_report.sh --binary <path> --i-own-this-target [--output <json-file>]
#
# Example:
#     bash r2_static_report.sh --binary ./myapp --i-own-this-target --output report.json

set -euo pipefail

# Parse arguments
BINARY=""
OWN_TARGET=false
OUTPUT=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --binary)
            BINARY="$2"
            shift 2
            ;;
        --i-own-this-target)
            OWN_TARGET=true
            shift
            ;;
        --output)
            OUTPUT="$2"
            shift 2
            ;;
        *)
            echo "Usage: $0 --binary <path> --i-own-this-target [--output <file>]" >&2
            exit 1
            ;;
    esac
done

# Authorization gate
if [ "$OWN_TARGET" != true ]; then
    echo "[!] Authorization gate: you must confirm --i-own-this-target" >&2
    echo "    before running reverse-engineering tools on a binary." >&2
    exit 1
fi

# Validate binary
if [ -z "$BINARY" ]; then
    echo "[!] --binary is required" >&2
    exit 1
fi

if [ ! -f "$BINARY" ]; then
    echo "[!] Binary not found: $BINARY" >&2
    exit 1
fi

# Check for radare2
if ! command -v r2 &> /dev/null; then
    echo "[!] radare2 not installed. Install with: brew install radare2 (or apt-get install radare2)" >&2
    exit 1
fi

# Run triage sequence
# Commands:
#   aaa         : auto-analyze
#   afl         : list functions
#   pdf @ main  : disassemble main
#   iz          : strings
#   ii          : imports
#   axt @main   : all xrefs to main
#
# JSON output via -j flag (not all commands support it, so we'll parse selectively)

echo "[*] Analyzing $BINARY ..." >&2

# Collect analysis results
FUNCTIONS=$(r2 -q -A -c 'aflj' "$BINARY" 2>/dev/null || echo '[]')
STRINGS=$(r2 -q -A -c 'izj' "$BINARY" 2>/dev/null || echo '[]')
IMPORTS=$(r2 -q -A -c 'iij' "$BINARY" 2>/dev/null || echo '[]')

# Get basic info (architecture, entry point)
ENTRY=$(r2 -q -c 'e?bin.baddr' "$BINARY" 2>/dev/null | head -1 | cut -d' ' -f3 || echo "0x0")
ARCH=$(r2 -q -c 'e?asm.arch' "$BINARY" 2>/dev/null | head -1 | cut -d' ' -f3 || echo "unknown")

# Build JSON output
REPORT=$(cat <<EOF
{
  "binary": "$(basename "$BINARY")",
  "arch": "$ARCH",
  "entry_point": "$ENTRY",
  "functions": $FUNCTIONS,
  "strings": $STRINGS,
  "imports": $IMPORTS,
  "timestamp": "$(date -u +'%Y-%m-%dT%H:%M:%SZ')"
}
EOF
)

# Output to file or stdout
if [ -n "$OUTPUT" ]; then
    echo "$REPORT" > "$OUTPUT"
    echo "[+] Report written to $OUTPUT" >&2
else
    echo "$REPORT"
fi
