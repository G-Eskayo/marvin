#!/bin/bash
# Seed the qa-knowledge ChromaDB with the required fact for this task.
# Run this before executing the task: bash setup.sh

set -e

AGENTS_VENV="${HOME}/.agents/venv"
if [ ! -f "${AGENTS_VENV}/bin/python" ]; then
    echo "Error: marvin venv not found at ${AGENTS_VENV}"
    echo "Set up the marvin profile first: profiles/setup.sh"
    exit 1
fi

# Seed the knowledge base with the agent balancing problem definition
"${AGENTS_VENV}/bin/python" "${HOME}/.agents/skills/qa-agent/scripts/qa_capture.py" \
    --content "The agent balancing problem is when an instruction-following model becomes overly constrained by guideline friction" \
    --category pattern \
    --library claude \
    --tags "instruction-following,model-behavior,constraints,guideline-friction" \
    --confidence high \
    --domain python-agents \
    --pattern-type error-handling \
    --outcome "Excessive guidelines can paralyze instruction-following models; balance is critical for both safety and utility"

echo "✓ Knowledge base seeded with agent balancing problem definition"
