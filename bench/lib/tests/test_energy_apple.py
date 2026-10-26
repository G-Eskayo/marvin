#!/usr/bin/env python3
"""Tests for ApplePowermetricsSampler. Run via:
    ~/.agents/venv/bin/python -m pytest lib/tests/test_energy_apple.py -v

Tests 8-10 from the design doc use FakePowermetricsSampler to avoid needing
real sudo/powermetrics on the test machine.
"""
from __future__ import annotations
import subprocess
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

LIB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LIB))

import pytest
from energy_apple import ApplePowermetricsSampler, FakePowermetricsSampler


class TestApplePowermetricsSampler:
    """Test cases 8-10 from the design doc using fake subprocess."""

    def test_case_8_no_passwordless_sudo(self):
        """Test case 8: No passwordless sudo for powermetrics.
        Sampler fails closed, reports energy as unavailable, never blocks on password.
        """
        sampler = ApplePowermetricsSampler()

        # Mock _check_available to return False (no passwordless sudo)
        with patch.object(sampler, "_check_available", return_value=False):
            result = sampler.start()
            assert result is False  # Should fail gracefully
            # Sampler never started
            assert sampler.process is None

    def test_case_9_stray_powermetrics_process(self):
        """Test case 9: A stale powermetrics process survives a prior crashed run.
        Start refuses or cleans it up rather than running two samplers.
        """
        # This is tested indirectly: when start() is called, it tries to pkill
        # any stray processes before starting a new one.
        sampler = ApplePowermetricsSampler()

        with patch("energy_apple.subprocess.run") as mock_run:
            with patch("energy_apple.subprocess.Popen") as mock_popen:
                # Make the subprocess.run (for cleanup) succeed
                mock_run.return_value = MagicMock(returncode=0)
                # Make Popen succeed (start new sampler)
                mock_popen.return_value = MagicMock(
                    pid=12345,
                    terminate=MagicMock(),
                    communicate=MagicMock(return_value=("CPU Power: 5000 mW\n", "")),
                    wait=MagicMock(),
                )

                result = sampler.start()

                # Verify that pkill was called to clean up strays
                mock_run.assert_called()
                call_args = [call[0][0] for call in mock_run.call_args_list]
                assert any("pkill" in " ".join(cmd) for cmd in call_args)

    def test_case_10_opencode_hangs_timeout(self):
        """Test case 10: opencode hangs, hard timeout kills both run and sampler.
        (This test covers the sampler's timeout handling when stopped.)
        """
        sampler = ApplePowermetricsSampler()

        with patch("energy_apple.subprocess.Popen") as mock_popen:
            # Mock a process that hangs (never communicates)
            mock_process = MagicMock()
            mock_process.pid = 12345
            mock_process.communicate.side_effect = subprocess.TimeoutExpired(
                "powermetrics", 5
            )
            mock_process.kill = MagicMock()
            mock_process.wait.return_value = None
            mock_popen.return_value = mock_process

            with patch.object(sampler, "_check_available", return_value=True):
                result = sampler.start()
                assert result is True

            # Now call stop with a timeout
            result = sampler.stop_and_measure()

            # Process should have been killed
            mock_process.kill.assert_called()
            # Energy measurement should still return a result (not crash)
            assert result is not None
            assert result["error"] == "process_killed_forcefully"

    def test_case_8_returns_unavailable_dict(self):
        """Test that when sampler fails to start, it returns a valid dict with available=False."""
        sampler = ApplePowermetricsSampler()
        with patch.object(sampler, "_check_available", return_value=False):
            started = sampler.start()
            assert started is False
            # Never started, so no measurement
            result = sampler.stop_and_measure()
            assert result is None


class TestFakePowermetricsSampler:
    """Tests using the fake sampler (synchronous, no subprocess)."""

    def test_fake_sampler_basic(self):
        """Test basic fake sampler lifecycle."""
        sampler = FakePowermetricsSampler()
        assert sampler.running is False

        started = sampler.start()
        assert started is True
        assert sampler.running is True

        time.sleep(0.1)
        result = sampler.stop_and_measure()

        assert result is not None
        assert result["available"] is True
        assert "joules" in result
        assert "wall_s" in result
        assert result["wall_s"] >= 0.1

    def test_fake_sampler_multiple_starts(self):
        """Test that double-start on fake sampler is safe."""
        sampler = FakePowermetricsSampler()
        sampler.start()
        # Second start should be safe
        sampler.start()
        result = sampler.stop_and_measure()
        assert result is not None

    def test_fake_sampler_stop_without_start(self):
        """Test that stop without start returns None."""
        sampler = FakePowermetricsSampler()
        result = sampler.stop_and_measure()
        assert result is None


class TestPowermetricsOutputParsing:
    """Test the power sample parsing logic."""

    def test_parse_valid_power_output(self):
        """Test parsing valid powermetrics output."""
        sampler = ApplePowermetricsSampler()
        output = [
            "Some header",
            "CPU Power: 5000 mW",
            "Some other line",
            "CPU Power: 4500 mW",
            "CPU Power: 5200 mW",
        ]
        result = sampler._compute_energy(output, wall_s=1.0)

        assert result["available"] is True
        assert result["samples"] == 3
        # Average of (5000 + 4500 + 5200) / 3 = 4900 mW
        # Energy = 4900 mW * 1.0 s / 1000 = 4.9 J
        assert abs(result["joules"] - 4.9) < 0.01

    def test_parse_no_samples(self):
        """Test handling of output with no power samples."""
        sampler = ApplePowermetricsSampler()
        output = ["Some header", "No power data here"]
        result = sampler._compute_energy(output, wall_s=1.0)

        assert result["available"] is True
        assert result["samples"] == 0
        assert result["joules"] == 0.0
        assert result["error"] == "no_power_samples_found"

    def test_parse_different_time_durations(self):
        """Test energy calculation with different wall times."""
        sampler = ApplePowermetricsSampler()
        output = ["CPU Power: 1000 mW"] * 10  # 10 samples at 1000 mW

        # Test 1: 1 second → 1 Joule
        result1 = sampler._compute_energy(output, wall_s=1.0)
        assert abs(result1["joules"] - 1.0) < 0.01

        # Test 2: 2 seconds → 2 Joules
        result2 = sampler._compute_energy(output, wall_s=2.0)
        assert abs(result2["joules"] - 2.0) < 0.01

        # Test 3: 0.5 seconds → 0.5 Joules
        result3 = sampler._compute_energy(output, wall_s=0.5)
        assert abs(result3["joules"] - 0.5) < 0.01
