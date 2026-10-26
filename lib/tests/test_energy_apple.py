"""Tests for energy_apple.py. Run via:
    ~/.agents/venv/bin/python -m pytest lib/tests/test_energy_apple.py -v
"""
from __future__ import annotations
import json
import subprocess
import sys
from pathlib import Path
from unittest import mock

import pytest

LIB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LIB))

import energy_apple as ea  # noqa: E402


class TestEnergySamplerNoSudo:
    """Regression test for the no-sudo-available path returning promptly."""

    def test_no_sudo_available_returns_none_immediately(self):
        """When `sudo -n true` fails, energy_apple returns None without invoking powermetrics."""
        with mock.patch("subprocess.run") as mock_run:
            # sudo -n true fails (no passwordless sudo configured)
            mock_run.return_value = subprocess.CompletedProcess(["sudo", "-n", "true"], returncode=1)

            sampler = ea.PowerSampler()
            sampler.start()
            sampler.stop()

            # Only one call: the sudo -n true probe
            assert mock_run.call_count == 1
            call_cmd = mock_run.call_args_list[0][0][0]
            assert "sudo" in call_cmd and "-n" in call_cmd and "true" in call_cmd

            result = sampler.joules()
            assert result is None

    def test_no_sudo_returns_none(self):
        """When passwordless sudo is unavailable, joules() returns None."""
        with mock.patch("subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(["sudo", "-n", "true"], returncode=1)

            sampler = ea.PowerSampler()
            sampler.start()
            sampler.stop()

            assert sampler.joules() is None

    def test_sudo_probe_timeout_returns_false(self):
        """When sudo -n true times out, has_sudo becomes False."""
        with mock.patch("subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.TimeoutExpired(["sudo"], 2)

            sampler = ea.PowerSampler()
            sampler.start()

            assert sampler.has_sudo is False
            assert sampler.error is not None


class TestEnergyMissingBinary:
    """Missing powermetrics binary path."""

    def test_missing_powermetrics_binary(self):
        """When powermetrics binary doesn't exist, sampler handles gracefully."""
        with mock.patch("subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(["sudo", "-n", "true"], returncode=0)

            with mock.patch("subprocess.Popen") as mock_popen:
                mock_popen.side_effect = FileNotFoundError("powermetrics not found")

                sampler = ea.PowerSampler()
                sampler.start()
                sampler.stop()

                result = sampler.joules()
                # Should return None with an error set
                assert result is None
                assert sampler.error is not None
                assert "powermetrics" in sampler.error.lower()


class TestEnergyMalformedOutput:
    """Malformed powermetrics output (truncated, non-numeric)."""

    def test_malformed_powermetrics_output(self):
        """Malformed plist output doesn't crash the integrator."""
        with mock.patch("subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(["sudo", "-n", "true"], returncode=0)

            with mock.patch("subprocess.Popen") as mock_popen:
                # Malformed plist output
                mock_proc = mock.MagicMock()
                mock_proc.communicate.return_value = (b"<invalid plist>", b"")
                mock_proc.returncode = 0
                mock_popen.return_value = mock_proc

                sampler = ea.PowerSampler()
                sampler.start()
                sampler.stop()

                result = sampler.joules()
                # Should handle gracefully, not crash
                assert result is None

    def test_empty_powermetrics_output(self):
        """Empty powermetrics output returns None."""
        with mock.patch("subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(["sudo", "-n", "true"], returncode=0)

            with mock.patch("subprocess.Popen") as mock_popen:
                mock_proc = mock.MagicMock()
                mock_proc.communicate.return_value = (b"", b"")
                mock_proc.returncode = 0
                mock_popen.return_value = mock_proc

                sampler = ea.PowerSampler()
                sampler.start()
                sampler.stop()

                result = sampler.joules()
                assert result is None

    def test_valid_plist_with_power_data(self):
        """Valid plist with power data is parsed and integrated."""
        import plistlib

        with mock.patch("subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(["sudo", "-n", "true"], returncode=0)

            with mock.patch("subprocess.Popen") as mock_popen:
                # Create valid plist with power data
                sample1 = {"cpu_power": 10.0, "gpu_power": 5.0, "ane_power": 1.0}
                sample2 = {"cpu_power": 12.0, "gpu_power": 4.0, "ane_power": 0.5}
                plist1 = plistlib.dumps(sample1)
                plist2 = plistlib.dumps(sample2)
                output = plist1 + b"\x00" + plist2

                mock_proc = mock.MagicMock()
                mock_proc.communicate.return_value = (output, b"")
                mock_proc.returncode = 0
                mock_popen.return_value = mock_proc

                sampler = ea.PowerSampler()
                with mock.patch("time.time") as mock_time:
                    mock_time.side_effect = [100.0, 102.0]  # 2 seconds
                    sampler.start()
                    sampler.stop()

                result = sampler.joules()
                # Average power: (16 + 16.5) / 2 = 16.25 W over 2 s = 32.5 J
                assert result is not None
                assert isinstance(result, float)
                assert result > 0


class TestEnergyIntegration:
    """Integration test when real passwordless sudo is available (skipped if not)."""

    def test_real_sudo_available_smoke_test(self):
        """Smoke test: when passwordless sudo IS available, sampler runs without error.

        Skipped if passwordless sudo isn't configured; not a mock test, but
        verifies the real path works when preconditions are met.
        """
        try:
            result = subprocess.run(["sudo", "-n", "true"], capture_output=True, timeout=5)
            if result.returncode != 0:
                pytest.skip("passwordless sudo not configured")
        except Exception:
            pytest.skip("passwordless sudo not available or timed out")

        # Real sampler: start, do nothing, stop, check joules
        sampler = ea.PowerSampler()
        sampler.start()
        import time
        time.sleep(0.1)  # Let powermetrics collect a few samples
        sampler.stop()
        result = sampler.joules()

        # Should either return None (no data due to short duration) or a float (>= 0)
        assert result is None or (isinstance(result, float) and result >= 0)


class TestEnergyContextManager:
    """Test PowerSampler as context manager."""

    def test_sampler_context_manager(self):
        """PowerSampler can be used as a context manager."""
        with mock.patch("subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(["sudo", "-n", "true"], returncode=1)

            with ea.PowerSampler() as sampler:
                assert sampler is not None
                # Sampler started
                assert sampler.t0 is not None

            # After __exit__, should have called stop
            assert sampler.t1 is not None
            result = sampler.joules()
            assert result is None


class TestEnergyProbeTimeout:
    """The sudo -n true probe must be fast and never block."""

    def test_sudo_probe_has_timeout(self):
        """The sudo -n true probe includes a timeout to prevent hangs."""
        with mock.patch("subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(["sudo", "-n", "true"], returncode=0)

            sampler = ea.PowerSampler()
            sampler.start()

            # Verify that subprocess.run was called with a timeout for the probe
            call_args = mock_run.call_args_list[0]
            assert "timeout" in call_args[1], "sudo -n true probe must have a timeout"
            assert call_args[1]["timeout"] < 5, "sudo -n true probe timeout should be < 5s"
