#!/usr/bin/env python3
"""Quick syntax validation of modified files."""
import sys
import py_compile

files_to_check = [
    "lib/brief_fallback.py",
    "lib/morning_brief.py",
    "lib/cron_health.py",
    "skills/improve/scripts/daily_digest.py",
    "skills/research-colony/scripts/run_colony.py",
    "skills/research-colony/scripts/research_digest.py",
    "lib/tests/test_brief_fallback.py",
    "skills/improve/scripts/tests/test_daily_digest.py",
    "skills/research-colony/scripts/tests/test_research_digest.py",
]

errors = []
for filepath in files_to_check:
    try:
        py_compile.compile(filepath, doraise=True)
        print(f"✓ {filepath}")
    except py_compile.PyCompileError as e:
        errors.append(f"✗ {filepath}: {e}")
        print(f"✗ {filepath}")

if errors:
    print("\nErrors found:")
    for err in errors:
        print(err)
    sys.exit(1)
else:
    print("\n✓ All files have valid syntax")
    sys.exit(0)
