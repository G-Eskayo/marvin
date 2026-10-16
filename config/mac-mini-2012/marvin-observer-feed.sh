#!/bin/bash
# mac-mini-2012 shows the M4 Mini's Health view instead of re-checking every machine itself (ADR 0069): copy the
# Mini's health-status.json, which already covers all three machines, to where the dashboard reads it. Uses the
# observer key (read-only allow-list). Only replaces the local copy with valid JSON, atomically.
set -euo pipefail
dest="$HOME/.claude/logs/health-status.json"
tmp="$(mktemp "$dest.XXXXXX")"
trap 'rm -f "$tmp"' EXIT
ssh -o BatchMode=yes -o ConnectTimeout=8 gils-mac-mini 'cat ~/.claude/logs/health-status.json' > "$tmp"
"$HOME/.agents/venv/bin/python" -c 'import json,sys; json.load(open(sys.argv[1]))' "$tmp"
mv "$tmp" "$dest"
