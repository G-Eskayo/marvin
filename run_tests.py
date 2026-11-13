#!/usr/bin/env python3
"""
Simple test runner for sort_suggestions tests.
"""
import sys
from pathlib import Path

# Add the scripts directory to the path
scripts_dir = Path(__file__).parent / "skills/architecture-review/scripts"
sys.path.insert(0, str(scripts_dir))

# Import test module
tests_dir = scripts_dir / "tests"
sys.path.insert(0, str(tests_dir))

from test_sort_suggestions import (
    test_missing_priority_field_sorts_below_every_real_priority,
    test_looks_merged_single_added_field,
    test_looks_merged_single_priority_field,
    test_looks_merged_multiple_added_fields,
    test_looks_merged_multiple_priority_fields,
    test_looks_merged_multiple_added_and_priority,
    test_looks_merged_no_added_or_priority,
    test_looks_merged_single_fields_no_duplication,
    test_looks_merged_case_sensitive,
    test_looks_merged_whitespace_variations,
)

tests = [
    ('test_missing_priority_field_sorts_below_every_real_priority', test_missing_priority_field_sorts_below_every_real_priority),
    ('test_looks_merged_single_added_field', test_looks_merged_single_added_field),
    ('test_looks_merged_single_priority_field', test_looks_merged_single_priority_field),
    ('test_looks_merged_multiple_added_fields', test_looks_merged_multiple_added_fields),
    ('test_looks_merged_multiple_priority_fields', test_looks_merged_multiple_priority_fields),
    ('test_looks_merged_multiple_added_and_priority', test_looks_merged_multiple_added_and_priority),
    ('test_looks_merged_no_added_or_priority', test_looks_merged_no_added_or_priority),
    ('test_looks_merged_single_fields_no_duplication', test_looks_merged_single_fields_no_duplication),
    ('test_looks_merged_case_sensitive', test_looks_merged_case_sensitive),
    ('test_looks_merged_whitespace_variations', test_looks_merged_whitespace_variations),
]

passed = 0
failed = 0
for name, test_func in tests:
    try:
        test_func()
        print(f'✓ {name}')
        passed += 1
    except AssertionError as e:
        print(f'✗ {name}')
        print(f'  Error: {e}')
        failed += 1
    except Exception as e:
        print(f'✗ {name}')
        print(f'  Unexpected error: {e}')
        failed += 1

print(f'\nResults: {passed} passed, {failed} failed')
sys.exit(0 if failed == 0 else 1)
