#!/bin/bash
# Cross-model bench sweep (Haiku/Sonnet/Opus)
#
# Runs the full 14-task suite across three model tiers, sequentially,
# to compare MARVIN vs clean profiles and validate the shrinking-gains hypothesis.
#
# Total: 14 tasks × 2 profiles × 3 tiers = 84 sessions (no --judge, no --repeat>1)
# Estimated: ~2-3 hours wall time, depending on task timeouts and queue.
#
# IMPORTANT: Run against a PINNED MARVIN profile snapshot. Profile drift across
# the sweep would confound model comparison. See plan note.
#
# Sanity checks:
#   - claude -p "ok" works (preflight quota check in bench.py)
#   - claude --model claude-opus-5 works (quick 1-word response)

set -e

# Quick model sanity check: verify Opus model ID is valid
echo "=== Sanity check: claude-opus-5 availability ==="
timeout 10 claude -p "Reply with exactly one word." --model claude-opus-5 || {
    echo "ERROR: claude-opus-5 model is not available or CLI is not functional"
    exit 1
}
echo "✓ Opus model available"
echo

# Define sweep targets
TASKS="tasks/*"
PROFILES="clean,marvin"
TIMESTAMP=$(date +%Y%m%d-%H%M%S)
LOG_DIR="sweep-logs-${TIMESTAMP}"
mkdir -p "${LOG_DIR}"

# Tier 1: Sonnet (default, no --model flag)
echo "=== TIER 1: Sonnet (default) - $(date) ==="
python3 bench.py $TASKS --profiles $PROFILES 2>&1 | tee "${LOG_DIR}/sonnet.log"
echo "✓ Sonnet tier complete"
echo

# Tier 2: Haiku
echo "=== TIER 2: Haiku (claude-haiku-4-5-20251001) - $(date) ==="
python3 bench.py $TASKS --profiles $PROFILES --model claude-haiku-4-5-20251001 2>&1 | tee "${LOG_DIR}/haiku.log"
echo "✓ Haiku tier complete"
echo

# Tier 3: Opus
echo "=== TIER 3: Opus (claude-opus-5) - $(date) ==="
python3 bench.py $TASKS --profiles $PROFILES --model claude-opus-5 2>&1 | tee "${LOG_DIR}/opus.log"
echo "✓ Opus tier complete"
echo

# Aggregate results
echo "=== Aggregating results ==="
python3 cross_model_report.py \
    --results-dir results \
    --models "default,claude-haiku-4-5-20251001,claude-opus-5" \
    | tee "${LOG_DIR}/report.md"

echo
echo "=== Sweep complete ==="
echo "Results saved in:"
echo "  - results/ (individual task JSONs)"
echo "  - ${LOG_DIR}/ (sweep logs and aggregated report)"
