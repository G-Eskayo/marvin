#!/usr/bin/env python3
"""Quick syntax check for the refactored modules."""
import sys
import py_compile

files = [
    'lib/resume_check.py',
    'lib/morning_brief.py',
]

errors = []
for f in files:
    try:
        py_compile.compile(f, doraise=True)
        print(f'✓ {f}')
    except py_compile.PyCompileError as e:
        print(f'✗ {f}')
        errors.append(str(e))

if errors:
    print('\nErrors found:')
    for e in errors:
        print(e)
    sys.exit(1)
else:
    print('\nAll files compile successfully!')
    sys.exit(0)
