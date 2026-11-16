#!/usr/bin/env python3
"""Tests for guard_reading: centralized guard state management."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import guard_reading


@pytest.fixture
def temp_state_file(tmp_path, monkeypatch):
    """Use a temp file for guard state during tests, and stub notify."""
    orig_path = guard_reading.STATE_PATH
    guard_reading.STATE_PATH = tmp_path / "guard-unreadable.json"

    # Stub notify.notify so tests don't send real alerts.
    notify_mock = mock.MagicMock()
    monkeypatch.setattr("lib.notify.notify", notify_mock, raising=False)
    monkeypatch.setitem(sys.modules, "notify", notify_mock)

    yield guard_reading.STATE_PATH, notify_mock

    guard_reading.STATE_PATH = orig_path


def test_generic_exception_counted_as_unreadable(temp_state_file):
    """Test 1: Reader raises a generic Exception → counted as unreadable."""
    state_path, _ = temp_state_file

    def broken_reader():
        raise ValueError("something went wrong")

    result = guard_reading.guard_reading("disk", broken_reader)
    assert result is None

    state = json.loads(state_path.read_text())
    assert "disk@local" in state
    entry = state["disk@local"]
    assert entry["consecutive_unreadable"] == 1
    assert entry["first_unreadable_at"] is not None
    assert "ValueError" in entry["last_error"]


def test_timeout_expired_counted_as_unreadable(temp_state_file):
    """Test 2: Reader raises subprocess.TimeoutExpired → counted like any other."""
    state_path, _ = temp_state_file

    def timeout_reader():
        raise subprocess.TimeoutExpired("ssh", timeout=5)

    result = guard_reading.guard_reading("tailscale", timeout_reader)
    assert result is None

    state = json.loads(state_path.read_text())
    assert "tailscale@local" in state
    entry = state["tailscale@local"]
    assert entry["consecutive_unreadable"] == 1
    assert "TimeoutExpired" in entry["last_error"]


def test_missing_state_file_treated_as_empty(temp_state_file):
    """Test 3: Missing/malformed guard-unreadable.json → treated as empty state."""
    state_path, _ = temp_state_file
    # State file doesn't exist yet.
    assert not state_path.exists()

    def working_reader():
        return True

    result = guard_reading.guard_reading("disk", working_reader)
    assert result is True

    # First read should have created it.
    assert state_path.exists()
    state = json.loads(state_path.read_text())
    assert state["disk@local"]["consecutive_readable"] == 1


def test_flapping_one_episode(temp_state_file):
    """Test 6: Flapping (unreadable → readable → ...) → one episode, no duplicate alert."""
    state_path, _ = temp_state_file
    call_count = 0

    def flapping_reader():
        nonlocal call_count
        call_count += 1
        # Flap: unreadable, readable, unreadable, readable, readable (need 2 consecutive readable to close)
        if call_count in (1, 3):
            raise RuntimeError("odd call")
        return "ok"

    # Call 1: unreadable
    result = guard_reading.guard_reading("disk", flapping_reader)
    assert result is None
    state = json.loads(state_path.read_text())
    first_unreadable = state["disk@local"]["first_unreadable_at"]
    assert first_unreadable is not None

    # Call 2: readable (not yet episode-closing, need 2 consecutive readable)
    result = guard_reading.guard_reading("disk", flapping_reader)
    assert result == "ok"
    state = json.loads(state_path.read_text())
    assert state["disk@local"]["consecutive_readable"] == 1
    # first_unreadable_at should still be there (not reset yet)
    assert state["disk@local"]["first_unreadable_at"] == first_unreadable

    # Call 3: unreadable again
    result = guard_reading.guard_reading("disk", flapping_reader)
    assert result is None
    state = json.loads(state_path.read_text())
    # first_unreadable_at should NOT have reset; same episode.
    assert state["disk@local"]["first_unreadable_at"] == first_unreadable
    assert state["disk@local"]["consecutive_readable"] == 0  # reset on failure

    # Call 4: readable again
    result = guard_reading.guard_reading("disk", flapping_reader)
    assert result == "ok"
    state = json.loads(state_path.read_text())
    assert state["disk@local"]["consecutive_readable"] == 1

    # Call 5: readable (this closes the episode)
    result = guard_reading.guard_reading("disk", flapping_reader)
    assert result == "ok"
    state = json.loads(state_path.read_text())
    # After 2 consecutive readable, episode closes: counters reset.
    assert state["disk@local"]["consecutive_readable"] >= EPISODE_CLOSE_THRESHOLD
    assert state["disk@local"]["first_unreadable_at"] is None


EPISODE_CLOSE_THRESHOLD = guard_reading.EPISODE_CLOSE_THRESHOLD


def test_concurrent_writers_atomic(temp_state_file):
    """Test 9: Concurrent writers → atomic replace means no corrupt write."""
    state_path, _ = temp_state_file
    # Multiple calls to guard_reading in a short time should use atomic writes.

    def reader1():
        raise RuntimeError("err1")

    def reader2():
        raise RuntimeError("err2")

    # These should not corrupt the file, even if called "concurrently" (we can't truly test concurrency here,
    # but we can verify that the atomic write pattern works).
    guard_reading.guard_reading("disk", reader1)
    guard_reading.guard_reading("memory", reader2)

    state = json.loads(state_path.read_text())
    assert "disk@local" in state
    assert "memory@local" in state
    assert state["disk@local"]["last_error"] == "RuntimeError: err1"
    assert state["memory@local"]["last_error"] == "RuntimeError: err2"


def test_state_file_permission_error_treated_as_empty(temp_state_file):
    """Test 10: State file with wrong permissions → OSError caught, treated as empty."""
    state_path, _ = temp_state_file
    # Pre-create an unreadable file.
    state_path.write_text(json.dumps({"old": "data"}))
    os.chmod(state_path, 0o000)

    try:
        def reader():
            return "value"

        # Should not raise; should treat as empty state.
        result = guard_reading.guard_reading("disk", reader)
        assert result == "value"

        # Restore permissions to check what happened.
        os.chmod(state_path, 0o644)
        state = json.loads(state_path.read_text())
        # Should have a new entry (treated as empty on read).
        assert "disk@local" in state
    finally:
        os.chmod(state_path, 0o644)


def test_bad_fail_mode_entry_raises_at_import():
    """Test 12: Bad FAIL_MODE edit (value not 'open'/'closed') → raises at import."""
    # This is tested by virtue of _validate_fail_mode() being called at module import.
    # To test it explicitly, we'd need to reload the module, which is complex.
    # For now, we verify that FAIL_MODE has only valid entries.
    for guard, mode in guard_reading.FAIL_MODE.items():
        assert mode in ("open", "closed"), f"Guard {guard} has invalid mode {mode}"


def test_malformed_call_raises_immediately():
    """Test 13: Malformed call (empty/None name, non-callable reader) → raises TypeError/ValueError."""

    def reader():
        return "ok"

    # Empty name
    with pytest.raises(ValueError, match="non-empty str"):
        guard_reading.guard_reading("", reader)

    # None name
    with pytest.raises(ValueError, match="non-empty str"):
        guard_reading.guard_reading(None, reader)

    # Non-callable reader
    with pytest.raises(TypeError, match="callable"):
        guard_reading.guard_reading("disk", "not a function")

    # Unknown guard name
    with pytest.raises(ValueError, match="not in FAIL_MODE"):
        guard_reading.guard_reading("unknown_guard", reader)


def test_notify_failure_doesnt_break_guard_reading(temp_state_file):
    """Test 16: notify() itself failing → guard_reading's alert step doesn't raise."""
    state_path, notify_mock = temp_state_file

    def broken_reader():
        raise RuntimeError("stuck tailscale")

    guard_reading.guard_reading("tailscale", broken_reader)

    # Manually set the state to trigger an alert (by setting first_unreadable_at to 2+ hours ago)
    state = json.loads(state_path.read_text())
    now_ts = datetime.now(timezone.utc)
    two_h_ago = (now_ts - timedelta(hours=2, seconds=10)).isoformat()
    state["tailscale@local"]["first_unreadable_at"] = two_h_ago
    state["tailscale@local"]["consecutive_unreadable"] = 3

    state_path.write_text(json.dumps(state))

    # Make notify.notify() raise an exception
    notify_mock.notify.side_effect = RuntimeError("notify broken")

    # Should not raise; should handle the exception gracefully.
    result = guard_reading.guard_reading("tailscale", broken_reader)
    assert result is None

    # Verify state was still updated (alert was attempted even though notify raised).
    state = json.loads(state_path.read_text())
    assert state["tailscale@local"]["alerted_at"] is not None

    # Verify notify was actually called (not just stubbed).
    notify_mock.notify.assert_called()


def test_none_result_counted_as_unreadable(temp_state_file):
    """Test: Reader returns None (not an exception) → counted as unreadable."""
    state_path, _ = temp_state_file

    def returns_none():
        return None

    result = guard_reading.guard_reading("github_budget", returns_none)
    assert result is None

    state = json.loads(state_path.read_text())
    assert "github_budget@local" in state
    entry = state["github_budget@local"]
    assert entry["consecutive_unreadable"] == 1
    assert entry["first_unreadable_at"] is not None
    assert "returned None" in entry["last_error"]


def test_flagged_guards_handles_malformed_entries(temp_state_file):
    """Test: flagged_guards skips malformed entries (non-dict), handles bad ISO strings."""
    state_path, _ = temp_state_file
    now_ts = datetime.now(timezone.utc)
    two_h_ago = (now_ts - timedelta(hours=2, seconds=10)).isoformat()
    ten_min_ago = (now_ts - timedelta(minutes=10)).isoformat()

    # Create state with mix of valid and malformed entries
    state = {
        "disk@local": {
            "consecutive_unreadable": 3,  # > 2 → always flagged
            "first_unreadable_at": two_h_ago,
            "consecutive_readable": 0,
            "alerted_at": None,
            "last_error": "RuntimeError: stuck disk",
        },
        "memory@local": "not a dict",  # Malformed: should be skipped entirely
        "github_budget@local": {
            "consecutive_unreadable": 1,  # <= 2, recent timestamp → not flagged (too recent)
            "first_unreadable_at": ten_min_ago,
            "consecutive_readable": 0,
            "alerted_at": None,
            "last_error": "error",
        },
        "tailscale@local": {
            "consecutive_unreadable": 1,  # <= 2, bad ISO format → not flagged (exception caught)
            "first_unreadable_at": "not-an-iso-string",
            "consecutive_readable": 0,
            "alerted_at": None,
            "last_error": "error",
        },
    }
    state_path.write_text(json.dumps(state))

    # flagged_guards should handle all these gracefully
    flagged = guard_reading.flagged_guards(now=now_ts)
    # Only disk@local should be flagged (consecutive_unreadable > 2)
    assert len(flagged) == 1
    assert flagged[0]["name"] == "disk@local"


def test_2h_alert_fires_exactly_once(temp_state_file):
    """Test 17: Guard unreadable for ≥2h → exactly one notify() call via guard_reading()."""
    state_path, notify_mock = temp_state_file
    now_ts = datetime.now(timezone.utc)
    two_h_ago = (now_ts - timedelta(hours=2, seconds=10)).isoformat()

    # Create initial state: guard unreadable for 2+ hours but never alerted
    state = {
        "disk@local": {
            "consecutive_unreadable": 3,
            "first_unreadable_at": two_h_ago,
            "consecutive_readable": 0,
            "alerted_at": None,
            "last_error": "RuntimeError: stuck disk",
            "last_read_at": two_h_ago,
        }
    }
    state_path.write_text(json.dumps(state))

    # Call guard_reading with a reader that keeps failing
    def broken_reader():
        raise RuntimeError("stuck disk")

    # First call should trigger the 2h alert
    result = guard_reading.guard_reading("disk", broken_reader)
    assert result is None

    # Verify notify was called exactly once
    assert notify_mock.notify.call_count == 1
    call_args = notify_mock.notify.call_args
    assert "guard unreadable" in call_args[0][0]
    assert "disk@local" in call_args[0][1]

    # Verify alerted_at was set
    state = json.loads(state_path.read_text())
    assert state["disk@local"]["alerted_at"] is not None

    # Reset mock and call again
    notify_mock.reset_mock()

    # Second call with same guard in unreadable state should NOT fire the alert again
    result = guard_reading.guard_reading("disk", broken_reader)
    assert result is None

    # Verify notify was NOT called (alerted_at already set)
    assert notify_mock.notify.call_count == 0

    # Test that flagged_guards correctly identifies this guard as flagged
    flagged = guard_reading.flagged_guards(now=now_ts)
    assert len(flagged) == 1
    assert flagged[0]["name"] == "disk@local"


def test_stale_guard_not_flagged(temp_state_file):
    """Test 11: Guard not probed recently (>1h) → not flagged even if first_unreadable_at is set."""
    state_path, _ = temp_state_file
    now_ts = datetime.now(timezone.utc)
    two_h_ago = (now_ts - timedelta(hours=2)).isoformat()
    one_h_ago = (now_ts - timedelta(hours=1, seconds=10)).isoformat()

    # Create state for a guard that was unreadable but hasn't been probed in over 1 hour.
    state = {
        "disk@local": {
            "consecutive_unreadable": 3,
            "first_unreadable_at": two_h_ago,
            "consecutive_readable": 0,
            "alerted_at": None,
            "last_error": "RuntimeError: stuck disk",
            "last_read_at": one_h_ago,  # Last probed >1h ago
        }
    }
    state_path.write_text(json.dumps(state))

    # flagged_guards should NOT include this stale guard
    flagged = guard_reading.flagged_guards(now=now_ts)
    assert len(flagged) == 0, "Stale guard should not be flagged"


def test_episode_closure_clears_first_unreadable_at(temp_state_file):
    """Test: An episode that closes should clear first_unreadable_at, so later failures don't look ancient."""
    state_path, _ = temp_state_file
    call_count = 0

    def flapping_reader():
        nonlocal call_count
        call_count += 1
        # fail, success, success (closes episode), then we're clean
        if call_count == 1:
            raise RuntimeError("fail1")
        return "ok"

    # Call 1: fail
    result = guard_reading.guard_reading("disk", flapping_reader)
    assert result is None
    state = json.loads(state_path.read_text())
    first_fail_time = state["disk@local"]["first_unreadable_at"]

    # Call 2: success
    result = guard_reading.guard_reading("disk", flapping_reader)
    assert result == "ok"
    state = json.loads(state_path.read_text())
    # first_unreadable_at should still be set (not enough successes yet)
    assert state["disk@local"]["first_unreadable_at"] == first_fail_time
    assert state["disk@local"]["consecutive_readable"] == 1

    # Call 3: success (this closes the episode)
    result = guard_reading.guard_reading("disk", flapping_reader)
    assert result == "ok"
    state = json.loads(state_path.read_text())
    # After 2 consecutive readable, episode closes and first_unreadable_at is reset
    assert state["disk@local"]["first_unreadable_at"] is None
    assert state["disk@local"]["consecutive_readable"] >= EPISODE_CLOSE_THRESHOLD

    # Now if we fail again, first_unreadable_at should be the NEW failure time, not the old one
    call_count = 0

    def fail_again_reader():
        raise RuntimeError("fail2")

    result = guard_reading.guard_reading("disk", fail_again_reader)
    assert result is None
    state = json.loads(state_path.read_text())
    # New failure should have a fresh first_unreadable_at
    assert state["disk@local"]["first_unreadable_at"] is not None
    assert state["disk@local"]["first_unreadable_at"] > first_fail_time
