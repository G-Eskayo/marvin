"""Tests for metrics_registry.py — gate verdict on build metrics."""
import pytest

from build_type_measure import BuildMeasure
from metrics_registry import compare, GateVerdict


class TestMetricsComparison:
    """Test compare() gate verdict logic."""

    def test_compare_identical_metrics_passes(self):
        """compare() should pass if metrics are identical."""
        baseline = BuildMeasure(
            type_check_pass=True,
            type_check_errors=0,
            lint_pass=True,
            lint_warnings=0,
            tests_pass=True,
            tests_failed=0,
            wall_s=10.0,
        )
        after = baseline

        verdict = compare(baseline, after)

        assert isinstance(verdict, GateVerdict)
        assert verdict.passed
        assert "All checks passed" in verdict.reason

    def test_compare_type_check_regression(self):
        """compare() should fail if type check errors increase."""
        baseline = BuildMeasure(
            type_check_pass=True,
            type_check_errors=0,
            lint_pass=True,
            lint_warnings=0,
            tests_pass=True,
            tests_failed=0,
            wall_s=10.0,
        )
        after = BuildMeasure(
            type_check_pass=False,
            type_check_errors=2,  # Increased!
            lint_pass=True,
            lint_warnings=0,
            tests_pass=True,
            tests_failed=0,
            wall_s=11.0,
        )

        verdict = compare(baseline, after)

        assert not verdict.passed
        assert "Type check errors increased" in verdict.reason

    def test_compare_lint_regression(self):
        """compare() should flag significant lint warning increases."""
        baseline = BuildMeasure(
            type_check_pass=True,
            type_check_errors=0,
            lint_pass=True,
            lint_warnings=10,
            tests_pass=True,
            tests_failed=0,
            wall_s=10.0,
        )
        after = BuildMeasure(
            type_check_pass=True,
            type_check_errors=0,
            lint_pass=True,
            lint_warnings=50,  # Significantly increased
            tests_pass=True,
            tests_failed=0,
            wall_s=11.0,
        )

        verdict = compare(baseline, after)

        assert not verdict.passed
        assert "Lint warnings increased" in verdict.reason

    def test_compare_lint_small_increase_allowed(self):
        """compare() should allow small (+5%) lint warning increases."""
        baseline = BuildMeasure(
            type_check_pass=True,
            type_check_errors=0,
            lint_pass=True,
            lint_warnings=100,
            tests_pass=True,
            tests_failed=0,
            wall_s=10.0,
        )
        after = BuildMeasure(
            type_check_pass=True,
            type_check_errors=0,
            lint_pass=True,
            lint_warnings=105,  # +5%, within threshold
            tests_pass=True,
            tests_failed=0,
            wall_s=11.0,
        )

        verdict = compare(baseline, after)

        assert verdict.passed

    def test_compare_test_regression(self):
        """compare() should fail if tests regress."""
        baseline = BuildMeasure(
            type_check_pass=True,
            type_check_errors=0,
            lint_pass=True,
            lint_warnings=0,
            tests_pass=True,
            tests_failed=0,
            wall_s=10.0,
        )
        after = BuildMeasure(
            type_check_pass=True,
            type_check_errors=0,
            lint_pass=True,
            lint_warnings=0,
            tests_pass=False,  # Tests failed!
            tests_failed=3,
            wall_s=11.0,
        )

        verdict = compare(baseline, after)

        assert not verdict.passed
        assert "Tests regressed" in verdict.reason

    def test_compare_improvement_passes(self):
        """compare() should pass if metrics improve."""
        baseline = BuildMeasure(
            type_check_pass=True,
            type_check_errors=2,
            lint_pass=True,
            lint_warnings=10,
            tests_pass=True,
            tests_failed=0,
            wall_s=10.0,
        )
        after = BuildMeasure(
            type_check_pass=True,
            type_check_errors=0,  # Improved!
            lint_pass=True,
            lint_warnings=5,  # Improved!
            tests_pass=True,
            tests_failed=0,
            wall_s=9.0,
        )

        verdict = compare(baseline, after)

        assert verdict.passed

    def test_compare_multiple_failures(self):
        """compare() should report all failures."""
        baseline = BuildMeasure(
            type_check_pass=True,
            type_check_errors=0,
            lint_pass=True,
            lint_warnings=0,
            tests_pass=True,
            tests_failed=0,
            wall_s=10.0,
        )
        after = BuildMeasure(
            type_check_pass=False,
            type_check_errors=1,  # Type check error
            lint_pass=True,
            lint_warnings=50,  # Lint warnings
            tests_pass=False,  # Tests fail
            tests_failed=2,
            wall_s=11.0,
        )

        verdict = compare(baseline, after)

        assert not verdict.passed
        # Should mention all failures
        assert "Type check errors" in verdict.reason or "Build type check" in verdict.reason
        assert "Lint warnings" in verdict.reason or "lint" in verdict.reason.lower()
        assert "Tests" in verdict.reason
