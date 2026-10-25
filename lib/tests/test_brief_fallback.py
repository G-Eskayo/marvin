"""Tests for brief_fallback.py (ADR 0067): fallback digest generation on secondary machines."""
import json
import subprocess
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch, call
import pytest

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import brief_fallback


class TestPastDeadline:
    """Test 1-2: past_deadline(scheduled, now)"""

    def test_1_past_deadline_when_grace_period_elapsed(self):
        """Test 1: past_deadline returns True when grace period has elapsed."""
        scheduled = datetime(2026, 10, 24, 8, 30, 0, tzinfo=timezone.utc)
        now = datetime(2026, 10, 24, 9, 30, 1, tzinfo=timezone.utc)  # 1h 1s later
        assert brief_fallback.past_deadline(scheduled, now) is True

    def test_2_not_past_deadline_within_grace_period(self):
        """Test 2: past_deadline returns False when within grace period."""
        scheduled = datetime(2026, 10, 24, 8, 30, 0, tzinfo=timezone.utc)
        now = datetime(2026, 10, 24, 9, 29, 59, tzinfo=timezone.utc)  # 59m 59s later
        assert brief_fallback.past_deadline(scheduled, now) is False


class TestInferRemotePath:
    """Test 3: _infer_remote_path(local_path)"""

    def test_3_infer_remote_path_converts_to_home_relative(self):
        """Test 3: _infer_remote_path converts paths under home to $HOME-relative form."""
        local = Path.home() / ".claude" / "daily-digest" / "2026-10-24.md"
        remote = brief_fallback._infer_remote_path(local)
        # Should be $HOME-relative and shell-quoted
        assert "$HOME" in remote
        assert ".claude" in remote
        assert "2026-10-24.md" in remote


class TestReadRemote:
    """Test 4-6: read_remote(remote_path, host, run=subprocess.run)"""

    def test_4_read_remote_success(self):
        """Test 4: read_remote returns file contents on success."""
        mock_run = MagicMock()
        mock_run.return_value = MagicMock(returncode=0, stdout="file content\n")

        result = brief_fallback.read_remote("/path/to/file.md", "mac-mini", run=mock_run)
        assert result == "file content\n"
        mock_run.assert_called_once()

    def test_5_read_remote_returns_none_on_ssh_failure(self):
        """Test 5: read_remote returns None when SSH fails."""
        mock_run = MagicMock()
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="ssh: could not connect")

        result = brief_fallback.read_remote("/path/to/file.md", "mac-mini", run=mock_run)
        assert result is None

    def test_6_read_remote_handles_timeout(self):
        """Test 6: read_remote returns None on timeout."""
        def timeout_run(*args, **kwargs):
            raise TimeoutError()

        result = brief_fallback.read_remote("/path/to/file.md", "mac-mini", run=timeout_run)
        assert result is None


class TestIsReal:
    """Test 7-9: _is_real(text)"""

    def test_7_is_real_with_substantial_content(self):
        """Test 7: _is_real returns True for real content."""
        text = "# Morning Brief\n\nThis is real content with substance."
        assert brief_fallback._is_real(text) is True

    def test_8_is_real_rejects_error_messages(self):
        """Test 8: _is_real returns False for error messages."""
        assert brief_fallback._is_real("(could not read file)") is False
        assert brief_fallback._is_real("(claude call failed: timeout)") is False

    def test_9_is_real_rejects_empty_content(self):
        """Test 9: _is_real returns False for empty or None."""
        assert brief_fallback._is_real("") is False
        assert brief_fallback._is_real(None) is False
        assert brief_fallback._is_real("   ") is False
        assert brief_fallback._is_real("abc") is False  # too short


class TestProduced:
    """Test 10-14: produced(local_path, host=None, run=subprocess.run)"""

    def test_10_produced_locally_returns_true_if_file_exists_and_real(self, tmp_path):
        """Test 10: produced checks locally and returns True for real content."""
        file_path = tmp_path / "digest.md"
        file_path.write_text("# Digest\n\nReal content here, not an error.")

        assert brief_fallback.produced(file_path, host=None) is True

    def test_11_produced_locally_returns_false_if_missing(self, tmp_path):
        """Test 11: produced returns False if file doesn't exist."""
        file_path = tmp_path / "nonexistent.md"
        assert brief_fallback.produced(file_path, host=None) is False

    def test_12_produced_locally_returns_false_if_only_error(self, tmp_path):
        """Test 12: produced returns False if file contains only error message."""
        file_path = tmp_path / "digest.md"
        file_path.write_text("(claude call failed: timeout)")

        assert brief_fallback.produced(file_path, host=None) is False

    def test_13_produced_remote_success(self, tmp_path):
        """Test 13: produced checks remote and returns True if file is real."""
        mock_run = MagicMock()
        mock_run.return_value = MagicMock(returncode=0, stdout="# Real digest\n\nContent here.")

        file_path = tmp_path / "digest.md"
        result = brief_fallback.produced(file_path, host="mac-mini", run=mock_run)
        assert result is True

    def test_14_produced_remote_returns_false_if_unreachable(self, tmp_path):
        """Test 14: produced returns False if remote is unreachable."""
        mock_run = MagicMock()
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="ssh: timeout")

        file_path = tmp_path / "digest.md"
        result = brief_fallback.produced(file_path, host="mac-mini", run=mock_run)
        assert result is False


class TestPrimaryHost:
    """Test 15: primary_host()"""

    def test_15_primary_host_returns_tailscale_hostname(self):
        """Test 15: primary_host returns the tailscale_hostname of the primary device."""
        mock_devices = {
            "mac-mini": {"tailscale_hostname": "mac-mini-2012", "hardware_uuid": "aaa"},
            "macbook": {"tailscale_hostname": "macbook-pro-1", "hardware_uuid": "bbb"},
        }

        with patch.object(brief_fallback.machine_profile, "remote_devices", return_value=mock_devices):
            with patch.object(brief_fallback.scanner_role, "is_primary") as mock_is_primary:
                mock_is_primary.side_effect = lambda d: d == "mac-mini"

                result = brief_fallback.primary_host()
                assert result == "mac-mini-2012"


class TestShouldRun:
    """Test 16-22: should_run(job_name, scheduled, out_path, device_id=None, now=None, run=subprocess.run)"""

    def test_16_should_run_false_if_output_already_exists(self, tmp_path):
        """Test 16: should_run returns False (idempotency) if output already exists."""
        out_path = tmp_path / "digest.md"
        out_path.write_text("# Already produced\n\nReal content.")

        with patch.object(brief_fallback.scanner_role, "is_primary", return_value=True):
            result = brief_fallback.should_run(
                "daily-digest",
                "08:30",
                out_path,
                device_id="mac-mini",
                now=datetime(2026, 10, 24, 9, 0, 0, tzinfo=timezone.utc),
            )
            assert result is False

    def test_17_should_run_always_true_if_primary_and_output_missing(self, tmp_path):
        """Test 17: should_run returns True if this device is primary and output missing."""
        out_path = tmp_path / "digest.md"

        with patch.object(brief_fallback.scanner_role, "is_primary", return_value=True):
            result = brief_fallback.should_run(
                "daily-digest",
                "08:30",
                out_path,
                device_id="mac-mini",
                now=datetime(2026, 10, 24, 9, 0, 0, tzinfo=timezone.utc),
            )
            assert result is True

    def test_18_should_run_false_if_secondary_and_primary_has_produced(self, tmp_path):
        """Test 18: should_run returns False if secondary and primary has output."""
        out_path = tmp_path / "digest.md"

        mock_run = MagicMock()

        with patch.object(brief_fallback.scanner_role, "is_primary", return_value=False):
            with patch.object(brief_fallback, "primary_host", return_value="mac-mini"):
                # Mock produced to return False for local check, True for remote check
                call_count = [0]
                def produced_side_effect(path, host=None, run=subprocess.run):
                    call_count[0] += 1
                    if host is None:
                        return False  # Local file doesn't exist
                    return True  # Remote file exists

                with patch.object(brief_fallback, "produced", side_effect=produced_side_effect):
                    result = brief_fallback.should_run(
                        "daily-digest",
                        "08:30",
                        out_path,
                        device_id="macbook",
                        now=datetime(2026, 10, 24, 9, 15, 0, tzinfo=timezone.utc),
                        run=mock_run,
                    )
                    assert result is False

    def test_19_should_run_true_if_secondary_and_grace_expired_and_primary_has_not_produced(self, tmp_path):
        """Test 19: should_run returns True if secondary, grace expired, and primary hasn't produced."""
        out_path = tmp_path / "digest.md"

        mock_run = MagicMock()

        with patch.object(brief_fallback.scanner_role, "is_primary", return_value=False):
            with patch.object(brief_fallback, "primary_host", return_value="mac-mini"):
                with patch.object(brief_fallback, "produced", return_value=False):
                    result = brief_fallback.should_run(
                        "daily-digest",
                        "08:30",
                        out_path,
                        device_id="macbook",
                        now=datetime(2026, 10, 24, 9, 31, 0, tzinfo=timezone.utc),
                        run=mock_run,
                    )
                    assert result is True

    def test_20_should_run_false_if_secondary_within_grace_period(self, tmp_path):
        """Test 20: should_run returns False if secondary within grace period."""
        out_path = tmp_path / "digest.md"

        mock_run = MagicMock()

        with patch.object(brief_fallback.scanner_role, "is_primary", return_value=False):
            with patch.object(brief_fallback, "primary_host", return_value="mac-mini"):
                with patch.object(brief_fallback, "produced", return_value=False):
                    result = brief_fallback.should_run(
                        "daily-digest",
                        "08:30",
                        out_path,
                        device_id="macbook",
                        now=datetime(2026, 10, 24, 9, 15, 0, tzinfo=timezone.utc),  # 45m after scheduled
                        run=mock_run,
                    )
                    assert result is False

    def test_21_should_run_fail_open_if_no_primary_found(self, tmp_path):
        """Test 21: should_run returns True (fail open) if primary cannot be determined."""
        out_path = tmp_path / "digest.md"

        mock_run = MagicMock()

        with patch.object(brief_fallback.scanner_role, "is_primary", return_value=False):
            with patch.object(brief_fallback, "primary_host", return_value=None):
                with patch.object(brief_fallback, "produced", return_value=False):
                    result = brief_fallback.should_run(
                        "daily-digest",
                        "08:30",
                        out_path,
                        device_id="macbook",
                        now=datetime(2026, 10, 24, 9, 15, 0, tzinfo=timezone.utc),
                        run=mock_run,
                    )
                    assert result is True

    def test_22_should_run_handles_malformed_scheduled_time(self, tmp_path):
        """Test 22: should_run fails open for malformed scheduled time."""
        out_path = tmp_path / "digest.md"

        mock_run = MagicMock()

        with patch.object(brief_fallback.scanner_role, "is_primary", return_value=False):
            with patch.object(brief_fallback, "primary_host", return_value="mac-mini"):
                with patch.object(brief_fallback, "produced", return_value=False):
                    result = brief_fallback.should_run(
                        "daily-digest",
                        "not-a-time",
                        out_path,
                        device_id="macbook",
                        now=datetime(2026, 10, 24, 9, 15, 0, tzinfo=timezone.utc),
                        run=mock_run,
                    )
                    assert result is True  # fail open
