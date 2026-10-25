#!/usr/bin/env python3
"""Tests for brief_fallback.py — the gating and resilience layer for scheduled morning jobs."""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import brief_fallback
from brief_fallback import Decision, produced, should_run, past_deadline, read_remote


class TestDecision:
    """Test 18: Decision NamedTuple can be constructed and accessed."""

    def test_decision_construction(self):
        """Decision can be created with all required fields."""
        d = Decision(
            name="morning-brief",
            primary_machine="mac-mini",
            primary_hour=9,
            primary_minute=45,
            fallback_machine="macbook-pro",
            fallback_hour=10,
            fallback_minute=45,
            soft_deadline_hours=4,
            hard_deadline_hours=8,
        )
        assert d.name == "morning-brief"
        assert d.primary_machine == "mac-mini"
        assert d.primary_hour == 9
        assert d.fallback_hour == 10
        assert d.hard_deadline_hours == 8


class TestProduced:
    """Tests 1, 2, 3, 5, 8: file existence, sidecar detection, and remote checking."""

    def test_produced_nonexistent_file(self, tmp_path):
        """Test 1: produced() returns False for non-existent files (when primary)."""
        path = tmp_path / "nonexistent.md"
        # When primary, produced() returns False for missing files (not looking remote).
        assert produced(path) is False

    def test_produced_file_without_sidecar(self, tmp_path):
        """Test 3: produced() returns True for files without a .built-by sidecar (legacy assumption)."""
        path = tmp_path / "brief.md"
        path.write_text("# Brief")
        # No sidecar: should assume it's produced (conservative — don't re-run).
        assert produced(path) is True

    def test_produced_file_with_own_sidecar(self, tmp_path, monkeypatch):
        """Test 3a: produced() returns False if sidecar names this machine."""
        path = tmp_path / "brief.md"
        path.write_text("# Brief")
        sidecar = tmp_path / "brief.md.built-by"
        sidecar.write_text("macbook-pro")

        # Mock registry_id to return the same machine as the sidecar.
        monkeypatch.setattr("brief_fallback.machine_profile.registry_id", lambda: "macbook-pro")
        assert produced(path) is False

    def test_produced_file_with_other_sidecar(self, tmp_path, monkeypatch):
        """Test 3: produced() returns True if sidecar names a different machine."""
        path = tmp_path / "brief.md"
        path.write_text("# Brief")
        sidecar = tmp_path / "brief.md.built-by"
        sidecar.write_text("mac-mini")

        # Mock registry_id to return a different machine.
        monkeypatch.setattr("brief_fallback.machine_profile.registry_id", lambda: "macbook-pro")
        assert produced(path) is True

    def test_produced_malformed_sidecar(self, tmp_path):
        """produced() returns True (lenient) if sidecar is malformed."""
        path = tmp_path / "brief.md"
        path.write_text("# Brief")
        sidecar = tmp_path / "brief.md.built-by"
        sidecar.write_text("")  # Empty/unreadable.
        assert produced(path) is True

    def test_produced_standby_file_from_primary_remote(self, tmp_path, monkeypatch):
        """Test 2: produced() returns True when standby finds file on primary (remote check)."""
        path = tmp_path / "brief.md"  # Not created locally
        monkeypatch.setattr("brief_fallback.machine_profile.registry_id", lambda: "macbook-pro")
        monkeypatch.setattr("brief_fallback.scanner_role.is_primary", lambda x: False)
        # Mock remote_macs() to return a dict with primary.
        monkeypatch.setattr("brief_fallback.machine_profile.remote_macs", lambda: {"mac-mini": {"tailscale_hostname": "mac-mini"}})
        # Mock read_remote() to return the file content from primary.
        monkeypatch.setattr("brief_fallback.read_remote", lambda p, d: "# Brief from primary" if d == "mac-mini" else None)
        assert produced(path) is True

    def test_produced_standby_file_missing_from_primary(self, tmp_path, monkeypatch):
        """Test 5: produced() returns False when standby can't reach primary (file truly missing)."""
        path = tmp_path / "brief.md"  # Not created locally
        monkeypatch.setattr("brief_fallback.machine_profile.registry_id", lambda: "macbook-pro")
        monkeypatch.setattr("brief_fallback.scanner_role.is_primary", lambda x: False)
        # Mock remote_macs() to return a dict with primary.
        monkeypatch.setattr("brief_fallback.machine_profile.remote_macs", lambda: {"mac-mini": {"tailscale_hostname": "mac-mini"}})
        # Mock read_remote() to return None (file not found remotely).
        monkeypatch.setattr("brief_fallback.read_remote", lambda p, d: None)
        assert produced(path) is False

    def test_produced_primary_machine_ignores_remote(self, tmp_path, monkeypatch):
        """Test 8: produced() returns False for primary when file is missing (doesn't check remote)."""
        path = tmp_path / "brief.md"  # Not created
        monkeypatch.setattr("brief_fallback.machine_profile.registry_id", lambda: "mac-mini")
        monkeypatch.setattr("brief_fallback.scanner_role.is_primary", lambda x: True)
        # Even though read_remote would return content, primary doesn't check remote.
        monkeypatch.setattr("brief_fallback.machine_profile.remote_macs", lambda: {"macbook-pro": {"tailscale_hostname": "macbook"}})
        monkeypatch.setattr("brief_fallback.read_remote", lambda p, d: "# Should be ignored")
        assert produced(path) is False


class TestShouldRun:
    """Tests 6, 7, 9 (standby), 11: gating logic."""

    def test_should_run_output_already_produced(self, tmp_path, monkeypatch):
        """Test 6: should_run() returns False when output is already produced."""
        path = tmp_path / "brief.md"
        path.write_text("# Brief")
        sidecar = tmp_path / "brief.md.built-by"
        sidecar.write_text("mac-mini")

        monkeypatch.setattr("brief_fallback.machine_profile.registry_id", lambda: "macbook-pro")
        assert should_run(path, 9, 45) is False

    def test_should_run_primary_machine(self, tmp_path, monkeypatch):
        """Test 7: should_run() returns True for the primary machine."""
        path = tmp_path / "brief.md"  # Not created — "not produced"
        monkeypatch.setattr("brief_fallback.machine_profile.registry_id", lambda: "mac-mini")
        monkeypatch.setattr("brief_fallback.scanner_role.is_primary", lambda x: True)
        assert should_run(path, 9, 45) is True

    def test_should_run_standby_before_fallback_time(self, tmp_path, monkeypatch):
        """Test 9 (standby): should_run() returns False for standby before fallback time."""
        path = tmp_path / "brief.md"  # Not created — "not produced"
        monkeypatch.setattr("brief_fallback.machine_profile.registry_id", lambda: "macbook-pro")
        monkeypatch.setattr("brief_fallback.scanner_role.is_primary", lambda x: False)

        # Mock the current time to be before the fallback time (primary_time + 1h).
        # Set primary time to 9:45, so fallback time is 10:45.
        # Mock "now" to 10:30 (30 min after primary, still before fallback).
        now = datetime.now(timezone.utc).astimezone().replace(hour=10, minute=30, second=0, microsecond=0)
        with patch("brief_fallback.datetime") as mock_dt:
            mock_dt.now.return_value = now
            mock_dt.side_effect = lambda *args, **kw: datetime(*args, **kw)
            assert should_run(path, 9, 45, fallback_offset_hours=1) is False

    def test_should_run_standby_after_fallback_time(self, tmp_path, monkeypatch):
        """Test 11: should_run() returns True for standby after fallback time."""
        path = tmp_path / "brief.md"  # Not created — "not produced"
        monkeypatch.setattr("brief_fallback.machine_profile.registry_id", lambda: "macbook-pro")
        monkeypatch.setattr("brief_fallback.scanner_role.is_primary", lambda x: False)

        # Mock "now" to 11:00 (75 min after primary at 9:45, past fallback at 10:45).
        now = datetime.now(timezone.utc).astimezone().replace(hour=11, minute=0, second=0, microsecond=0)
        with patch("brief_fallback.datetime") as mock_dt:
            mock_dt.now.return_value = now
            mock_dt.side_effect = lambda *args, **kw: datetime(*args, **kw)
            assert should_run(path, 9, 45, fallback_offset_hours=1) is True


class TestPastDeadline:
    """Tests 12, 13: deadline detection."""

    def test_past_deadline_newly_produced_file(self, tmp_path, monkeypatch):
        """Test 12: past_deadline() returns False for newly produced files."""
        path = tmp_path / "brief.md"
        path.write_text("# Brief")
        sidecar = tmp_path / "brief.md.built-by"
        sidecar.write_text("mac-mini")

        # Different machine, so produced() returns True.
        monkeypatch.setattr("brief_fallback.machine_profile.registry_id", lambda: "macbook-pro")
        assert past_deadline(path, 4, 9, 45) is False

    def test_past_deadline_missing_file(self, tmp_path):
        """Test 13: past_deadline() returns True when file is missing and deadline passed."""
        path = tmp_path / "brief.md"  # Not created.
        # File doesn't exist, so produced() returns False; deadline is in the past.
        # Use a past deadline (e.g., 9:45 + 4h = 13:45, check against 14:00).
        now = datetime.now(timezone.utc).astimezone().replace(hour=14, minute=0, second=0, microsecond=0)
        assert past_deadline(path, 4, 9, 45, now) is True


class TestHealthSeverity:
    """Tests for health_severity() with deadline anchor logic."""

    def test_health_severity_produced_file(self, tmp_path, monkeypatch):
        """Test: health_severity returns green when file is produced."""
        path = tmp_path / "brief.md"
        path.write_text("# Brief")
        sidecar = tmp_path / "brief.md.built-by"
        sidecar.write_text("mac-mini")
        monkeypatch.setattr("brief_fallback.machine_profile.registry_id", lambda: "macbook-pro")

        sev = brief_fallback.health_severity(path, 9, 45, 4, 12)
        assert sev == "green"

    def test_health_severity_missing_file_before_soft_deadline(self, tmp_path):
        """Test: health_severity returns green when before soft deadline."""
        path = tmp_path / "brief.md"  # Not created
        # Now at 10:00, deadline is 9:45 + 4h = 13:45, so still green (before soft deadline).
        now = datetime.now(timezone.utc).astimezone().replace(hour=10, minute=0, second=0, microsecond=0)
        sev = brief_fallback.health_severity(path, 9, 45, 4, 12, now=now)
        assert sev == "green"

    def test_health_severity_missing_file_past_soft_deadline(self, tmp_path):
        """Test: health_severity returns yellow when past soft deadline."""
        path = tmp_path / "brief.md"  # Not created
        # Now at 14:30, soft deadline 13:45, hard deadline 21:45.
        now = datetime.now(timezone.utc).astimezone().replace(hour=14, minute=30, second=0, microsecond=0)
        sev = brief_fallback.health_severity(path, 9, 45, 4, 12, now=now)
        assert sev == "yellow"

    def test_health_severity_missing_file_past_hard_deadline(self, tmp_path):
        """Test: health_severity returns red when past hard deadline."""
        path = tmp_path / "brief.md"  # Not created
        # Now at 22:00, hard deadline 21:45 (9:45 + 12h).
        now = datetime.now(timezone.utc).astimezone().replace(hour=22, minute=0, second=0, microsecond=0)
        sev = brief_fallback.health_severity(path, 9, 45, 4, 12, now=now)
        assert sev == "red"


class TestReadRemote:
    """Test 14: read_remote() handles offline devices gracefully."""

    def test_read_remote_device_offline(self, tmp_path, monkeypatch):
        """Test 14: read_remote() returns None when device is offline."""
        path = Path.home() / ".claude" / "briefs" / "2026-10-25.md"

        # Mock remote_devices to return a device.
        monkeypatch.setattr(
            "brief_fallback.machine_profile.remote_devices",
            lambda: {"mac-mini": {"tailscale_hostname": "mac-mini-tailscale"}},
        )
        # Mock _tailscale_online_hosts to return empty (no devices online).
        monkeypatch.setattr(
            "brief_fallback.task_dispatch._tailscale_online_hosts",
            lambda: set(),
        )
        assert read_remote(path, "mac-mini") is None

    def test_read_remote_device_not_registered(self, monkeypatch):
        """read_remote() returns None for unregistered device."""
        path = Path.home() / ".claude" / "briefs" / "2026-10-25.md"
        monkeypatch.setattr(
            "brief_fallback.machine_profile.remote_devices",
            lambda: {},  # No devices.
        )
        assert read_remote(path, "unknown-device") is None

    def test_read_remote_successful(self, tmp_path, monkeypatch):
        """read_remote() reads file contents from online device."""
        path = tmp_path / "brief.md"

        # Mock the devices and online status.
        monkeypatch.setattr(
            "brief_fallback.machine_profile.remote_devices",
            lambda: {"mac-mini": {"tailscale_hostname": "mac-mini-tailscale"}},
        )
        monkeypatch.setattr(
            "brief_fallback.task_dispatch._tailscale_online_hosts",
            lambda: {"mac-mini-tailscale"},
        )
        # Mock subprocess.run to return file contents.
        mock_run = MagicMock()
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = "# Brief from mac-mini\n"
        monkeypatch.setattr("brief_fallback.subprocess.run", mock_run)

        content = read_remote(path, "mac-mini")
        assert content == "# Brief from mac-mini\n"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
