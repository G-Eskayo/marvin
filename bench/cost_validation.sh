#!/usr/bin/env bash
# Does MARVIN cut the cost of AI-assisted work, and where? (marvin#645, Run 31)
#
#   bench/cost_validation.sh [OUT_DIR]      # default: bench/results/cost-<date>
#
# Same model for every main cell (the account default; Run 31: claude-opus-5-5), N=3
# per cell, LLM judge on every run, hidden pytest checks on the coding tasks. It stops
# before a task when the plan's five-hour or seven-day usage is above 75%; rerun the
# same command later and point cost_report.py at both folders.
# Run 31 spent about $25 at API prices (about 75 sessions with judges).
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$HERE"
PY="${PY:-$HOME/.agents/venv/bin/python}"
OUT="${1:-results/cost-$(date +%Y%m%d)}"
COMMON=(--repeat 3 --judge --out-dir "$OUT" --stop-above 0.75)

[ -d profiles/clean ] || bash profiles/setup.sh

# 1. Plain Claude Code against MARVIN, same tasks, same model.
"$PY" bench.py tasks/task-013-lru-cache-bug tasks/task-017-holiday-sla tasks/task-015-flag-bucketing \
  tasks/task-012-protocol-mismatch tasks/task-004-caveman tasks/task-014-kb-lookup \
  --profiles clean,marvin "${COMMON[@]}"

# 2. Levers, one at a time, everything else held constant.
#    Model routing: route.py sends research to Haiku; recall now stays on the session model (PR #1125).
"$PY" bench.py tasks/task-004-caveman tasks/task-014-kb-lookup --profiles marvin \
  --model claude-haiku-4-5-20251001 "${COMMON[@]}"
#    Caveman: the opt-in trigger, on an explain task and a coding task.
"$PY" bench.py tasks/task-004-caveman tasks/task-013-lru-cache-bug --profiles marvin \
  --prompt-prefix "Caveman mode. " --tag caveman "${COMMON[@]}"
#    Memory: plain Claude Code with the notes pasted in, against MARVIN's KB lookup (task-014).
"$PY" bench.py tasks/task-018-kb-repaste --profiles clean --tag repaste "${COMMON[@]}"

# 3. Report.
"$PY" cost_report.py "$OUT" --base clean --treat marvin
"$PY" cost_report.py "$OUT" --base marvin --treat marvin@haiku --treat marvin+caveman
