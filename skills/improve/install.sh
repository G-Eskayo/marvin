#!/usr/bin/env bash
# Install the daily digest's launchd job for this Mac: the primary (the Mini) gets com.marvin.daily-digest at 08:30,
# every other Mac gets com.marvin.daily-digest-fallback, which builds only if the Mini went quiet. The other half of the
# pair is booted out and removed. Before #1123 this always installed the primary plist, so the laptop ran it at the usual
# time, its fallback gate said "before deadline", and it skipped every day.
set -euo pipefail
mkdir -p "$HOME/.claude/logs"
exec "$HOME/.agents/venv/bin/python" "$HOME/.agents/lib/brief_fallback.py" install daily-digest
