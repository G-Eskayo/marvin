#!/usr/bin/env python3
"""Restore test_health_checks.py from main branch."""
import subprocess
import sys
from pathlib import Path

result = subprocess.run(
    ['git', 'show', 'main:lib/tests/test_health_checks.py'],
    capture_output=True, text=True, check=True
)

# Get the first 28 lines from the current file (keep the first few tests)
current_file = Path('lib/tests/test_health_checks.py').read_text()
current_lines = current_file.split('\n')

# Get main version
main_lines = result.stdout.split('\n')

# Check if we're keeping embedded pipeline_purpose tests
# Look for the pipeline_purpose tests in current file
pipeline_purpose_start = None
for i, line in enumerate(current_lines):
    if '# ── pipeline purpose' in line:
        pipeline_purpose_start = i
        break

# Find where pipeline_purpose tests end in main (should be at end)
# Since main doesn't have pipeline_purpose, we'll add them at the end

# Write the restored version: main content + pipeline_purpose tests if they exist
if pipeline_purpose_start:
    # Extract the pipeline_purpose section from current file
    pipeline_purpose_tests = '\n'.join(current_lines[pipeline_purpose_start:])
    # Remove the last test section from main and add pipeline_purpose
    main_content = '\n'.join(main_lines)
    restored = main_content + '\n\n' + pipeline_purpose_tests
else:
    restored = result.stdout

Path('lib/tests/test_health_checks.py').write_text(restored)
print(f"Restored {len(restored.splitlines())} lines")
print(f"Test count: {restored.count('def test_')}")
sys.exit(0)
