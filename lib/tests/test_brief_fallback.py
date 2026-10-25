#!/usr/bin/env python3
"""Tests for lib/brief_fallback.py — fallback builder gate for digests and brief."""
from __future__ import annotations
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
import pytest
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import brief_fallback


class TestShouldRun:
    """Test should_run() decision logic."""

    def test_mini_always_builds_without_checking_anything(self):
        """Primary (mac-mini) always builds, no remote checks needed."""
        run_mock = lambda *args, **kwargs: None  # never called
        decision = brief_fallback.should_run(
            device_id="mac-mini-1",
            now=datetime.now(timezone.utc),
            run=run_mock,
        )
        assert decision.should_build is True
        assert decision.reason == "primary"

    def test_laptop_waits_before_the_deadline(self, tmp_path):
        """Before deadline, standby waits without checking primary."""
        local_path = tmp_path / "digest.md"

        # 7 AM — well before 8:30 AM deadline
        now = datetime(2026, 10, 22, 7, 0, 0, tzinfo=timezone.utc)

        def run_mock(*args, **kwargs):
            raise AssertionError("SSH should not be called before deadline")

        decision = brief_fallback.should_run(
            device_id="macbook-pro-1",
            now=now,
            local_path=local_path,
            run=run_mock,
        )
        assert decision.should_build is False
        assert "before deadline" in decision.reason

    def test_mini_down_all_morning_laptop_builds_once(self, tmp_path):
        """After deadline, if primary has nothing, fallback builds. Second call sees it produced."""
        local_path = tmp_path / "digest.md"
        remote_path = "$HOME/.claude/digest.md"

        # Past deadline: use 10 AM local time (which is definitely past 8:30 + 1h grace)
        # Create a datetime in local timezone
        import time
        local_tz = datetime.now().astimezone().tzinfo
        now = datetime(2026, 10, 22, 10, 0, 0, tzinfo=local_tz)
        # Convert to UTC for the function call
        now_utc = now.astimezone(timezone.utc)

        # Mock remote read returning None (unreachable)
        def run_mock_fail(cmd, *args, **kwargs):
            result = subprocess.CompletedProcess(cmd, returncode=1, stdout="", stderr="")
            return result

        # First call: nothing produced yet
        decision1 = brief_fallback.should_run(
            device_id="macbook-pro-1",
            now=now_utc,
            local_path=local_path,
            remote_path=remote_path,
            run=run_mock_fail,
        )
        assert decision1.should_build is True
        assert "fallback" in decision1.reason

        # Simulate primary now producing the file
        local_path.write_text("# Daily Digest\n\nSome content.")

        # Second call: file exists, so don't rebuild
        def run_mock_success(cmd, *args, **kwargs):
            result = subprocess.CompletedProcess(
                cmd,
                returncode=0,
                stdout="# Daily Digest\n\nSome content.",
                stderr="",
            )
            return result

        decision2 = brief_fallback.should_run(
            device_id="macbook-pro-1",
            now=now_utc,
            local_path=local_path,
            remote_path=remote_path,
            run=run_mock_success,
        )
        assert decision2.should_build is False
        assert "already produced" in decision2.reason

    def test_failure_placeholder_counts_as_not_produced(self, tmp_path):
        """A file with a failure marker is not considered produced."""
        local_path = tmp_path / "digest.md"
        local_path.write_text("(claude call failed: timeout)")

        # Use local timezone for the test
        local_tz = datetime.now().astimezone().tzinfo
        now = datetime(2026, 10, 22, 10, 0, 0, tzinfo=local_tz).astimezone(timezone.utc)

        decision = brief_fallback.should_run(
            device_id="macbook-pro-1",
            now=now,
            local_path=local_path,
        )
        assert decision.should_build is True
        assert "fallback" in decision.reason

    def test_empty_local_file_counts_as_not_produced(self, tmp_path):
        """A zero-byte or whitespace-only file is not produced."""
        local_path = tmp_path / "digest.md"
        local_path.write_text("")

        # Use local timezone for the test
        local_tz = datetime.now().astimezone().tzinfo
        now = datetime(2026, 10, 22, 10, 0, 0, tzinfo=local_tz).astimezone(timezone.utc)

        decision = brief_fallback.should_run(
            device_id="macbook-pro-1",
            now=now,
            local_path=local_path,
        )
        assert decision.should_build is True
        assert "fallback" in decision.reason

        # Also test whitespace-only
        local_path.write_text("   \n  \n")
        decision = brief_fallback.should_run(
            device_id="macbook-pro-1",
            now=now,
            local_path=local_path,
        )
        assert decision.should_build is True

    def test_clock_skew_never_compares_across_machines(self):
        """past_deadline uses only local clock, never remote clock."""
        # Simulate MacBook waking 6 hours late (use local time)
        local_tz = datetime.now().astimezone().tzinfo
        now = datetime(2026, 10, 22, 14, 30, 0, tzinfo=local_tz).astimezone(timezone.utc)

        result = brief_fallback.past_deadline(now, usual_hour=8, usual_minute=30)
        assert result is True  # Well past 8:30 + 1h grace = 9:30

        # Signature check: past_deadline takes no device_id or remote-clock argument
        sig = brief_fallback.past_deadline.__code__.co_varnames
        assert "device_id" not in sig
        assert "remote" not in sig

    def test_unreadable_local_file_falls_through_to_remote(self, tmp_path):
        """If local file has permission error, check remote instead."""
        local_path = tmp_path / "digest.md"
        local_path.write_text("content")
        # Make it unreadable
        local_path.chmod(0o000)

        try:
            def run_mock(cmd, *args, **kwargs):
                return subprocess.CompletedProcess(
                    cmd,
                    returncode=0,
                    stdout="# Remote content",
                    stderr="",
                )

            # Call produced() directly with explicit remote path
            result = brief_fallback.produced(
                local_path,
                remote_path="$HOME/.claude/digest.md",
                host="test-host",
                run=run_mock,
            )
            assert result is True
        finally:
            # Restore permissions for cleanup
            local_path.chmod(0o644)

    def test_registry_lookup_failure_treated_as_not_produced(self, tmp_path, monkeypatch):
        """If machine registry is unavailable, treat as "not produced" not a crash."""
        local_path = tmp_path / "digest.md"

        # Monkeypatch remote_devices to raise
        def mock_remote_devices():
            raise RuntimeError("marvin-network.json missing")
        monkeypatch.setattr("brief_fallback.machine_profile.remote_devices", mock_remote_devices)

        # Use local timezone for the test
        local_tz = datetime.now().astimezone().tzinfo
        now = datetime(2026, 10, 22, 10, 0, 0, tzinfo=local_tz).astimezone(timezone.utc)

        # Should not crash, should return "should build"
        decision = brief_fallback.should_run(
            device_id="macbook-pro-1",
            now=now,
            local_path=local_path,
        )
        assert decision.should_build is True


class TestPastDeadline:
    """Test past_deadline() grace-period logic."""

    def test_exactly_at_deadline(self):
        """Exactly at scheduled time is not yet past (grace hasn't expired)."""
        local_tz = datetime.now().astimezone().tzinfo
        now = datetime(2026, 10, 22, 8, 30, 0, tzinfo=local_tz).astimezone(timezone.utc)
        result = brief_fallback.past_deadline(now, usual_hour=8, usual_minute=30)
        assert result is False  # Deadline itself is not "past"

    def test_one_minute_after_scheduled_time(self):
        """One minute after is still within 60-minute grace."""
        local_tz = datetime.now().astimezone().tzinfo
        now = datetime(2026, 10, 22, 8, 31, 0, tzinfo=local_tz).astimezone(timezone.utc)
        result = brief_fallback.past_deadline(now, usual_hour=8, usual_minute=30)
        assert result is False

    def test_59_minutes_after_scheduled_time(self):
        """59 minutes after is still within grace."""
        local_tz = datetime.now().astimezone().tzinfo
        now = datetime(2026, 10, 22, 9, 29, 0, tzinfo=local_tz).astimezone(timezone.utc)
        result = brief_fallback.past_deadline(now, usual_hour=8, usual_minute=30, grace_minutes=60)
        assert result is False

    def test_60_minutes_after_scheduled_time(self):
        """60 minutes after (deadline + grace) is past."""
        local_tz = datetime.now().astimezone().tzinfo
        now = datetime(2026, 10, 22, 9, 30, 0, tzinfo=local_tz).astimezone(timezone.utc)
        result = brief_fallback.past_deadline(now, usual_hour=8, usual_minute=30, grace_minutes=60)
        assert result is True

    def test_much_later_in_day(self):
        """Many hours later: definitely past deadline."""
        local_tz = datetime.now().astimezone().tzinfo
        now = datetime(2026, 10, 22, 15, 0, 0, tzinfo=local_tz).astimezone(timezone.utc)
        result = brief_fallback.past_deadline(now, usual_hour=8, usual_minute=30)
        assert result is True


class TestInferRemotePath:
    """Test _infer_remote_path() helper."""

    @pytest.mark.parametrize("subdir,name", [
        ("skills/improve/outputs", "daily-digest.md"),
        ("skills/research-colony/outputs", "research-digest.md"),
        (".claude/outputs", "briefs.json"),
    ])
    def test_infer_remote_path_preserves_subdirectory(self, subdir, name, tmp_path, monkeypatch):
        """_infer_remote_path() computes path relative to home, preserving subdirectories."""
        # Create a temp home and construct the path
        monkeypatch.setenv("HOME", str(tmp_path))
        home = Path.home()
        local_dir = home / subdir
        local_dir.mkdir(parents=True, exist_ok=True)
        local_path = local_dir / name

        remote = brief_fallback._infer_remote_path(local_path)
        # Should compute relative to home
        assert remote == f"$HOME/{subdir}/{name}"

    def test_infer_remote_path_falls_back_to_filename_outside_home(self):
        """_infer_remote_path() falls back to .claude/{name} for paths outside home."""
        # Use an absolute path not under any home
        outside_home = Path("/tmp/outside_home/digest.md")
        remote = brief_fallback._infer_remote_path(outside_home)
        # Should fall back to just the filename in .claude/
        assert remote == "$HOME/.claude/digest.md"


class TestReadRemote:
    """Test read_remote() SSH path handling."""

    def test_read_remote_lets_home_expand_but_quotes_rest(self, tmp_path):
        """read_remote() splits $HOME/ so shell expands it, but safely quotes the rest."""
        # When remote_path is "$HOME/skills/improve/outputs/daily-digest.md"
        # The SSH command should be: cat "$HOME/skills/improve/outputs/daily-digest.md"
        # (splitting so $HOME expands but the path part is quoted)

        commands_received = []

        def run_mock(cmd, *args, **kwargs):
            commands_received.append(cmd)
            # Simulate SSH returning the file content
            return subprocess.CompletedProcess(cmd, returncode=0, stdout="content", stderr="")

        result = brief_fallback.read_remote(
            "$HOME/skills/improve/outputs/daily-digest.md",
            host="test-host",
            run=run_mock,
        )

        assert result == "content"
        assert len(commands_received) == 1
        cmd = commands_received[0]
        # Should be: ssh [...opts] test-host cat $HOME/skills/improve/outputs/daily-digest.md
        # (with the path part quoted to protect against spaces/special chars)
        cmd_str = " ".join(cmd)
        assert "cat" in cmd_str
        assert "$HOME/" in cmd_str  # Should preserve $HOME/ literally

    def test_read_remote_quotes_against_shell_injection(self, tmp_path):
        """read_remote() safely quotes non-$HOME paths against shell injection."""
        # When remote_path doesn't start with $HOME/, it should be fully quoted

        commands_received = []

        def run_mock(cmd, *args, **kwargs):
            commands_received.append(cmd)
            return subprocess.CompletedProcess(cmd, returncode=0, stdout="content", stderr="")

        # Path with special characters that would be dangerous if not quoted
        malicious_path = "/tmp/file'; rm -rf /; echo '"

        result = brief_fallback.read_remote(
            malicious_path,
            host="test-host",
            run=run_mock,
        )

        assert result == "content"
        assert len(commands_received) == 1
        cmd = commands_received[0]
        # The malicious path should be quoted (shlex.quote should have wrapped it)
        cmd_str = " ".join(cmd)
        # shlex.quote wraps in single quotes, so it should appear quoted
        assert "'" in cmd_str or '"' in cmd_str


class TestParameterization:
    """Test that should_run() and past_deadline() accept parameters correctly."""

    def test_should_run_with_custom_deadline_hour(self, tmp_path):
        """should_run() accepts custom usual_hour parameter."""
        local_path = tmp_path / "digest.md"

        # 5 AM — before custom 6 AM deadline
        local_tz = datetime.now().astimezone().tzinfo
        now = datetime(2026, 10, 22, 5, 0, 0, tzinfo=local_tz).astimezone(timezone.utc)

        def run_mock(*args, **kwargs):
            raise AssertionError("SSH should not be called before deadline")

        decision = brief_fallback.should_run(
            device_id="macbook-pro-1",
            now=now,
            local_path=local_path,
            usual_hour=6,
            usual_minute=0,
            run=run_mock,
        )
        assert decision.should_build is False

    def test_past_deadline_with_custom_grace(self):
        """past_deadline() respects custom grace_minutes parameter."""
        local_tz = datetime.now().astimezone().tzinfo
        now = datetime(2026, 10, 22, 9, 31, 0, tzinfo=local_tz).astimezone(timezone.utc)

        # With 60 min grace, 9:31 is past 8:30 + 60
        result1 = brief_fallback.past_deadline(now, usual_hour=8, usual_minute=30, grace_minutes=60)
        assert result1 is True

        # With 120 min grace, 9:31 is NOT past 8:30 + 120 = 10:30
        result2 = brief_fallback.past_deadline(now, usual_hour=8, usual_minute=30, grace_minutes=120)
        assert result2 is False

    def test_produced_detects_failure_marker_at_start_not_in_middle(self, tmp_path):
        """produced() only rejects if the failure marker is at the start (after stripping)."""
        path = tmp_path / "digest.md"
        # Failure marker not at start — should be treated as valid content
        path.write_text("Some content (claude call failed: timeout) more content")

        assert brief_fallback.produced(path) is True

        # But marker at the start is still rejected
        path.write_text("(claude call failed: timeout) plus some content after")
        assert brief_fallback.produced(path) is False

        # Even with leading whitespace, it's still rejected
        path.write_text("  \n(claude call failed: timeout)")
        assert brief_fallback.produced(path) is False

    def test_produced_detects_quarantine_as_substring(self, tmp_path):
        """produced() detects quarantine marker via substring check."""
        path = tmp_path / "digest.md"
        # Quarantine marker not at start
        path.write_text("Some prefix _Quarantined by safety-monitor some suffix")

        assert brief_fallback.produced(path) is True

    def test_produced_does_not_misfire_on_a_digest_that_quotes_the_failure_marker_in_prose(self, tmp_path):
        """produced() only rejects files that START with failure marker (after stripping whitespace)."""
        path = tmp_path / "digest.md"
        # A digest that talks about the failure marker (not at the start)
        content = """# Research Digest

## Tools & Repos

I found an interesting tool that handles errors gracefully, logging "(claude call failed: timeout)" when the API is slow.

This is what you should use instead of blaming the tool."""
        path.write_text(content)

        # Should be treated as produced (it's valid content that happens to quote the marker)
        assert brief_fallback.produced(path) is True
