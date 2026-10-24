"""Tests for brief_fallback module (fallback builder gate for digests and morning brief)."""
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import MagicMock
import brief_fallback as bf


# Test 1: _infer_remote_path with home-relative paths
def test_infer_remote_path_home_relative(tmp_path):
    """_infer_remote_path() converts home-relative paths to $HOME/..."""
    home = Path.home()
    local_path = home / ".claude" / "briefs" / "2026-10-24.md"
    result = bf._infer_remote_path(local_path)
    assert result == "$HOME/.claude/briefs/2026-10-24.md"


# Test 2: read_remote returns None on SSH failure
def test_read_remote_ssh_failure():
    """read_remote() returns None when SSH fails."""
    mock_run = MagicMock()
    mock_run.return_value.returncode = 1
    mock_run.return_value.stderr = "Connection refused"

    result = bf.read_remote("$HOME/.claude/briefs/today.md", host="test-host", run=mock_run)
    assert result is None


# Test 3: produced() checks local file first
def test_produced_local_file_exists(tmp_path):
    """produced() returns True if local file exists with content."""
    local_path = tmp_path / "digest.md"
    local_path.write_text("# Today's Digest\n\nSome content here.")

    result = bf.produced(local_path)
    assert result is True


# Test 5: produced() falls back to remote when local missing
def test_produced_remote_fallback():
    """produced() checks remote file when local is missing."""
    local_path = Path("/nonexistent/digest.md")

    mock_run = MagicMock()
    mock_run.return_value.returncode = 0
    mock_run.return_value.stdout = "# Remote Digest\n\nContent from primary."

    result = bf.produced(local_path, host="test-host", run=mock_run)
    assert result is True


# Test 6: produced() detects failure placeholders
def test_produced_rejects_failure_placeholders(tmp_path):
    """produced() returns False for error placeholder strings."""
    # Test "(claude call failed:...)" placeholder
    local_path = tmp_path / "digest.md"
    local_path.write_text("(claude call failed: timeout)")
    assert bf.produced(local_path) is False

    # Test empty file
    local_path.write_text("")
    assert bf.produced(local_path) is False

    # Test whitespace-only file
    local_path.write_text("   \n  \n")
    assert bf.produced(local_path) is False


# Test 9: past_deadline before deadline
def test_past_deadline_before(utc_tz):
    """past_deadline() returns False when before deadline."""
    # Use UTC timezone to ensure consistent timing across machines
    now = datetime(2026, 10, 24, 8, 15, tzinfo=timezone.utc)
    result = bf.past_deadline(now, usual_hour=8, usual_minute=30, grace_minutes=60)
    assert result is False


# Test 10: past_deadline after deadline with grace
def test_past_deadline_after():
    """past_deadline() returns True after deadline + grace period."""
    from datetime import timedelta

    # Create a time that's definitely after 8:30 + 60m = 9:30 local time
    # Use current local time and add enough time to ensure we're past 9:30
    from datetime import datetime as dt
    now_local = datetime.now(timezone.utc).astimezone()

    # Replace to a time definitely after 9:30 (use 14:00 which should always be after 9:30)
    now_test = now_local.replace(hour=14, minute=0, second=0, microsecond=0)
    result = bf.past_deadline(now_test, usual_hour=8, usual_minute=30, grace_minutes=60)
    assert result is True


# Test 11: should_run returns primary decision for primary device
def test_should_run_primary(utc_tz):
    """should_run() returns primary decision when called from primary."""
    decision = bf.should_run(device_id="mac-mini-1", now=datetime(2026, 10, 24, 9, 0, tzinfo=timezone.utc))
    assert decision.should_build is True
    assert "primary" in decision.reason


# Test 12: should_run returns standby before deadline
def test_should_run_standby_before_deadline(tmp_path, utc_tz):
    """should_run() returns standby decision before deadline."""
    now = datetime(2026, 10, 24, 8, 0, tzinfo=timezone.utc)  # Before 8:30
    local_path = tmp_path / "digest.md"

    decision = bf.should_run(
        device_id="macbook-pro-1",
        now=now,
        local_path=local_path,
        usual_hour=8,
        usual_minute=30,
        grace_minutes=60,
        run=MagicMock()
    )
    assert decision.should_build is False
    assert "standby" in decision.reason and "before deadline" in decision.reason


# Test 13: should_run returns fallback after deadline when remote missing
def test_should_run_fallback_after_deadline_missing_remote():
    """should_run() returns fallback decision after deadline + grace when remote not produced."""
    # Use a time that's definitely after 9:30 local time (8:30 + 60m)
    # Create a local time and ensure it's after the deadline
    now_local = datetime.now(timezone.utc).astimezone()
    now = now_local.replace(hour=14, minute=0, second=0, microsecond=0)

    local_path = Path("/nonexistent/digest.md")

    mock_run = MagicMock()
    mock_run.return_value.returncode = 1  # SSH fails

    decision = bf.should_run(
        device_id="macbook-pro-1",
        now=now,
        local_path=local_path,
        usual_hour=8,
        usual_minute=30,
        grace_minutes=60,
        run=mock_run
    )
    assert decision.should_build is True
    assert "fallback" in decision.reason
