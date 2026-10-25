#!/usr/bin/env python3
"""Tests for lib/brief_fallback.py — fallback builder gate logic."""
import pytest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch, MagicMock
import sys
import os

# Ensure we can import lib modules
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import brief_fallback


class TestPastDeadline:
    """Test past_deadline() deadline + grace period logic."""

    def test_well_before_deadline(self):
        """Before usual time, should not be past deadline."""
        # 08:00 local time, deadline is 08:30
        from datetime import tzinfo
        local_tz = datetime.now(timezone.utc).astimezone().tzinfo
        now = datetime(2026, 10, 25, 8, 0, 0, tzinfo=local_tz)
        assert not brief_fallback.past_deadline(now, usual_hour=8, usual_minute=30, grace_minutes=60)

    def test_after_deadline_plus_grace(self):
        """After usual time plus grace period, should be past deadline."""
        # 09:40 local time, deadline is 08:30 + 60m = 09:30
        local_tz = datetime.now(timezone.utc).astimezone().tzinfo
        now = datetime(2026, 10, 25, 9, 40, 0, tzinfo=local_tz)
        assert brief_fallback.past_deadline(now, usual_hour=8, usual_minute=30, grace_minutes=60)

    def test_at_deadline(self):
        """Exactly at usual time, should not be past deadline (still within grace)."""
        local_tz = datetime.now(timezone.utc).astimezone().tzinfo
        now = datetime(2026, 10, 25, 8, 30, 0, tzinfo=local_tz)
        assert not brief_fallback.past_deadline(now, usual_hour=8, usual_minute=30, grace_minutes=60)

    def test_at_deadline_end(self):
        """Exactly at deadline + grace, should be past deadline."""
        # 09:30 local time, deadline is 08:30 + 60m = 09:30
        local_tz = datetime.now(timezone.utc).astimezone().tzinfo
        now = datetime(2026, 10, 25, 9, 30, 0, tzinfo=local_tz)
        assert brief_fallback.past_deadline(now, usual_hour=8, usual_minute=30, grace_minutes=60)


class TestProduced:
    """Test produced() file existence and validity checks."""

    def test_local_file_exists_and_valid(self, tmp_path):
        """Existing file with content counts as produced."""
        test_file = tmp_path / "test_output.txt"
        test_file.write_text("Brief content here")
        assert brief_fallback.produced(test_file)

    def test_local_file_empty(self, tmp_path):
        """Empty file does not count as produced."""
        test_file = tmp_path / "test_output.txt"
        test_file.write_text("")
        assert not brief_fallback.produced(test_file)

    def test_local_file_whitespace_only(self, tmp_path):
        """Whitespace-only file does not count as produced."""
        test_file = tmp_path / "test_output.txt"
        test_file.write_text("   \n\t  ")
        assert not brief_fallback.produced(test_file)

    def test_local_file_failure_placeholder(self, tmp_path):
        """File with failure placeholder does not count as produced."""
        test_file = tmp_path / "test_output.txt"
        test_file.write_text("(claude call failed: some error)")
        assert not brief_fallback.produced(test_file)

    def test_local_file_quarantined(self, tmp_path):
        """Quarantined file counts as produced (safety outcome, not outage)."""
        test_file = tmp_path / "test_output.txt"
        test_file.write_text("Some content\n_Quarantined by safety-monitor")
        assert brief_fallback.produced(test_file)

    def test_remote_file_read_on_local_missing(self, tmp_path):
        """When local file is missing, attempts to read remote."""
        test_file = tmp_path / "test_output.txt"  # Does not exist
        mock_run = MagicMock()
        mock_run.return_value = MagicMock(returncode=0, stdout="Remote content")

        with patch("brief_fallback.read_remote", return_value="Remote content"):
            assert brief_fallback.produced(test_file)


class TestShouldRun:
    """Test should_run() decision logic for primary vs. fallback."""

    @patch("brief_fallback.machine_profile.registry_id")
    @patch("brief_fallback.is_primary")
    def test_primary_always_builds(self, mock_is_primary, mock_registry_id):
        """Primary device always returns True."""
        mock_registry_id.return_value = "mini"
        mock_is_primary.return_value = True
        now = datetime(2026, 10, 25, 10, 0, 0, tzinfo=timezone.utc)

        decision = brief_fallback.should_run(device_id="mini", now=now)
        assert decision.should_build
        assert decision.reason == "primary"

    @patch("brief_fallback.machine_profile.registry_id")
    @patch("brief_fallback.is_primary")
    def test_standby_before_deadline(self, mock_is_primary, mock_registry_id):
        """Standby device before deadline should not build."""
        mock_registry_id.return_value = "macbook"
        mock_is_primary.return_value = False
        # 08:00 local time, deadline is 08:30 + 60m = 09:30
        local_tz = datetime.now(timezone.utc).astimezone().tzinfo
        now = datetime(2026, 10, 25, 8, 0, 0, tzinfo=local_tz)

        decision = brief_fallback.should_run(
            device_id="macbook", now=now, local_path=None,
            usual_hour=8, usual_minute=30, grace_minutes=60
        )
        assert not decision.should_build
        assert "standby: before deadline" in decision.reason

    @patch("brief_fallback.machine_profile.registry_id")
    @patch("brief_fallback.is_primary")
    def test_fallback_after_deadline_no_production(self, mock_is_primary, mock_registry_id, tmp_path):
        """Standby device after deadline with no production should build."""
        mock_registry_id.return_value = "macbook"
        mock_is_primary.return_value = False
        # 09:40 local time, deadline is 08:30 + 60m = 09:30
        local_tz = datetime.now(timezone.utc).astimezone().tzinfo
        now = datetime(2026, 10, 25, 9, 40, 0, tzinfo=local_tz)
        test_file = tmp_path / "test_output.txt"  # Does not exist

        decision = brief_fallback.should_run(
            device_id="macbook", now=now, local_path=test_file,
            usual_hour=8, usual_minute=30, grace_minutes=60
        )
        assert decision.should_build
        assert "fallback: covering for the primary" in decision.reason

    @patch("brief_fallback.machine_profile.registry_id")
    @patch("brief_fallback.is_primary")
    def test_standby_after_deadline_with_production(self, mock_is_primary, mock_registry_id, tmp_path):
        """Standby device after deadline but primary already produced should not build."""
        mock_registry_id.return_value = "macbook"
        mock_is_primary.return_value = False
        # 09:40 local time, deadline is 08:30 + 60m = 09:30
        local_tz = datetime.now(timezone.utc).astimezone().tzinfo
        now = datetime(2026, 10, 25, 9, 40, 0, tzinfo=local_tz)
        test_file = tmp_path / "test_output.txt"
        test_file.write_text("Primary produced content")

        decision = brief_fallback.should_run(
            device_id="macbook", now=now, local_path=test_file,
            usual_hour=8, usual_minute=30, grace_minutes=60
        )
        assert not decision.should_build
        assert "standby: primary already produced" in decision.reason


class TestInferRemotePath:
    """Test _infer_remote_path() path conversion logic."""

    def test_home_relative_path(self):
        """Home-relative paths become $HOME/..."""
        home = Path.home()
        local_path = home / ".claude" / "outbox" / "brief.txt"
        result = brief_fallback._infer_remote_path(local_path)
        assert result.startswith("$HOME/")
        assert "brief.txt" in result

    def test_non_home_path(self):
        """Non-home paths fall back to filename in ~/.claude."""
        # Create a path that's definitely not under home
        local_path = Path("/tmp/test_brief.txt")
        result = brief_fallback._infer_remote_path(local_path)
        assert result == "$HOME/.claude/test_brief.txt"
