#!/bin/bash
# Seed the task-015 isolation fixture into ChromaDB
# Run this once to populate the qa-knowledge collection with the canary token

# Generate a random 8-character hex token
TOKEN=$(python3 -c "import secrets; print('QA-ISOLATE-' + secrets.token_hex(4))")

echo "Generated token: $TOKEN"
echo "Seeding into ChromaDB..."

# Run qa_capture.py to seed the fixture
~/.agents/venv/bin/python ~/.agents/skills/qa-agent/scripts/qa_capture.py \
  --content "marvin-bench isolated-recall canary: $TOKEN" \
  --category config \
  --tags "bench-fixture,isolated-recall,task-015" \
  --domain marvin-bench \
  --confidence high \
  --outcome "ChromaDB-only fixture for task-015-isolated-kb-recall; never written to a tracked file, proves marvin's pass is attributable to ChromaDB retrieval, not disk or training-data recall."

echo "Fixture seeded. Update task.json expect array with the generated token if needed."
