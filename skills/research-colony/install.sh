#!/usr/bin/env bash
# Install the research colony's launchd job for this Mac: the primary (the Mini) gets com.marvin.research-colony at
# 09:00, every other Mac gets com.marvin.research-colony-fallback, which runs only if the Mini went quiet. The other half
# of the pair is booted out and removed (#1123: the laptop used to get the primary plist and skip every day).
set -euo pipefail
mkdir -p "$HOME/.claude/logs" "$HOME/.claude/research-digest" "$HOME/.claude/research-feed"
exec "$HOME/.agents/venv/bin/python" "$HOME/.agents/lib/brief_fallback.py" install research-colony
