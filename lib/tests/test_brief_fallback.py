"""Tests for lib/brief_fallback.py's fallback decision logic. Run via:
    ~/.agents/venv/bin/python -m pytest lib/tests/test_brief_fallback.py -v
"""
from __future__ import annotations
import subprocess
import sys
from pathlib import Path
from datetime import datetime, timedelta, timezone
from unittest.mock import patch, MagicMock

LIB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LIB))

import brief_fallback as bf  # noqa: E402


# ── produced() tests ─────────────────────────────────────────────────────────

def test_produced_file_not_exists(tmp_path):
    """produced() returns False when file does not exist."""
    path = tmp_path / "nonexistent.md"
    assert bf.produced(path) is False


def test_produced_file_empty(tmp_path):
    """produced() returns False when file is empty."""
    path = tmp_path / "empty.md"
    path.write_text("")
    assert bf.produced(path) is False


def test_produced_file_whitespace_only(tmp_path):
    """produced() returns False when file has only whitespace."""
    path = tmp_path / "whitespace.md"
    path.write_text("   \n\n  \t  ")
    assert bf.produced(path) is False


def test_produced_file_with_failure_marker(tmp_path):
    """produced() returns False when file contains '(claude call failed:' marker."""
    path = tmp_path / "failed.md"
    path.write_text("# Some content\n\n(claude call failed: timeout)\n\nMore text")
    assert bf.produced(path) is False


def test_produced_file_valid(tmp_path):
    """produced() returns True when file has valid content and no failure markers."""
    path = tmp_path / "valid.md"
    path.write_text("# Morning brief\n\nSome actual content here.")
    assert bf.produced(path) is True


def test_produced_read_error(tmp_path):
    """produced() returns False on read error."""
    path = tmp_path / "noread.md"
    path.write_text("content")
    with patch.object(Path, "read_text", side_effect=OSError("Permission denied")):
        assert bf.produced(path) is False


# ── _is_valid_content() tests ────────────────────────────────────────────────

def test_is_valid_content_none():
    """_is_valid_content returns False for None."""
    assert bf._is_valid_content(None) is False


def test_is_valid_content_empty_string():
    """_is_valid_content returns False for empty string."""
    assert bf._is_valid_content("") is False


def test_is_valid_content_whitespace_only():
    """_is_valid_content returns False for whitespace-only string."""
    assert bf._is_valid_content("   \n  \t  ") is False


def test_is_valid_content_with_failure_marker():
    """_is_valid_content returns False when content contains failure marker."""
    assert bf._is_valid_content("# Content\n(claude call failed: timeout)") is False


def test_is_valid_content_valid():
    """_is_valid_content returns True for valid content."""
    assert bf._is_valid_content("# Morning brief\n\nValid content.") is True


# ── _quote_remote_path() tests ───────────────────────────────────────────────

def test_quote_remote_path_with_home_prefix():
    """_quote_remote_path preserves $HOME prefix."""
    path = "$HOME/.claude/briefs/2026-10-24.md"
    quoted = bf._quote_remote_path(path)
    assert quoted.startswith("$HOME/")
    # Verify the rest is quoted
    assert "'" in quoted or '"' in quoted or "\\" in quoted


def test_quote_remote_path_without_home_prefix():
    """_quote_remote_path quotes absolute paths."""
    path = "/home/user/.claude/briefs/2026-10-24.md"
    quoted = bf._quote_remote_path(path)
    # Should be quoted for shell safety
    assert "'" in quoted or '"' in quoted or "\\" in quoted


def test_quote_remote_path_shell_injection():
    """_quote_remote_path prevents shell injection attacks."""
    path = "$HOME/.claude/briefs/test.md; rm -rf /"
    quoted = bf._quote_remote_path(path)
    # The semicolon and command should be safely quoted
    assert "'" in quoted or '"' in quoted or "\\" in quoted
    # Should not directly contain unquoted semicolon-command
    rest = quoted.replace("$HOME/", "")
    assert rest != "test.md; rm -rf /" and "rm -rf" not in rest.split("'")[0] if "'" in rest else True


def test_quote_remote_path_home_expansion():
    """_quote_remote_path preserves $HOME for remote expansion."""
    path = "$HOME/.claude/briefs/2026-10-24.md"
    quoted = bf._quote_remote_path(path)
    # $HOME should remain unquoted so the shell expands it on the remote machine
    assert quoted.startswith("$HOME/")
    # But the rest should be quoted
    assert quoted != path  # Not identical; the filename part is quoted


# ── should_run() tests ───────────────────────────────────────────────────────

def test_should_run_on_primary_returns_true_primary():
    """should_run returns True when running on the primary (mini)."""
    with patch("brief_fallback.machine_profile.registry_id", return_value="mac-mini-primary"):
        with patch("brief_fallback.scanner_role.is_primary", return_value=True):
            path = Path("/tmp/brief.md")
            should_run, reason = bf.should_run(path)
            assert should_run is True
            assert "primary" in reason.lower()


def test_should_run_identity_lookup_fails():
    """should_run returns True with defensive reason when identity lookup fails."""
    with patch("brief_fallback.machine_profile.registry_id", side_effect=Exception("lookup failed")):
        path = Path("/tmp/brief.md")
        should_run, reason = bf.should_run(path)
        assert should_run is True
        assert "defensive" in reason.lower()


def test_should_run_file_already_produced_locally():
    """should_run returns False when output file was already produced."""
    with patch("brief_fallback.machine_profile.registry_id", return_value="laptop"):
        with patch("brief_fallback.scanner_role.is_primary", return_value=False):
            path = Path("/tmp/brief.md")
            with patch("brief_fallback.produced") as mock_prod:
                mock_prod.return_value = True
                should_run, reason = bf.should_run(path)
                assert should_run is False
                assert "already produced" in reason.lower()


def test_should_run_file_produced_on_primary():
    """should_run returns False when primary already produced the file."""
    with patch("brief_fallback.machine_profile.registry_id", return_value="laptop"):
        with patch("brief_fallback.scanner_role.is_primary", return_value=False):
            path = Path("/tmp/brief.md")
            with patch("brief_fallback.produced", return_value=False):
                with patch("brief_fallback._read_primary_output", return_value="# Valid content"):
                    with patch("brief_fallback._is_valid_content", return_value=True):
                        should_run, reason = bf.should_run(path)
                        assert should_run is False
                        assert "already produced on primary" in reason.lower()


def test_past_deadline_not_yet():
    """past_deadline returns False when not yet past the deadline."""
    # Create a time 30 minutes before the deadline (9:45 - 30 min = 9:15)
    # We need to be in the local timezone that past_deadline will convert to
    from datetime import datetime as dt_cls, timezone as tz_cls, timedelta
    now_local = datetime.now(timezone.utc).astimezone()
    # Set to 09:15 local time, deadline is 09:45
    test_time = now_local.replace(hour=9, minute=15, second=0, microsecond=0)
    assert bf.past_deadline(test_time, usual_hour=9, usual_minute=45, grace_minutes=60) is False


def test_past_deadline_yes():
    """past_deadline returns True when past deadline+grace."""
    # Create a time 15 minutes after the deadline+grace window
    # deadline 09:45 + 60 min grace = 10:45, so test at 11:00
    now_local = datetime.now(timezone.utc).astimezone()
    test_time = now_local.replace(hour=11, minute=0, second=0, microsecond=0)
    assert bf.past_deadline(test_time, usual_hour=9, usual_minute=45, grace_minutes=60) is True


def test_should_run_returns_tuple():
    """should_run always returns (bool, str) tuple."""
    with patch("brief_fallback.machine_profile.registry_id", return_value="laptop"):
        with patch("brief_fallback.scanner_role.is_primary", return_value=False):
            path = Path("/tmp/brief.md")
            with patch("brief_fallback.produced", return_value=False):
                with patch("brief_fallback._read_primary_output", return_value=None):
                    result = bf.should_run(path)
                    assert isinstance(result, tuple)
                    assert len(result) == 2
                    assert isinstance(result[0], bool)
                    assert isinstance(result[1], str)


# ── _infer_remote_path() tests ───────────────────────────────────────────────

def test_infer_remote_path_briefs():
    """_infer_remote_path converts local path to remote $HOME-relative path."""
    home = Path.home()
    local_path = home / ".claude" / "briefs" / "2026-10-24.md"
    remote = bf._infer_remote_path(local_path)
    assert "$HOME" in remote
    assert "2026-10-24.md" in remote
    assert not str(home) in remote  # Should not contain absolute path


def test_infer_remote_path_daily_digest():
    """_infer_remote_path works for daily-digest paths."""
    home = Path.home()
    local_path = home / ".claude" / "daily-digest" / "2026-10-24.md"
    remote = bf._infer_remote_path(local_path)
    assert "$HOME" in remote
    assert "daily-digest" in remote
    assert "2026-10-24.md" in remote


# ── read_remote() tests ──────────────────────────────────────────────────────

def test_read_remote_success():
    """read_remote returns file content on successful SSH read."""
    import subprocess as sp_module
    mock_run = MagicMock()
    mock_proc = MagicMock()
    mock_proc.returncode = 0
    mock_proc.stdout = "# Content from remote\n"
    mock_run.return_value = mock_proc

    result = bf.read_remote("$HOME/.claude/briefs/test.md", "remote.host", run=mock_run)
    assert result == "# Content from remote\n"
    # Verify SSH was called
    assert mock_run.called
    call_args = mock_run.call_args
    # The command should have ssh as the first element and contain the host
    assert "ssh" in call_args[0][0]
    assert "remote.host" in call_args[0][0]


def test_read_remote_ssh_failure():
    """read_remote returns None on SSH command failure."""
    mock_run = MagicMock()
    mock_proc = MagicMock()
    mock_proc.returncode = 1
    mock_run.return_value = mock_proc

    result = bf.read_remote("$HOME/.claude/briefs/test.md", "remote.host", run=mock_run)
    assert result is None


def test_read_remote_timeout():
    """read_remote returns None on timeout."""
    mock_run = MagicMock(side_effect=subprocess.TimeoutExpired("ssh", 15))
    result = bf.read_remote("$HOME/.claude/briefs/test.md", "remote.host", run=mock_run)
    assert result is None


def test_read_remote_empty_path():
    """read_remote returns None when path is empty."""
    result = bf.read_remote("", "remote.host")
    assert result is None


def test_read_remote_empty_host():
    """read_remote returns None when host is empty."""
    result = bf.read_remote("$HOME/.claude/briefs/test.md", "")
    assert result is None


def test_should_run_clock_skew_regression():
    """should_run correctly handles clock skew where now is 1 second before deadline+grace."""
    with patch("brief_fallback.machine_profile.registry_id", return_value="laptop"):
        with patch("brief_fallback.scanner_role.is_primary", return_value=False):
            with patch("brief_fallback.produced", return_value=False):
                with patch("brief_fallback._read_primary_output", return_value=None):
                    # Create a test time that is exactly 1 second before the deadline+grace
                    now_local = datetime.now(timezone.utc).astimezone()
                    deadline = now_local.replace(hour=9, minute=45, second=0, microsecond=0)
                    # 60 minutes grace: deadline+grace = 10:45
                    deadline_with_grace = deadline + timedelta(minutes=60)
                    test_time = deadline_with_grace - timedelta(seconds=1)

                    # Should still return False (too early)
                    should_run, reason = bf.should_run(Path("/tmp/brief.md"), usual_hour=9, usual_minute=45, grace_minutes=60, now=test_time)
                    assert should_run is False
                    assert "too early" in reason.lower()

                    # One second later should trigger
                    test_time_after = test_time + timedelta(seconds=2)
                    should_run, reason = bf.should_run(Path("/tmp/brief.md"), usual_hour=9, usual_minute=45, grace_minutes=60, now=test_time_after)
                    assert should_run is True


def test_should_run_concurrent_invocations():
    """should_run behaves consistently across concurrent invocations with the same now time."""
    with patch("brief_fallback.machine_profile.registry_id", return_value="laptop"):
        with patch("brief_fallback.scanner_role.is_primary", return_value=False):
            with patch("brief_fallback.produced", return_value=False):
                with patch("brief_fallback._read_primary_output", return_value=None):
                    # Use a fixed now time
                    now_local = datetime.now(timezone.utc).astimezone()
                    test_time = now_local.replace(hour=11, minute=0, second=0, microsecond=0)

                    # Call twice with the same now value
                    result1 = bf.should_run(Path("/tmp/brief.md"), usual_hour=9, usual_minute=45, grace_minutes=60, now=test_time)
                    result2 = bf.should_run(Path("/tmp/brief.md"), usual_hour=9, usual_minute=45, grace_minutes=60, now=test_time)

                    # Should be identical
                    assert result1 == result2


def test_fallback_builds_once_then_stays_idle():
    """Simulates the full fallback flow: first call builds, second call sees output and stops."""
    tmp_path = Path("/tmp/test_fallback_flow")
    tmp_path.mkdir(exist_ok=True)
    brief_path = tmp_path / "brief.md"

    try:
        with patch("brief_fallback.machine_profile.registry_id", return_value="laptop"):
            with patch("brief_fallback.scanner_role.is_primary", return_value=False):
                now_local = datetime.now(timezone.utc).astimezone()
                test_time = now_local.replace(hour=11, minute=0, second=0, microsecond=0)

                # First call: file doesn't exist, primary has nothing, we're past deadline
                with patch("brief_fallback._read_primary_output", return_value=None):
                    should_run, reason = bf.should_run(brief_path, usual_hour=9, usual_minute=45, grace_minutes=60, now=test_time)
                    assert should_run is True

                # Simulate the build: write the file
                brief_path.write_text("# Morning brief\n\nBuilt by fallback")

                # Second call: file now exists, so fallback should not run again
                with patch("brief_fallback._read_primary_output", return_value=None):
                    should_run, reason = bf.should_run(brief_path, usual_hour=9, usual_minute=45, grace_minutes=60, now=test_time)
                    assert should_run is False
                    assert "already produced" in reason.lower()
    finally:
        import shutil
        shutil.rmtree(tmp_path, ignore_errors=True)
