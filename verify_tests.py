#!/usr/bin/env python3
"""Minimal test runner to verify same_category_gap implementation."""
import sys
from pathlib import Path

# Add brain-map/scripts to path
sys.path.insert(0, str(Path(__file__).parent / "brain-map" / "scripts"))
sys.path.insert(0, str(Path(__file__).parent / "brain-map" / "scripts" / "tests"))

import same_category_gap as scg
import test_same_category_gap as tests

def run_tests():
    """Run all test functions."""
    test_functions = [
        name for name in dir(tests)
        if name.startswith("test_") and callable(getattr(tests, name))
    ]

    passed = 0
    failed = 0

    for test_name in sorted(test_functions):
        test_func = getattr(tests, test_name)
        try:
            test_func()
            print(f"✓ {test_name}")
            passed += 1
        except AssertionError as e:
            print(f"✗ {test_name}: {e}")
            failed += 1
        except Exception as e:
            print(f"✗ {test_name}: {type(e).__name__}: {e}")
            failed += 1

    print(f"\n{passed} passed, {failed} failed")
    return 0 if failed == 0 else 1

if __name__ == "__main__":
    sys.exit(run_tests())
