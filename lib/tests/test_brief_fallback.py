#!/usr/bin/env python3
"""Tests for brief_fallback.py: deadline checking, produced detection."""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import brief_fallback


class TestProduced:
    """Test produced() detection."""

    def test_produced_file_exists(self, tmp_path):
        """File exists with content -> produced returns True."""
        f = tmp_path / "test.md"
        f.write_text("content")
        assert brief_fallback.produced(f)

    def test_produced_sidecar_exists(self, tmp_path):
        """File doesn't exist but .produced sidecar does -> True."""
        f = tmp_path / "test.md"
        sidecar = tmp_path / "test.md.produced"
        sidecar.write_text("data")
        assert brief_fallback.produced(f)

    def test_produced_neither_exists(self, tmp_path):
        """File and sidecar don't exist -> False."""
        f = tmp_path / "test.md"
        assert not brief_fallback.produced(f)

    def test_produced_file_empty_or_whitespace(self, tmp_path):
        """File exists but is empty or whitespace-only -> False."""
        f = tmp_path / "test.md"
        f.write_text("   \n  \n")
        assert not brief_fallback.produced(f)

    def test_produced_file_with_failure_marker(self, tmp_path):
        """File exists with failure marker -> False (builder tried but failed, skip fallback)."""
        f = tmp_path / "test.md"
        f.write_text("(claude call failed: timeout)")
        assert not brief_fallback.produced(f)

    def test_produced_file_with_quarantine_marker(self, tmp_path):
        """File exists with quarantine marker -> True (output was produced and flagged)."""
        f = tmp_path / "test.md"
        f.write_text("_Quarantined by safety-monitor before shipping — flagged as risky._")
        assert brief_fallback.produced(f)


class TestPastDeadline:
    """Test past_deadline() logic."""

    def test_before_deadline(self):
        """Before scheduled time -> False."""
        # Create a time 8:00 AM in local timezone
        from datetime import date
        from zoneinfo import ZoneInfo
        local_tz = ZoneInfo("America/Denver")  # Test with a specific timezone
        now_local = datetime(2026, 10, 25, 8, 0, 0, tzinfo=local_tz)
        # Convert to UTC for the function (past_deadline will convert back)
        now_utc = now_local.astimezone(timezone.utc)

        assert not brief_fallback.past_deadline(
            now_utc, usual_hour=9, usual_minute=0, grace_minutes=0
        )

    def test_at_deadline(self):
        """Exactly at scheduled time -> False (no grace)."""
        from zoneinfo import ZoneInfo
        local_tz = ZoneInfo("America/Denver")
        now_local = datetime(2026, 10, 25, 9, 0, 0, tzinfo=local_tz)
        now_utc = now_local.astimezone(timezone.utc)

        assert not brief_fallback.past_deadline(
            now_utc, usual_hour=9, usual_minute=0, grace_minutes=0
        )

    def test_after_deadline_with_grace(self):
        """Past deadline+grace window -> True."""
        from zoneinfo import ZoneInfo
        local_tz = ZoneInfo("America/Denver")
        now_local = datetime(2026, 10, 25, 10, 5, 0, tzinfo=local_tz)  # 10:05 AM local = past 09:00 + 60 min
        now_utc = now_local.astimezone(timezone.utc)

        assert brief_fallback.past_deadline(
            now_utc, usual_hour=9, usual_minute=0, grace_minutes=60
        )

    def test_within_grace_window(self):
        """Within grace period -> False."""
        from zoneinfo import ZoneInfo
        local_tz = ZoneInfo("America/Denver")
        now_local = datetime(2026, 10, 25, 9, 30, 0, tzinfo=local_tz)  # 09:30 AM local = within 60 min of 09:00
        now_utc = now_local.astimezone(timezone.utc)

        assert not brief_fallback.past_deadline(
            now_utc, usual_hour=9, usual_minute=0, grace_minutes=60
        )


class TestShouldRun:
    """Test should_run() decision logic."""

    def test_already_produced(self, tmp_path):
        """File already produced -> (False, reason)."""
        from zoneinfo import ZoneInfo
        f = tmp_path / "brief.md"
        f.write_text("data")
        local_tz = ZoneInfo("America/Denver")
        now_local = datetime(2026, 10, 25, 10, 30, tzinfo=local_tz)
        now = now_local.astimezone(timezone.utc)
        should, reason = brief_fallback.should_run(f, usual_hour=9, usual_minute=45, grace_minutes=60, now=now)
        assert not should
        assert "already produced" in reason

    def test_deadline_not_reached(self, tmp_path):
        """Deadline not reached -> (False, reason)."""
        from zoneinfo import ZoneInfo
        f = tmp_path / "brief.md"
        local_tz = ZoneInfo("America/Denver")
        now_local = datetime(2026, 10, 25, 10, 0, tzinfo=local_tz)  # Before 10:45
        now = now_local.astimezone(timezone.utc)
        should, reason = brief_fallback.should_run(f, usual_hour=9, usual_minute=45, grace_minutes=60, now=now)
        assert not should
        assert "not yet reached" in reason

    def test_fallback_should_run(self, tmp_path):
        """Past deadline, not produced -> (True, reason)."""
        from zoneinfo import ZoneInfo
        f = tmp_path / "brief.md"
        local_tz = ZoneInfo("America/Denver")
        now_local = datetime(2026, 10, 25, 10, 50, tzinfo=local_tz)  # After 10:45 (09:45 + 60 min)
        now = now_local.astimezone(timezone.utc)
        should, reason = brief_fallback.should_run(f, usual_hour=9, usual_minute=45, grace_minutes=60, now=now)
        assert should
        assert "fallback" in reason




if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
