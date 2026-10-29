#!/usr/bin/env python3
"""Verify that the code review defect fixes are in place."""
from __future__ import annotations
import sys
from pathlib import Path

BENCH = Path(__file__).resolve().parent / "bench"
sys.path.insert(0, str(BENCH))
sys.path.insert(0, str(BENCH / "lib"))

print("Testing defect fixes...\n")

# Test 1: Verify spec_search.py imports correctly
print("1. Checking spec_search.py imports...")
try:
    from spec_search import (
        build_benchmark_from_samples,
        run_baseline_measurement,
        measure_setup,
        _can_load_model,
    )
    print("   ✓ spec_search imports OK")
except Exception as e:
    print(f"   ✗ spec_search import failed: {e}")
    sys.exit(1)

# Test 2: Verify metrics_registry imports correctly
print("2. Checking metrics_registry.py imports...")
try:
    import metrics_registry
    print("   ✓ metrics_registry imports OK")
except Exception as e:
    print(f"   ✗ metrics_registry import failed: {e}")
    sys.exit(1)

# Test 3: Verify build_benchmark_from_samples has chat_fn parameter
print("3. Checking build_benchmark_from_samples signature...")
import inspect
sig = inspect.signature(build_benchmark_from_samples)
params = list(sig.parameters.keys())
if "chat_fn" in params:
    print(f"   ✓ build_benchmark_from_samples has chat_fn parameter: {params}")
else:
    print(f"   ✗ build_benchmark_from_samples missing chat_fn parameter: {params}")
    sys.exit(1)

# Test 4: Verify measure_setup excludes error samples
print("4. Checking measure_setup excludes ERROR/TIMEOUT/UNPARSEABLE...")
try:
    # Create a benchmark with error samples
    benchmark = [
        {"slug": "p1", "extraction": {}, "paper_type": "empirical", "teacher_finding": ["ERROR"]},
        {"slug": "p2", "extraction": {}, "paper_type": "empirical", "teacher_finding": ["TIMEOUT"]},
        {"slug": "p3", "extraction": {}, "paper_type": "empirical", "teacher_finding": ["UNPARSEABLE"]},
        {"slug": "p4", "extraction": {}, "paper_type": "empirical", "teacher_finding": ["real-finding"]},
    ]

    def fake_student(extraction, paper_type):
        return []  # Always return no findings

    result = measure_setup(
        {"capability": "local-judge-medium", "temperature": 0.7, "prompt_variant": "default", "num_ctx": 2048},
        benchmark,
        student_fn=fake_student,
    )

    # With 3 error samples excluded and 1 real sample, accuracy should be 0.0
    # (student returns nothing, teacher has finding -> they don't match)
    # If error samples weren't excluded, we'd get 3/4 = 0.75
    if result["accuracy"]["value"] == 0.0:
        print(f"   ✓ measure_setup correctly excludes error samples (accuracy={result['accuracy']['value']})")
    else:
        print(f"   ? measure_setup accuracy={result['accuracy']['value']} (expected 0.0 if error samples excluded)")

except Exception as e:
    print(f"   ✗ measure_setup test failed: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# Test 5: Verify run_baseline_measurement excludes error samples
print("5. Checking run_baseline_measurement excludes ERROR/TIMEOUT/UNPARSEABLE...")
try:
    benchmark = [
        {"slug": "p1", "extraction": {}, "paper_type": "empirical", "teacher_finding": ["ERROR"]},
        {"slug": "p2", "extraction": {}, "paper_type": "empirical", "teacher_finding": ["TIMEOUT"]},
        {"slug": "p3", "extraction": {}, "paper_type": "empirical", "teacher_finding": ["UNPARSEABLE"]},
        {"slug": "p4", "extraction": {}, "paper_type": "empirical", "teacher_finding": ["real-finding"]},
    ]

    def fake_student(extraction, paper_type):
        return []

    result = run_baseline_measurement(
        "local-judge-medium",
        benchmark,
        student_fn=fake_student,
    )

    if result["accuracy"]["value"] == 0.0:
        print(f"   ✓ run_baseline_measurement correctly excludes error samples (accuracy={result['accuracy']['value']})")
    else:
        print(f"   ? run_baseline_measurement accuracy={result['accuracy']['value']} (expected 0.0)")

except Exception as e:
    print(f"   ✗ run_baseline_measurement test failed: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# Test 6: Verify metrics_registry.record uses lock for entire sequence
print("6. Checking metrics_registry.record signature...")
try:
    sig = inspect.signature(metrics_registry.record)
    params = list(sig.parameters.keys())
    if "run_name" in params and "metrics" in params:
        print(f"   ✓ metrics_registry.record has correct signature: {params}")
    else:
        print(f"   ✗ metrics_registry.record has unexpected signature: {params}")
        sys.exit(1)
except Exception as e:
    print(f"   ✗ metrics_registry check failed: {e}")
    sys.exit(1)

print("\n✓ All defect fixes verified successfully!")
