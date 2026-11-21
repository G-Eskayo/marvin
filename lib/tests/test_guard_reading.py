#!/usr/bin/env python3
"""Tests for guard_reading module."""
import json
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import guard_reading as gr


def test_guard_reading_success():
    """guard_reading with error=None returns value unchanged."""
    with tempfile.TemporaryDirectory() as tmpdir:
        log_path = Path(tmpdir) / "guard-readings.jsonl"
        gr.LOG_PATH = log_path

        result = gr.guard_reading("disk:local-pipeline", 42.5, error=None)
        assert result == 42.5, f"Expected 42.5, got {result}"

        # Check that the log was written
        assert log_path.exists(), "Log file should exist"
        lines = log_path.read_text().strip().split('\n')
        assert len(lines) == 1, f"Expected 1 log line, got {len(lines)}"
        entry = json.loads(lines[0])
        assert entry["guard"] == "disk:local-pipeline"
        assert entry["ok"] is True
        assert "error" not in entry


def test_guard_reading_failure():
    """guard_reading with error returns None."""
    with tempfile.TemporaryDirectory() as tmpdir:
        log_path = Path(tmpdir) / "guard-readings.jsonl"
        gr.LOG_PATH = log_path

        result = gr.guard_reading("disk:local-pipeline", 42.5, error="read timed out")
        assert result is None, f"Expected None, got {result}"

        # Check that the log was written
        assert log_path.exists(), "Log file should exist"
        lines = log_path.read_text().strip().split('\n')
        assert len(lines) == 1
        entry = json.loads(lines[0])
        assert entry["guard"] == "disk:local-pipeline"
        assert entry["ok"] is False
        assert entry["error"] == "read timed out"


def test_guard_reading_none_value():
    """guard_reading with value=None and error=None is success (None is a valid value)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        log_path = Path(tmpdir) / "guard-readings.jsonl"
        gr.LOG_PATH = log_path

        result = gr.guard_reading("dispatch:breaker", None, error=None)
        assert result is None  # None is returned, but it's success

        entry = json.loads(log_path.read_text().strip())
        assert entry["ok"] is True


def test_guard_state_no_unreadable():
    """guard_state with no unreadable entries returns ok=True."""
    with tempfile.TemporaryDirectory() as tmpdir:
        log_path = Path(tmpdir) / "guard-readings.jsonl"
        gr.LOG_PATH = log_path

        # Write a successful read
        gr.guard_reading("disk:local-pipeline", 50.0, error=None)

        state = gr.guard_state("disk:local-pipeline")
        assert state["ok"] is True
        assert state["consecutive_unreadable"] == 0
        assert state["alert"] is False


def test_guard_state_consecutive_unreadable():
    """guard_state counts consecutive unreadable entries."""
    with tempfile.TemporaryDirectory() as tmpdir:
        log_path = Path(tmpdir) / "guard-readings.jsonl"
        gr.LOG_PATH = log_path

        # Write three failures
        for i in range(3):
            gr.guard_reading("disk:local-pipeline", None, error=f"error {i}")

        state = gr.guard_state("disk:local-pipeline")
        assert state["ok"] is False
        assert state["consecutive_unreadable"] == 3
        assert state["alert"] is True  # 3 >= 2


def test_guard_state_episode_age():
    """guard_state computes episode age in minutes."""
    with tempfile.TemporaryDirectory() as tmpdir:
        log_path = Path(tmpdir) / "guard-readings.jsonl"
        gr.LOG_PATH = log_path

        # Write an old failure entry manually
        old_time = (datetime.now(timezone.utc) - timedelta(minutes=35)).isoformat()
        entry = {"at": old_time, "guard": "disk:local-pipeline", "ok": False, "error": "timeout"}
        log_path.write_text(json.dumps(entry) + "\n")

        state = gr.guard_state("disk:local-pipeline")
        assert state["ok"] is False
        assert state["consecutive_unreadable"] == 1
        # Episode should be ~35 minutes old; allow 5 minute tolerance
        assert 30 < state["episode_age_min"] <= 40
        assert state["alert"] is True  # 35 >= 30


def test_guard_state_breaks_at_success():
    """guard_state stops counting consecutive unreadables when it hits a success."""
    with tempfile.TemporaryDirectory() as tmpdir:
        log_path = Path(tmpdir) / "guard-readings.jsonl"
        gr.LOG_PATH = log_path

        # Write: unreadable, unreadable, success, unreadable, unreadable
        gr.guard_reading("disk:local-pipeline", None, error="error 1")
        gr.guard_reading("disk:local-pipeline", None, error="error 2")
        gr.guard_reading("disk:local-pipeline", 50.0, error=None)  # success
        gr.guard_reading("disk:local-pipeline", None, error="error 3")
        gr.guard_reading("disk:local-pipeline", None, error="error 4")

        state = gr.guard_state("disk:local-pipeline")
        # Only the last two unreadables count (after the success)
        assert state["consecutive_unreadable"] == 2
        assert state["ok"] is False
        assert state["alert"] is True  # 2 >= 2


def test_fail_mode_table():
    """FAIL_MODE table has all guard names with valid modes."""
    for name, mode in gr.FAIL_MODE.items():
        assert mode in ("open", "closed"), f"Invalid fail_mode '{mode}' for {name}"
        assert len(name) > 0, "Guard name should not be empty"


def test_guard_reading_cli_record():
    """CLI record command logs a reading."""
    with tempfile.TemporaryDirectory() as tmpdir:
        log_path = Path(tmpdir) / "guard-readings.jsonl"
        gr.LOG_PATH = log_path

        # Simulate CLI call
        result = gr._cli(["record", "--name", "disk:local-pipeline", "--ok", "true"])
        assert result == 0

        entry = json.loads(log_path.read_text().strip())
        assert entry["guard"] == "disk:local-pipeline"
        assert entry["ok"] is True
        assert "error" not in entry


def test_guard_reading_cli_record_error():
    """CLI record command with error."""
    with tempfile.TemporaryDirectory() as tmpdir:
        log_path = Path(tmpdir) / "guard-readings.jsonl"
        gr.LOG_PATH = log_path

        result = gr._cli(["record", "--name", "dispatch:breaker", "--ok", "false", "--error", "ssh timeout"])
        assert result == 0

        entry = json.loads(log_path.read_text().strip())
        assert entry["guard"] == "dispatch:breaker"
        assert entry["ok"] is False
        assert entry["error"] == "ssh timeout"


if __name__ == "__main__":
    test_guard_reading_success()
    test_guard_reading_failure()
    test_guard_reading_none_value()
    test_guard_state_no_unreadable()
    test_guard_state_consecutive_unreadable()
    test_guard_state_episode_age()
    test_guard_state_breaks_at_success()
    test_fail_mode_table()
    test_guard_reading_cli_record()
    test_guard_reading_cli_record_error()
    print("All tests passed!")
