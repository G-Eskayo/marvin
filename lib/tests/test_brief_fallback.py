#!/usr/bin/env python3
"""Tests for lib/brief_fallback.py — fallback builder gate for digests and brief."""
from __future__ import annotations
import json
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import brief_fallback as bf
import scanner_role
import machine_profile


NOW = datetime(2026, 10, 24, 9, 30, tzinfo=timezone.utc)


class TestShouldRun:
    """Tests for should_run() decision logic."""

    def test_primary_always_builds(self, monkeypatch):
        """Primary machine always returns should_build=True."""
        monkeypatch.setattr(scanner_role, "is_primary", lambda device_id: True)
        monkeypatch.setattr(machine_profile, "registry_id", lambda: "mac-mini-1")

        result = bf.should_run(device_id="mac-mini-1", now=NOW)
        assert result.should_build is True
        assert result.reason == "primary"

    def test_fallback_skips_before_deadline(self, monkeypatch):
        """Fallback skips when before deadline + grace."""
        local_now = NOW.astimezone().replace(hour=8, minute=50)
        now = local_now.astimezone(timezone.utc)

        def mock_is_primary(device_id: str) -> bool:
            return device_id.startswith("mac-mini")
        monkeypatch.setattr(scanner_role, "is_primary", mock_is_primary)
        monkeypatch.setattr(machine_profile, "registry_id", lambda: "macbook-pro")

        result = bf.should_run(device_id="macbook-pro", now=now,
                              usual_hour=8, usual_minute=30, grace_minutes=60)
        assert result.should_build is False
        assert "before deadline" in result.reason

    def test_fallback_builds_if_primary_stale(self, tmp_path, monkeypatch):
        """Fallback builds when primary hasn't produced."""
        local_now = NOW.astimezone().replace(hour=10, minute=0)
        now = local_now.astimezone(timezone.utc)

        output_file = tmp_path / "briefs" / "2026-10-24.md"
        output_file.parent.mkdir(parents=True, exist_ok=True)

        def mock_is_primary(device_id: str) -> bool:
            return device_id.startswith("mac-mini")
        monkeypatch.setattr(scanner_role, "is_primary", mock_is_primary)
        monkeypatch.setattr(machine_profile, "registry_id", lambda: "macbook-pro")

        def mock_read_remote(remote_path, host=None, run=subprocess.run):
            return None
        monkeypatch.setattr(bf, "read_remote", mock_read_remote)

        result = bf.should_run(device_id="macbook-pro", now=now, local_path=output_file,
                              usual_hour=8, usual_minute=30, grace_minutes=60)
        assert result.should_build is True
        assert "fallback" in result.reason

    def test_fallback_skips_if_primary_fresh(self, tmp_path, monkeypatch):
        """Fallback skips when primary already produced today."""
        now = datetime.now(timezone.utc)
        local_today = now.astimezone().strftime("%Y-%m-%d")

        output_file = tmp_path / "briefs" / f"{local_today}.md"
        output_file.parent.mkdir(parents=True, exist_ok=True)
        output_file.write_text("# Brief")

        def mock_is_primary(device_id: str) -> bool:
            return device_id.startswith("mac-mini")
        monkeypatch.setattr(scanner_role, "is_primary", mock_is_primary)
        monkeypatch.setattr(machine_profile, "registry_id", lambda: "macbook-pro")

        def mock_read_remote(remote_path, host=None, run=subprocess.run):
            return output_file.read_text()
        monkeypatch.setattr(bf, "read_remote", mock_read_remote)

        result = bf.should_run(device_id="macbook-pro", now=now, local_path=output_file,
                              usual_hour=8, usual_minute=30, grace_minutes=60)
        assert result.should_build is False
        assert "already produced" in result.reason


class TestProduced:
    """Tests for produced() file existence check."""

    def test_produced_returns_true_for_nonempty_local_file(self, tmp_path):
        """produced() returns True when local file exists and has content."""
        f = tmp_path / "digest.md"
        f.write_text("# Content")
        assert bf.produced(f) is True

    def test_produced_returns_false_for_empty_file(self, tmp_path):
        """produced() returns False when file is empty."""
        f = tmp_path / "digest.md"
        f.write_text("")
        assert bf.produced(f) is False

    def test_produced_returns_false_for_whitespace_only(self, tmp_path):
        """produced() returns False when file contains only whitespace."""
        f = tmp_path / "digest.md"
        f.write_text("   \n  \n")
        assert bf.produced(f) is False

    def test_produced_returns_false_for_failure_placeholder(self, tmp_path):
        """produced() returns False for claude call failure strings."""
        f = tmp_path / "digest.md"
        f.write_text("(claude call failed: timeout)")
        assert bf.produced(f) is False

    def test_produced_returns_true_for_quarantined_content(self, tmp_path):
        """produced() returns True for quarantined content (it was produced)."""
        f = tmp_path / "digest.md"
        f.write_text("_Quarantined by safety-monitor\n\nContent.")
        assert bf.produced(f) is True

    def test_produced_checks_remote_when_local_missing(self, tmp_path, monkeypatch):
        """produced() falls through to remote check if local file missing."""
        f = tmp_path / "digest.md"

        def mock_read_remote(remote_path, host=None, run=subprocess.run):
            return "# Remote content"
        monkeypatch.setattr(bf, "read_remote", mock_read_remote)

        assert bf.produced(f) is True

    def test_produced_returns_false_when_remote_also_missing(self, tmp_path, monkeypatch):
        """produced() returns False when both local and remote are missing."""
        f = tmp_path / "digest.md"

        def mock_read_remote(remote_path, host=None, run=subprocess.run):
            return None
        monkeypatch.setattr(bf, "read_remote", mock_read_remote)

        assert bf.produced(f) is False


class TestPastDeadline:
    """Tests for past_deadline() time comparison."""

    def test_past_deadline_true_when_past_deadline_plus_grace(self):
        """past_deadline returns True when now > usual_hour:minute + grace."""
        local_now = NOW.astimezone().replace(hour=9, minute=40)
        now = local_now.astimezone(timezone.utc)

        assert bf.past_deadline(now, usual_hour=8, usual_minute=30, grace_minutes=60) is True

    def test_past_deadline_false_before_grace(self):
        """past_deadline returns False when now < usual_hour:minute + grace."""
        local_now = NOW.astimezone().replace(hour=8, minute=50)
        now = local_now.astimezone(timezone.utc)

        assert bf.past_deadline(now, usual_hour=8, usual_minute=30, grace_minutes=60) is False

    def test_past_deadline_uses_local_time(self):
        """past_deadline compares in local wall-clock time, not UTC."""
        # Use local time directly to avoid timezone offset issues
        local_now = datetime(2026, 10, 24, 12, 40, 0)
        local_now_with_tz = local_now.astimezone(timezone.utc)
        assert bf.past_deadline(local_now_with_tz, usual_hour=12, usual_minute=30, grace_minutes=5) is True


class TestInferRemotePath:
    """Tests for _infer_remote_path() path resolution."""

    def test_infer_remote_path_for_home_relative(self, monkeypatch):
        """_infer_remote_path converts home-relative paths to $HOME/..."""
        monkeypatch.setenv("HOME", "/home/testuser")
        home = Path("/home/testuser")
        path = home / ".claude" / "briefs" / "2026-10-24.md"

        result = bf._infer_remote_path(path)
        assert result == "$HOME/.claude/briefs/2026-10-24.md"

    def test_infer_remote_path_fallback_for_non_home_paths(self, monkeypatch):
        """_infer_remote_path falls back for paths outside home."""
        monkeypatch.setenv("HOME", "/home/testuser")
        path = Path("/tmp/digest.md")

        result = bf._infer_remote_path(path)
        assert "$HOME" in result and "digest.md" in result


class TestReadRemote:
    """Tests for read_remote() SSH file reads."""

    def test_read_remote_succeeds_with_content(self, monkeypatch):
        """read_remote returns file content on successful SSH read."""
        def mock_run(cmd, **kwargs):
            result = MagicMock()
            result.returncode = 0
            result.stdout = "# Remote content\n"
            return result

        result = bf.read_remote("$HOME/.claude/briefs/2026-10-24.md", host="remote-host", run=mock_run)
        assert result == "# Remote content\n"

    def test_read_remote_returns_none_on_ssh_failure(self, monkeypatch):
        """read_remote returns None when SSH fails."""
        def mock_run(cmd, **kwargs):
            result = MagicMock()
            result.returncode = 1
            return result

        result = bf.read_remote("$HOME/.claude/briefs/2026-10-24.md", host="remote-host", run=mock_run)
        assert result is None

    def test_read_remote_returns_none_on_timeout(self, monkeypatch):
        """read_remote returns None on SSH timeout."""
        def mock_run(cmd, **kwargs):
            raise subprocess.TimeoutExpired("ssh", 15)

        result = bf.read_remote("$HOME/.claude/briefs/2026-10-24.md", host="remote-host", run=mock_run)
        assert result is None

    def test_read_remote_quotes_path_safely(self):
        """read_remote properly quotes paths with special chars."""
        paths_captured = []

        def mock_run(cmd, **kwargs):
            paths_captured.append(cmd)
            result = MagicMock()
            result.returncode = 0
            result.stdout = "content"
            return result

        bf.read_remote("$HOME/path with spaces/file.md", host="remote", run=mock_run)
        cmd = paths_captured[0]
        assert "ssh" in cmd
        assert any("path with spaces" in str(arg) for arg in cmd)
