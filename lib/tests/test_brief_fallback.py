"""Fallback brief builder — standby machine covers when primary is down."""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import brief_fallback as bf


# ── Test 1: _infer_remote_path constructs the right SSH prefix ──────────────────────────────

def test_infer_remote_path_constructs_home_prefix_and_quoted_remainder(tmp_path):
    home = Path.home()
    local_path = home / ".claude" / "briefs" / "2026-10-25.md"
    prefix, remainder = bf._infer_remote_path(local_path)
    assert prefix == "$HOME"
    assert remainder == ".claude/briefs/2026-10-25.md"


# ── Test 2: _infer_remote_path rejects paths outside home ──────────────────────────────────

def test_infer_remote_path_rejects_paths_outside_home():
    with pytest.raises(ValueError, match="is not under"):
        bf._infer_remote_path("/tmp/foo")


# ── Test 3: read_remote returns None on path outside home ────────────────────────────────

def test_read_remote_returns_none_on_path_outside_home():
    result = bf.read_remote("/tmp/foo", "gils-mac-mini")
    assert result is None


# ── Test 4: read_remote returns None on SSH timeout ──────────────────────────────────

def test_read_remote_returns_none_on_timeout():
    mock_run = MagicMock(side_effect=TimeoutError())
    result = bf.read_remote(Path.home() / ".claude" / "briefs" / "2026-10-25.md",
                            "gils-mac-mini", run=mock_run)
    assert result is None


# ── Test 5: read_remote returns None on SSH failure ──────────────────────────────────

def test_read_remote_returns_none_on_ssh_failure():
    mock_result = MagicMock(returncode=1, stdout="")
    mock_run = MagicMock(return_value=mock_result)
    result = bf.read_remote(Path.home() / ".claude" / "briefs" / "2026-10-25.md",
                            "gils-mac-mini", run=mock_run)
    assert result is None


# ── Test 6: read_remote returns file content on success ──────────────────────────────────

def test_read_remote_returns_content_on_success():
    content = "# Morning brief\n\nSomething happened."
    mock_result = MagicMock(returncode=0, stdout=content)
    mock_run = MagicMock(return_value=mock_result)
    result = bf.read_remote(Path.home() / ".claude" / "briefs" / "2026-10-25.md",
                            "gils-mac-mini", run=mock_run)
    assert result == content
    # Verify the SSH command was constructed correctly
    call_args = mock_run.call_args
    assert "ssh" in call_args[0][0]
    assert "gils-mac-mini" in call_args[0][0]


# ── Test 7: read_remote quoting handles special characters ──────────────────────────────

def test_read_remote_quotes_special_characters():
    mock_result = MagicMock(returncode=0, stdout="content")
    mock_run = MagicMock(return_value=mock_result)
    # Path with spaces and special chars
    bf.read_remote(Path.home() / ".claude" / "briefs" / "my brief (2026-10-25).md",
                   "gils-mac-mini", run=mock_run)
    call_args = mock_run.call_args
    cmd = " ".join(call_args[0][0])
    # The path should be quoted
    assert "'" in cmd or '"' in cmd


# ── Test 8: produced() returns False for missing files ──────────────────────────────────

def test_produced_returns_false_for_missing_files(tmp_path):
    missing_file = tmp_path / "does-not-exist.md"
    assert not bf.produced(missing_file)


# ── Test 9: produced() returns False for empty files ──────────────────────────────────

def test_produced_returns_false_for_empty_files(tmp_path):
    empty_file = tmp_path / "empty.md"
    empty_file.write_text("")
    assert not bf.produced(empty_file)


# ── Test 10: produced() returns False for whitespace-only files ──────────────────────────

def test_produced_returns_false_for_whitespace_only_files(tmp_path):
    ws_file = tmp_path / "whitespace.md"
    ws_file.write_text("   \n\n  \t  ")
    assert not bf.produced(ws_file)


# ── Test 11: produced() returns False for files containing failure marker ──────────────

def test_produced_returns_false_for_claude_call_failure(tmp_path):
    failed_file = tmp_path / "failed.md"
    failed_file.write_text("# Digest\n\n(claude call failed: timeout)")
    assert not bf.produced(failed_file)


# ── Test 12: produced() returns True for valid files ──────────────────────────────────

def test_produced_returns_true_for_valid_files(tmp_path):
    valid_file = tmp_path / "valid.md"
    valid_file.write_text("# Morning brief\n\nSome content here.")
    assert bf.produced(valid_file)


# ── Test 13: past_deadline returns False when before deadline ──────────────────────────

def test_past_deadline_returns_false_when_before_deadline():
    # Use local time since past_deadline() converts with astimezone()
    now = datetime(2026, 10, 25, 8, 30).astimezone()  # Before usual time
    assert not bf.past_deadline(now, usual_hour=9, usual_minute=15, grace_minutes=60)


# ── Test 14: past_deadline returns False within grace period ──────────────────────────

def test_past_deadline_returns_false_within_grace():
    # Use local time since past_deadline() converts with astimezone()
    now = datetime(2026, 10, 25, 10, 0).astimezone()  # 45 min after 09:15
    assert not bf.past_deadline(now, usual_hour=9, usual_minute=15, grace_minutes=60)


# ── Test 15: past_deadline returns True after grace period ───────────────────────────

def test_past_deadline_returns_true_after_grace():
    # Use local time since past_deadline() converts with astimezone()
    now = datetime(2026, 10, 25, 10, 30).astimezone()  # 75 min after 09:15
    assert bf.past_deadline(now, usual_hour=9, usual_minute=15, grace_minutes=60)


# ── Test 16: should_run returns True for primary, empty reason ───────────────────────

@patch('brief_fallback.scanner_role.is_primary', return_value=True)
@patch('brief_fallback.machine_profile.registry_id', return_value='mac-mini')
def test_should_run_primary_always_runs(mock_id, mock_is_primary):
    should, reason = bf.should_run(Path.home() / ".claude" / "briefs" / "test.md",
                                   usual_hour=9, usual_minute=15)
    assert should is True
    assert reason == ""


# ── Test 17: should_run standby before deadline explains why ────────────────────────

@patch('brief_fallback.scanner_role.is_primary', return_value=False)
@patch('brief_fallback.machine_profile.registry_id', return_value='macbook-pro')
def test_should_run_standby_before_deadline(mock_id, mock_is_primary):
    now = datetime(2026, 10, 25, 9, 0).astimezone()  # Before 09:15 + 60 min grace
    should, reason = bf.should_run(Path.home() / ".claude" / "briefs" / "test.md",
                                   usual_hour=9, usual_minute=15, now=now)
    assert should is False
    assert "primary hasn't reached deadline yet" in reason


# ── Test 18: should_run standby after deadline with local file returns already covered ──

@patch('brief_fallback.scanner_role.is_primary', return_value=False)
@patch('brief_fallback.machine_profile.registry_id', return_value='macbook-pro')
def test_should_run_standby_with_local_file(mock_id, mock_is_primary, tmp_path):
    local_file = tmp_path / "brief.md"
    local_file.write_text("# Morning brief\n\nSome content")
    now = datetime(2026, 10, 25, 10, 30).astimezone()  # After deadline
    should, reason = bf.should_run(local_file, usual_hour=9, usual_minute=15, now=now)
    assert should is False
    assert "already produced" in reason


# ── Test 19: should_run standby after deadline without local file runs fallback ──────

@patch('brief_fallback.scanner_role.is_primary', return_value=False)
@patch('brief_fallback.machine_profile.registry_id', return_value='macbook-pro')
@patch('brief_fallback.machine_profile.remote_macs', return_value={})
def test_should_run_standby_without_local_file(mock_remote, mock_id, mock_is_primary, tmp_path):
    local_file = tmp_path / "brief.md"
    # File doesn't exist
    now = datetime(2026, 10, 25, 10, 30).astimezone()
    should, reason = bf.should_run(local_file, usual_hour=9, usual_minute=15, now=now)
    assert should is True
    assert "fallback: covering for the primary" in reason


# ── Test 20: should_run checks primary remote state ────────────────────────────────

@patch('brief_fallback.read_remote')
@patch('brief_fallback.scanner_role.is_primary')
@patch('brief_fallback.machine_profile.registry_id', return_value='macbook-pro')
@patch('brief_fallback.machine_profile.remote_macs')
def test_should_run_checks_primary_remote(mock_remote_macs, mock_id, mock_is_primary, mock_read_remote, tmp_path):
    # Set up so that mac-mini is primary
    def is_primary_side_effect(dev_id):
        return dev_id == 'mac-mini'

    mock_is_primary.side_effect = is_primary_side_effect
    mock_remote_macs.return_value = {
        'mac-mini': {'tailscale_hostname': 'gils-mac-mini'}
    }
    mock_read_remote.return_value = "# Morning brief\n\nPrimary built this"

    local_file = tmp_path / "brief.md"
    now = datetime(2026, 10, 25, 10, 30).astimezone()
    should, reason = bf.should_run(local_file, usual_hour=9, usual_minute=15, now=now)
    assert should is False
    assert "primary already built it" in reason
    mock_read_remote.assert_called_once()
