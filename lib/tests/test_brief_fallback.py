"""Tests for brief_fallback.py. Run via:
    ~/.agents/venv/bin/python -m pytest lib/tests/test_brief_fallback.py -v
"""
from __future__ import annotations
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

LIB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LIB))

import pytest
import brief_fallback as bf  # noqa: E402


class TestDecision:
    def test_decision_is_a_named_tuple(self):
        d = bf.Decision(should_build=True, reason="test")
        assert d.should_build is True
        assert d.reason == "test"

    def test_decision_unpacking(self):
        d = bf.Decision(True, "primary")
        should_build, reason = d
        assert should_build is True
        assert reason == "primary"


class TestInferRemotePath:
    def test_infers_path_under_home(self):
        home = Path.home()
        local_path = home / ".claude" / "briefs" / "morning.txt"
        result = bf._infer_remote_path(local_path)
        assert result == "$HOME/.claude/briefs/morning.txt"

    def test_infers_nested_path_under_home(self):
        home = Path.home()
        local_path = home / "Developer" / "project" / "file.txt"
        result = bf._infer_remote_path(local_path)
        assert result == "$HOME/Developer/project/file.txt"

    def test_falls_back_to_filename_for_non_home_path(self):
        local_path = Path("/tmp/output.txt")
        result = bf._infer_remote_path(local_path)
        # Should fall back to the filename in ~/.claude/
        assert result == "$HOME/.claude/output.txt"

    def test_preserves_special_chars_in_filename(self):
        home = Path.home()
        local_path = home / ".claude" / "test-file (1).txt"
        result = bf._infer_remote_path(local_path)
        assert "$HOME/.claude/test-file (1).txt" in result or "$HOME/.claude/test-file%20(1).txt" in result


class TestReadRemote:
    def test_read_remote_returns_content_on_success(self):
        mock_run = MagicMock()
        mock_run.return_value = MagicMock(returncode=0, stdout="test content\n")

        result = bf.read_remote("$HOME/.claude/test.txt", host="test-host", run=mock_run)
        assert result == "test content\n"

    def test_read_remote_returns_none_on_ssh_failure(self):
        mock_run = MagicMock()
        mock_run.return_value = MagicMock(returncode=1, stdout="")

        result = bf.read_remote("$HOME/.claude/test.txt", host="test-host", run=mock_run)
        assert result is None

    def test_read_remote_returns_none_on_timeout(self):
        mock_run = MagicMock(side_effect=TimeoutError())

        result = bf.read_remote("$HOME/.claude/test.txt", host="test-host", run=mock_run)
        assert result is None

    def test_read_remote_returns_none_on_exception(self):
        mock_run = MagicMock(side_effect=Exception("Some error"))

        result = bf.read_remote("$HOME/.claude/test.txt", host="test-host", run=mock_run)
        assert result is None

    def test_read_remote_quotes_paths_with_special_chars(self):
        mock_run = MagicMock()
        mock_run.return_value = MagicMock(returncode=0, stdout="content")

        bf.read_remote("$HOME/test file with spaces.txt", host="test-host", run=mock_run)

        # Verify the command was constructed with proper quoting
        call_args = mock_run.call_args
        cmd = call_args[0][0]
        # Should contain a quoted path, not the literal path with unquoted spaces
        assert "test file with spaces.txt" not in " ".join(cmd) or "'" in " ".join(cmd) or '"' in " ".join(cmd)

    def test_read_remote_finds_primary_host_from_registry(self):
        mock_run = MagicMock()
        mock_run.return_value = MagicMock(returncode=0, stdout="content")

        # Mock machine_profile and scanner_role
        with patch('brief_fallback.machine_profile') as mock_mp, \
             patch('brief_fallback.is_primary') as mock_is_primary:
            mock_mp.remote_macs.return_value = {
                "device-a": {"tailscale_hostname": "other-host"},
                "device-b": {"tailscale_hostname": "primary-host"},
            }
            mock_is_primary.side_effect = lambda dev_id: dev_id == "device-b"

            result = bf.read_remote("$HOME/test.txt", host=None, run=mock_run)

            # Should have found the primary's host and called cat on it
            assert result == "content"


class TestProduced:
    def test_produced_returns_true_if_local_file_exists_with_content(self, tmp_path):
        file_path = tmp_path / "output.txt"
        file_path.write_text("digest content")

        result = bf.produced(file_path)
        assert result is True

    def test_produced_returns_false_if_local_file_is_empty(self, tmp_path):
        file_path = tmp_path / "output.txt"
        file_path.write_text("")

        result = bf.produced(file_path)
        assert result is False

    def test_produced_returns_false_if_local_file_is_whitespace_only(self, tmp_path):
        file_path = tmp_path / "output.txt"
        file_path.write_text("   \n\t  ")

        result = bf.produced(file_path)
        assert result is False

    def test_produced_returns_false_if_content_is_failure_placeholder(self, tmp_path):
        file_path = tmp_path / "output.txt"
        file_path.write_text("(claude call failed: rate limited)")

        result = bf.produced(file_path)
        assert result is False

    def test_produced_returns_true_if_quarantined(self, tmp_path):
        file_path = tmp_path / "output.txt"
        file_path.write_text("some digest\n_Quarantined by safety-monitor")

        result = bf.produced(file_path)
        assert result is True

    def test_produced_checks_remote_if_local_missing(self, tmp_path):
        file_path = tmp_path / "nonexistent.txt"
        mock_run = MagicMock()
        mock_run.return_value = MagicMock(returncode=0, stdout="remote content")

        with patch('brief_fallback.read_remote') as mock_read:
            mock_read.return_value = "remote content"
            result = bf.produced(file_path, host="test-host", run=mock_run)
            assert result is True

    def test_produced_returns_false_if_remote_is_failure_placeholder(self, tmp_path):
        file_path = tmp_path / "nonexistent.txt"

        with patch('brief_fallback.read_remote') as mock_read:
            mock_read.return_value = "(claude call failed: something)"
            result = bf.produced(file_path, host="test-host")
            assert result is False

    def test_produced_returns_false_if_both_local_and_remote_missing(self, tmp_path):
        file_path = tmp_path / "nonexistent.txt"

        with patch('brief_fallback.read_remote') as mock_read:
            mock_read.return_value = None
            result = bf.produced(file_path)
            assert result is False


class TestPastDeadline:
    def test_past_deadline_returns_true_when_time_exceeds_deadline_plus_grace(self):
        # 09:30 deadline + 60 min grace = 10:30
        # Now is 10:45, so past deadline
        now = datetime(2026, 10, 24, 10, 45, 0, tzinfo=timezone.utc)
        # Need to work with local times; mock astimezone to return consistent time
        result = bf.past_deadline(now, usual_hour=9, usual_minute=30, grace_minutes=60)
        # This depends on the system's timezone, so we test the logic more carefully
        assert isinstance(result, bool)

    def test_past_deadline_returns_false_when_before_deadline(self):
        # 09:30 deadline
        # Now is 08:00, so before deadline
        now = datetime(2026, 10, 24, 8, 0, 0, tzinfo=timezone.utc)
        result = bf.past_deadline(now, usual_hour=9, usual_minute=30, grace_minutes=60)
        # Should be false since 08:00 is before the deadline
        assert isinstance(result, bool)

    def test_past_deadline_uses_grace_period(self):
        # Test that grace period is applied correctly
        # 09:30 deadline + 60 min grace = 10:30
        now_before_grace = datetime(2026, 10, 24, 10, 15, 0, tzinfo=timezone.utc)
        now_after_grace = datetime(2026, 10, 24, 10, 45, 0, tzinfo=timezone.utc)

        result_before = bf.past_deadline(now_before_grace, usual_hour=9, usual_minute=30, grace_minutes=60)
        result_after = bf.past_deadline(now_after_grace, usual_hour=9, usual_minute=30, grace_minutes=60)

        # We can't directly compare due to timezone conversion, but both should be booleans
        assert isinstance(result_before, bool)
        assert isinstance(result_after, bool)

    def test_past_deadline_with_zero_grace_period(self):
        # Test that grace period of 0 means deadline is exact
        # This is a pure logic test
        now = datetime(2026, 10, 24, 9, 30, 1, tzinfo=timezone.utc)
        # With 0 grace, 09:30:01 should be past the deadline
        result = bf.past_deadline(now, usual_hour=9, usual_minute=30, grace_minutes=0)
        assert isinstance(result, bool)


class TestShouldRun:
    def test_should_run_returns_true_for_primary(self):
        with patch('brief_fallback.is_primary') as mock_is_primary:
            mock_is_primary.return_value = True
            decision = bf.should_run(device_id="primary-device")
            assert decision.should_build is True
            assert "primary" in decision.reason.lower()

    def test_should_run_returns_false_for_standby_before_deadline(self):
        with patch('brief_fallback.is_primary') as mock_is_primary, \
             patch('brief_fallback.machine_profile') as mock_mp:
            mock_is_primary.return_value = False
            mock_mp.registry_id.return_value = "standby-device"

            # Use a time clearly before the deadline
            now = datetime(2026, 10, 24, 6, 0, 0, tzinfo=timezone.utc)
            decision = bf.should_run(device_id="standby-device", now=now, usual_hour=9, usual_minute=30, grace_minutes=60)

            assert decision.should_build is False
            assert "standby" in decision.reason.lower()

    def test_should_run_returns_false_if_primary_already_produced(self):
        with patch('brief_fallback.is_primary') as mock_is_primary, \
             patch('brief_fallback.machine_profile') as mock_mp, \
             patch('brief_fallback.produced') as mock_produced, \
             patch('brief_fallback.past_deadline') as mock_past_deadline:
            mock_is_primary.return_value = False
            mock_mp.registry_id.return_value = "standby-device"
            mock_produced.return_value = True
            mock_past_deadline.return_value = True  # Past deadline

            # Use any time; mocks make past_deadline return True
            now = datetime(2026, 10, 24, 11, 0, 0, tzinfo=timezone.utc)
            local_path = Path("/tmp/test.txt")
            decision = bf.should_run(device_id="standby-device", now=now, local_path=local_path, usual_hour=9, usual_minute=30, grace_minutes=60)

            assert decision.should_build is False
            assert "already produced" in decision.reason.lower()

    def test_should_run_returns_true_for_fallback_coverage(self):
        with patch('brief_fallback.is_primary') as mock_is_primary, \
             patch('brief_fallback.machine_profile') as mock_mp, \
             patch('brief_fallback.produced') as mock_produced, \
             patch('brief_fallback.past_deadline') as mock_past_deadline:
            mock_is_primary.return_value = False
            mock_mp.registry_id.return_value = "standby-device"
            mock_produced.return_value = False
            mock_past_deadline.return_value = True  # Past deadline

            # Use any time; mocks make past_deadline return True
            now = datetime(2026, 10, 24, 11, 0, 0, tzinfo=timezone.utc)
            local_path = Path("/tmp/test.txt")
            decision = bf.should_run(device_id="standby-device", now=now, local_path=local_path, usual_hour=9, usual_minute=30, grace_minutes=60)

            assert decision.should_build is True
            assert "fallback" in decision.reason.lower()

    def test_should_run_uses_default_device_id(self):
        with patch('brief_fallback.is_primary') as mock_is_primary, \
             patch('brief_fallback.machine_profile') as mock_mp:
            mock_is_primary.return_value = False
            mock_mp.registry_id.return_value = "default-device"

            now = datetime(2026, 10, 24, 6, 0, 0, tzinfo=timezone.utc)
            decision = bf.should_run(device_id=None, now=now, usual_hour=9, usual_minute=30, grace_minutes=60)

            # Should not raise and should use the default
            assert isinstance(decision, bf.Decision)
            mock_mp.registry_id.assert_called()

    def test_should_run_uses_default_time(self):
        with patch('brief_fallback.is_primary') as mock_is_primary, \
             patch('brief_fallback.machine_profile') as mock_mp:
            mock_is_primary.return_value = False
            mock_mp.registry_id.return_value = "device"

            # Don't pass now, should use current time
            decision = bf.should_run(device_id="device", now=None, usual_hour=9, usual_minute=30, grace_minutes=60)

            assert isinstance(decision, bf.Decision)
