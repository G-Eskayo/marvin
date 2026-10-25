"""Tests for machine_profile.py functions."""
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock
import subprocess

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import machine_profile  # noqa: E402


class TestSshCat:
    """Tests for ssh_cat() function."""

    def test_ssh_cat_success(self):
        """ssh_cat returns file contents on success."""
        file_content = "line 1\nline 2\n"
        with patch("subprocess.run") as run_mock:
            proc_mock = MagicMock()
            proc_mock.returncode = 0
            proc_mock.stdout = file_content
            run_mock.return_value = proc_mock

            result = machine_profile.ssh_cat("example.com", "/home/user/file.txt")
            assert result == file_content
            run_mock.assert_called_once()
            call_args = run_mock.call_args
            assert call_args[1]["timeout"] == 10

    def test_ssh_cat_non_zero_exit(self):
        """ssh_cat returns None on non-zero exit code."""
        with patch("subprocess.run") as run_mock:
            proc_mock = MagicMock()
            proc_mock.returncode = 1
            run_mock.return_value = proc_mock

            result = machine_profile.ssh_cat("example.com", "/home/user/file.txt")
            assert result is None

    def test_ssh_cat_timeout(self):
        """ssh_cat returns None on subprocess timeout."""
        with patch("subprocess.run") as run_mock:
            run_mock.side_effect = subprocess.TimeoutExpired("ssh", 10)

            result = machine_profile.ssh_cat("example.com", "/home/user/file.txt")
            assert result is None

    def test_ssh_cat_exception(self):
        """ssh_cat returns None on any exception."""
        with patch("subprocess.run") as run_mock:
            run_mock.side_effect = OSError("Connection refused")

            result = machine_profile.ssh_cat("example.com", "/home/user/file.txt")
            assert result is None

    def test_ssh_cat_custom_timeout(self):
        """ssh_cat respects custom timeout parameter."""
        with patch("subprocess.run") as run_mock:
            proc_mock = MagicMock()
            proc_mock.returncode = 0
            proc_mock.stdout = "content"
            run_mock.return_value = proc_mock

            machine_profile.ssh_cat("example.com", "/path", timeout=30)
            call_args = run_mock.call_args
            assert call_args[1]["timeout"] == 30

    def test_ssh_cat_calls_ssh_with_correct_args(self):
        """ssh_cat constructs proper SSH command."""
        with patch("subprocess.run") as run_mock:
            proc_mock = MagicMock()
            proc_mock.returncode = 0
            proc_mock.stdout = "content"
            run_mock.return_value = proc_mock

            machine_profile.ssh_cat("host.com", "/remote/path")
            call_args = run_mock.call_args[0][0]
            # Check that it's an ssh command with the correct host and path
            assert "ssh" in call_args
            assert "host.com" in call_args
            assert "cat /remote/path" in " ".join(call_args)


class TestIsStationary:
    """Tests for is_stationary() function."""

    def test_is_stationary_true_for_stationary(self):
        """is_stationary returns True when mobility_class is 'stationary'."""
        mock_profile = {
            "mobility_class": "stationary",
            "label": "mac-mini",
        }
        with patch("machine_profile.load_or_build", return_value=mock_profile):
            assert machine_profile.is_stationary() is True

    def test_is_stationary_false_for_mobile(self):
        """is_stationary returns False when mobility_class is 'mobile'."""
        mock_profile = {
            "mobility_class": "mobile",
            "label": "macbook-pro",
        }
        with patch("machine_profile.load_or_build", return_value=mock_profile):
            assert machine_profile.is_stationary() is False

    def test_is_stationary_false_when_missing_mobility_class(self):
        """is_stationary returns False when mobility_class is missing."""
        mock_profile = {
            "label": "unknown-machine",
        }
        with patch("machine_profile.load_or_build", return_value=mock_profile):
            assert machine_profile.is_stationary() is False

    def test_is_stationary_false_for_unknown_value(self):
        """is_stationary returns False for any value other than 'stationary'."""
        mock_profile = {
            "mobility_class": "unknown",
        }
        with patch("machine_profile.load_or_build", return_value=mock_profile):
            assert machine_profile.is_stationary() is False
