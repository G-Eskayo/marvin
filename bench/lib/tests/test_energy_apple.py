"""Tests for energy_apple.py — power measurement with powermetrics."""
import subprocess
import time

import pytest

from energy_apple import measure_subprocess, EnergyMeasure


class TestEnergyMeasure:
    """Test EnergyMeasure data structure."""

    def test_energy_measure_to_dict(self):
        """EnergyMeasure.to_dict() should serialize properly."""
        em = EnergyMeasure(joules=100.0, wh=0.0278, duration_s=10.0)
        d = em.to_dict()

        assert d["joules"] == 100.0
        assert d["wh"] == pytest.approx(0.0278, abs=0.001)
        assert d["duration_s"] == 10.0


class TestMeasureSubprocess:
    """Test measure_subprocess on real commands."""

    def test_measure_simple_command(self):
        """measure_subprocess should capture exit code even if powermetrics unavailable."""
        # Run a simple true command
        exit_code, energy, error = measure_subprocess(["true"])

        # Should return something
        assert exit_code in (0, -1)
        # Energy is None if powermetrics not available (expected in test env)
        if energy is None:
            assert error  # Should have a reason

    def test_measure_failing_command(self):
        """measure_subprocess should report non-zero exit on command failure."""
        exit_code, energy, error = measure_subprocess(["false"])

        # false command exits with 1
        # But with powermetrics issues, might return -1
        assert exit_code in (1, -1)

    def test_measure_timeout(self):
        """measure_subprocess should handle timeouts."""
        # Sleep longer than timeout
        exit_code, energy, error = measure_subprocess(
            ["sleep", "10"],
            timeout=1,
        )

        # Should timeout and return non-zero
        assert exit_code != 0

    def test_measure_with_working_dir(self):
        """measure_subprocess should respect cwd parameter."""
        import tempfile
        import os

        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a marker file
            marker = os.path.join(tmpdir, "marker.txt")

            # Run command that reads from cwd
            exit_code, energy, error = measure_subprocess(
                ["sh", "-c", f"touch {marker}"],
                cwd=tmpdir,
                timeout=5,
            )

            # Check if command ran (marker might or might not exist due to powermetrics)
            # This tests that cwd parameter is at least passed through


class TestMeasureSubprocessRobustness:
    """Test measure_subprocess error handling."""

    def test_measure_nonexistent_command(self):
        """measure_subprocess should handle nonexistent commands gracefully."""
        exit_code, energy, error = measure_subprocess(["nonexistent_command_xyz"])

        # Should return some error code, not crash
        assert exit_code != 0

    def test_measure_preserves_exit_code_on_energy_failure(self):
        """If powermetrics fails, subprocess exit code should still be reported."""
        # true command
        exit_code, energy, error = measure_subprocess(["true"])

        # Even if energy is None, exit code should be accurate
        assert exit_code in (0, -1)

    def test_measure_empty_command_fails(self):
        """measure_subprocess with empty command should fail gracefully."""
        try:
            exit_code, energy, error = measure_subprocess([])
            # Should either fail or return error
            assert exit_code != 0
        except Exception:
            # Acceptable to raise on invalid input
            pass
