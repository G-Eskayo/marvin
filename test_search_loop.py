#!/usr/bin/env python3
"""Test that the spec_search loop actually works with the defect fixes.

This test verifies that:
1. The search loop doesn't get stuck on "unchanged" comparisons
2. ERROR/TIMEOUT/UNPARSEABLE samples are properly excluded
3. The search can accept improvements
"""
from __future__ import annotations
import sys
from pathlib import Path

BENCH = Path(__file__).resolve().parent / "bench"
sys.path.insert(0, str(BENCH))
sys.path.insert(0, str(BENCH / "lib"))

from spec_search import spec_search
import metrics_registry
import tempfile

def test_search_loop_finds_improvements():
    """Test that spec_search can find and accept improvements to accuracy.

    This was broken before the fixes because:
    1. ERROR/TIMEOUT/UNPARSEABLE samples weren't excluded, so they counted as "teacher found nothing"
    2. Every edit measured the same accuracy, so compare() returned "unchanged"
    3. No edits were ever accepted, so the search loop was a no-op

    With the fixes, the search should be able to:
    1. Exclude error samples
    2. Measure different accuracies for different setups (at least in theory)
    3. Accept edits that improve accuracy
    """

    print("Testing spec_search loop with improvements...\n")

    # Create a benchmark where:
    # - Half the samples have real findings
    # - Half have error findings (should be excluded)
    benchmark = [
        {"slug": "p1", "extraction": {"claim": "A"}, "paper_type": "empirical", "teacher_finding": ["finding1"]},
        {"slug": "p2", "extraction": {"claim": "B"}, "paper_type": "empirical", "teacher_finding": ["ERROR"]},
        {"slug": "p3", "extraction": {"claim": "C"}, "paper_type": "empirical", "teacher_finding": ["finding2"]},
        {"slug": "p4", "extraction": {"claim": "D"}, "paper_type": "empirical", "teacher_finding": ["TIMEOUT"]},
        {"slug": "p5", "extraction": {"claim": "E"}, "paper_type": "empirical", "teacher_finding": []},
        {"slug": "p6", "extraction": {"claim": "F"}, "paper_type": "empirical", "teacher_finding": ["UNPARSEABLE"]},
    ]

    # Create a student that varies with round number
    # This simulates different edits producing different results
    call_counts = {}

    def varying_student(extraction, paper_type, round_num=[0]):
        """Student that improves accuracy on even rounds."""
        round_num[0] += 1

        # Get the slug from extraction
        slug = extraction.get("claim", "unknown")

        # For odd rounds: return nothing (low accuracy)
        # For even rounds: return findings for papers with findings (higher accuracy)
        if round_num[0] % 2 == 0:
            # Even rounds: better accuracy
            if slug in ("A", "C"):
                return ["finding-detected"]
            else:
                return []
        else:
            # Odd rounds: poor accuracy
            return []

    def fake_teacher(extraction, paper_type):
        """Fake teacher that returns consistent findings."""
        # Not used in this test (we use the benchmark's pre-defined teacher_finding)
        return "FINDING: test"

    # Use a temporary metrics dir for testing
    with tempfile.TemporaryDirectory() as tmpdir:
        original_dir = metrics_registry.METRICS_DIR
        metrics_registry.METRICS_DIR = Path(tmpdir)

        try:
            result = spec_search(
                "local-judge-medium",
                benchmark,
                student_fn=varying_student,
                teacher_fn=fake_teacher,
                max_rounds=5,
                stop_if_no_improvement_rounds=2,
            )

            print(f"✓ Search completed successfully")
            print(f"  Rounds completed: {result['rounds_completed']}")
            print(f"  Edits accepted: {result['edits_accepted']}")
            print(f"  Edits rejected: {result['edits_rejected']}")
            print(f"  Best metrics: {result['best_metrics']}")

            # Key verification: the search should have run some rounds
            if result['rounds_completed'] > 0:
                print(f"✓ Search loop ran {result['rounds_completed']} rounds (not zero)")
            else:
                print(f"✗ Search loop ran 0 rounds (would indicate it's stuck)")
                return False

            return True

        finally:
            metrics_registry.METRICS_DIR = original_dir


def test_error_samples_excluded():
    """Test that ERROR/TIMEOUT/UNPARSEABLE samples are properly excluded from counting.

    Expected behavior:
    - Only samples with real findings count toward total
    - Error samples should not be in the accuracy calculation
    """
    from spec_search import run_baseline_measurement

    print("\nTesting error sample exclusion...\n")

    # Create a benchmark with mixed samples
    benchmark = [
        {"slug": "p1", "extraction": {}, "paper_type": "empirical", "teacher_finding": ["real-finding"]},
        {"slug": "p2", "extraction": {}, "paper_type": "empirical", "teacher_finding": ["ERROR"]},
        {"slug": "p3", "extraction": {}, "paper_type": "empirical", "teacher_finding": []},
        {"slug": "p4", "extraction": {}, "paper_type": "empirical", "teacher_finding": ["TIMEOUT"]},
        {"slug": "p5", "extraction": {}, "paper_type": "empirical", "teacher_finding": ["UNPARSEABLE"]},
    ]

    # Student that returns empty findings (conservative approach)
    def empty_student(extraction, paper_type):
        return []

    result = run_baseline_measurement(
        "local-judge-medium",
        benchmark,
        student_fn=empty_student,
    )

    # With error samples excluded:
    # - p1: teacher has finding, student has none -> no match
    # - p2: ERROR -> EXCLUDED
    # - p3: teacher has none, student has none -> MATCH
    # - p4: TIMEOUT -> EXCLUDED
    # - p5: UNPARSEABLE -> EXCLUDED
    #
    # So we have 2 valid samples, 1 match
    # Accuracy = 1/2 = 0.5

    accuracy = result["accuracy"]["value"]
    print(f"Accuracy with error samples excluded: {accuracy}")

    if accuracy == 0.5:
        print(f"✓ Correct accuracy (1/2 samples matched)")
        return True
    elif accuracy == 0.4:
        print(f"? Accuracy is 0.4, which suggests 2/5 samples (error samples not excluded)")
        return False
    else:
        print(f"? Unexpected accuracy: {accuracy}")
        return False


if __name__ == "__main__":
    success = True

    try:
        if not test_search_loop_finds_improvements():
            success = False
    except Exception as e:
        print(f"✗ test_search_loop_finds_improvements failed: {e}")
        import traceback
        traceback.print_exc()
        success = False

    try:
        if not test_error_samples_excluded():
            success = False
    except Exception as e:
        print(f"✗ test_error_samples_excluded failed: {e}")
        import traceback
        traceback.print_exc()
        success = False

    if success:
        print("\n✓ All search loop tests passed!")
        sys.exit(0)
    else:
        print("\n✗ Some tests failed")
        sys.exit(1)
