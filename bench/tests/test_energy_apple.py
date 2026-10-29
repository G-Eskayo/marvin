"""Tests for energy_apple.py — powermetrics sampling for Apple Silicon.
~/.agents/venv/bin/python -m pytest bench/tests/test_energy_apple.py -v
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

BENCH = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BENCH / "lib"))

import energy_apple as ea


class TestEnergyAppleSampling:
    def test_start_sampling_returns_none_if_powermetrics_missing(self):
        """Test that start_sampling returns None if powermetrics not found."""
        with patch("shutil.which", return_value=None):
            result = ea.start_sampling()
            assert result is None

    def test_start_sampling_returns_none_if_no_sudo(self):
        """Test that start_sampling returns None if sudo fails."""
        with patch("shutil.which", return_value="/usr/bin/powermetrics"):
            with patch("subprocess.Popen", side_effect=PermissionError("sudo required")):
                result = ea.start_sampling()
                assert result is None

    def test_start_sampling_returns_handle_with_process_and_time(self):
        """Test that start_sampling returns handle dict with process and time."""
        mock_popen = MagicMock()
        with patch("shutil.which", return_value="/usr/bin/powermetrics"):
            with patch("subprocess.Popen", return_value=mock_popen):
                handle = ea.start_sampling()

                assert handle is not None
                assert "process" in handle
                assert handle["process"] is mock_popen
                assert "start_time" in handle

    def test_start_sampling_uses_sudo_with_noninteractive_flag(self):
        """Test that start_sampling uses -n flag to prevent password prompt."""
        mock_popen = MagicMock()
        with patch("shutil.which", return_value="/usr/bin/powermetrics"):
            with patch("subprocess.Popen", return_value=mock_popen) as mock_popen_call:
                ea.start_sampling()

                # Verify -n flag was passed to sudo
                call_args = mock_popen_call.call_args
                cmd = call_args[0][0]
                assert "sudo" in cmd
                assert "-n" in cmd  # non-interactive flag

    def test_stop_sampling_returns_none_if_no_handle(self):
        """Test that stop_sampling returns None if handle is None."""
        result = ea.stop_sampling(None)
        assert result is None

    def test_stop_sampling_parses_cpu_and_gpu_power(self):
        """Test that stop_sampling parses CPU and GPU power lines."""
        mock_proc = MagicMock()
        mock_proc.communicate.return_value = (
            "CPU Power: 10.5 W\nGPU Power: 5.2 W\nSample: 1\n",
            ""
        )

        handle = {
            "process": mock_proc,
            "start_time": 0.0,
        }

        with patch("time.time", return_value=5.0):
            result = ea.stop_sampling(handle)

        # Should extract and integrate power
        assert result is not None
        assert "joules" in result
        assert result["joules"] > 0
        assert result["samples"] == 1

    def test_stop_sampling_parses_milliwatts(self):
        """Test that stop_sampling parses milliwatts (mW) and converts to watts."""
        mock_proc = MagicMock()
        # Real Apple Silicon output in milliwatts
        mock_proc.communicate.return_value = (
            "CPU Power: 5234 mW\nGPU Power: 145 mW\n",
            ""
        )

        handle = {
            "process": mock_proc,
            "start_time": 0.0,
        }

        with patch("time.time", return_value=2.0):
            result = ea.stop_sampling(handle)

        assert result is not None
        # 5234 mW = 5.234 W, 145 mW = 0.145 W
        # Total: (5.234 + 0.145) * 2 = 10.758 J
        assert result["joules"] > 10
        assert result["avg_cpu_power_w"] > 5
        assert result["avg_gpu_power_w"] < 1

    def test_stop_sampling_handles_mixed_units(self):
        """Test that stop_sampling handles both W and mW in same output."""
        mock_proc = MagicMock()
        # Mixed units (though unusual, should handle gracefully)
        mock_proc.communicate.return_value = (
            "CPU Power: 5234 mW\nGPU Power: 0.2 W\n",
            ""
        )

        handle = {
            "process": mock_proc,
            "start_time": 0.0,
        }

        with patch("time.time", return_value=1.0):
            result = ea.stop_sampling(handle)

        assert result is not None
        # Both should be converted to watts
        assert result["avg_cpu_power_w"] > 5
        assert result["avg_gpu_power_w"] > 0

    def test_stop_sampling_returns_none_on_parse_error(self):
        """Test that stop_sampling returns None if no power samples found."""
        mock_proc = MagicMock()
        mock_proc.communicate.return_value = ("invalid output with no power data", "")

        handle = {
            "process": mock_proc,
            "start_time": 0.0,
        }

        with patch("time.time", return_value=5.0):
            result = ea.stop_sampling(handle)
            assert result is None

    def test_stop_sampling_terminates_process_on_timeout(self):
        """Test that stop_sampling terminates the process if timeout occurs."""
        mock_proc = MagicMock()
        mock_proc.communicate.side_effect = subprocess.TimeoutExpired("cmd", 5)

        handle = {
            "process": mock_proc,
            "start_time": 0.0,
        }

        result = ea.stop_sampling(handle)

        # Process should be terminated
        mock_proc.terminate.assert_called_once()
        # Should return None
        assert result is None

    def test_stop_sampling_integrates_power_over_time(self):
        """Test that energy (joules) = avg power (W) * elapsed time (s)."""
        mock_proc = MagicMock()
        # 10W CPU + 5W GPU = 15W average, over 2 seconds = 30J
        mock_proc.communicate.return_value = (
            "CPU Power: 10.0 W\nGPU Power: 5.0 W\n",
            ""
        )

        handle = {
            "process": mock_proc,
            "start_time": 0.0,
        }

        with patch("time.time", return_value=2.0):
            result = ea.stop_sampling(handle)

        assert result is not None
        # Energy = (10 + 5) W * 2 s = 30 J
        assert result["joules"] == 30.0

    def test_stop_sampling_handles_multiple_samples(self):
        """Test that stop_sampling averages multiple power samples."""
        mock_proc = MagicMock()
        # Multiple samples: average them
        mock_proc.communicate.return_value = (
            "CPU Power: 10.0 W\nGPU Power: 5.0 W\nCPU Power: 12.0 W\nGPU Power: 3.0 W\n",
            ""
        )

        handle = {
            "process": mock_proc,
            "start_time": 0.0,
        }

        with patch("time.time", return_value=1.0):
            result = ea.stop_sampling(handle)

        assert result is not None
        assert "samples" in result
        # Should have 2 CPU + 2 GPU samples
        assert result["samples"] >= 2

    def test_stop_sampling_returns_dict_with_all_fields(self):
        """Test that stop_sampling result has all expected fields."""
        mock_proc = MagicMock()
        mock_proc.communicate.return_value = (
            "CPU Power: 5.0 W\nGPU Power: 2.0 W\n",
            ""
        )

        handle = {
            "process": mock_proc,
            "start_time": 0.0,
        }

        with patch("time.time", return_value=1.0):
            result = ea.stop_sampling(handle)

        assert result is not None
        assert "joules" in result
        assert "samples" in result
        assert "elapsed_s" in result
        assert "avg_cpu_power_w" in result
        assert "avg_gpu_power_w" in result
