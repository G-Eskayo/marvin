#!/bin/bash
# ci-machine.sh — make a bare CI runner look like a clean MARVIN install, before the Python checks (marvin#826).
#
# The suite reads what every MARVIN machine has: the engine at ~/.agents with its venv, and the read-only inputs
# under ~/.claude that tests see through their temp HOME (conftest.py): the settings naming the memory folder, the
# memory index, the lexicon and the skill manifest. A bare runner has none of them, and 83 tests failed for it
# (2026-10-30). This makes a minimal, empty install, never the owner's data: an empty memory index, an empty
# lexicon, and the manifest built from this checkout's own skills.
set -euo pipefail

ws=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
ln -sfn "$ws" "$HOME/.agents"

python -m venv "$ws/venv"
"$ws/venv/bin/python" -m pip install -q -r "$ws/requirements-ci.txt"
echo "$ws/venv/bin" >> "${GITHUB_PATH:-/dev/null}"   # `python` in a check is the venv's, as on the Macs

memory="$HOME/.claude/projects/$(printf %s "$HOME" | tr / -)/memory"
mkdir -p "$memory"
[ -f "$memory/MEMORY.md" ] || printf '# Memory Index\n' > "$memory/MEMORY.md"
[ -f "$HOME/.claude/settings.json" ] || printf '{"autoMemoryDirectory": "%s"}\n' "$memory" > "$HOME/.claude/settings.json"
[ -f "$HOME/.claude/lexicon.md" ] || printf '# Shared Lexicon\n' > "$HOME/.claude/lexicon.md"
"$ws/venv/bin/python" "$ws/skills/self-improve/scripts/rebuild-manifest.py"
