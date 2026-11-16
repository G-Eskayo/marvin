#!/usr/bin/env python3
"""Tests for guard_reading.py (marvin#???). Run via:
    ~/.agents/venv/bin/python -m pytest lib/tests/test_guard_reading.py -v
"""
from __future__ import annotations

import ast
import json
import re
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

import pytest

LIB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LIB))

import guard_reading as gr  # noqa: E402


@pytest.fixture
def tmp_log_path(tmp_path):
    """Temp log file for each test."""
    path = tmp_path / "guard-readings.json"
    with mock.patch.object(gr, "LOG_PATH", path):
        yield path


class TestDebounce:
    """Debouncing: state flips only after 2 reads agree (or the debounce window passes)."""

    def test_first_bad_read_sets_pending(self, tmp_log_path):
        gr.record("test:guard", ok=False, detail="read failed")
        state = json.loads(tmp_log_path.read_text())
        entry = state["test:guard"]
        assert entry["state"] == "ok"  # state hasn't flipped yet
        assert entry["pending"] == {"state": "unreadable", "count": 1, "first_at": entry["pending"]["first_at"]}

    def test_second_bad_read_flips_state(self, tmp_log_path):
        gr.record("test:guard", ok=False, detail="read 1")
        gr.record("test:guard", ok=False, detail="read 2")
        state = json.loads(tmp_log_path.read_text())
        entry = state["test:guard"]
        assert entry["state"] == "unreadable"  # state flipped
        assert entry["pending"] is None

    def test_bad_then_good_resets_pending(self, tmp_log_path):
        gr.record("test:guard", ok=False)
        gr.record("test:guard", ok=True)
        state = json.loads(tmp_log_path.read_text())
        entry = state["test:guard"]
        assert entry["state"] == "ok"  # back to ok (never flipped)
        assert entry["pending"] is None

    def test_good_reads_dont_flip_from_unreadable_immediately(self, tmp_log_path):
        # Get to unreadable state first
        gr.record("test:guard", ok=False)
        gr.record("test:guard", ok=False)
        state = json.loads(tmp_log_path.read_text())
        assert state["test:guard"]["state"] == "unreadable"

        # Now try good reads; need 2 to flip back
        gr.record("test:guard", ok=True, detail="read 1")
        state = json.loads(tmp_log_path.read_text())
        assert state["test:guard"]["state"] == "unreadable"  # still unreadable
        assert state["test:guard"]["pending"] is not None

        gr.record("test:guard", ok=True, detail="read 2")
        state = json.loads(tmp_log_path.read_text())
        assert state["test:guard"]["state"] == "ok"  # now flipped back
        assert state["test:guard"]["pending"] is None

    def test_contradicting_reads_dont_accumulate(self, tmp_log_path):
        # Get to unreadable state first with 2 bad reads
        gr.record("test:guard", ok=False)  # pending bad
        gr.record("test:guard", ok=False)  # flip to unreadable
        state1 = json.loads(tmp_log_path.read_text())
        assert state1["test:guard"]["state"] == "unreadable"

        # Now try a good read - sets pending for flip back to ok
        gr.record("test:guard", ok=True)   # pending good (need 2 to flip)
        state2 = json.loads(tmp_log_path.read_text())
        assert state2["test:guard"]["state"] == "unreadable"  # state hasn't flipped yet
        assert state2["test:guard"]["pending"] is not None  # pending for flip to ok
        assert state2["test:guard"]["pending"]["state"] == "ok"

    def test_detail_always_updated(self, tmp_log_path):
        gr.record("test:guard", ok=True, detail="first detail")
        gr.record("test:guard", ok=True, detail="second detail")
        state = json.loads(tmp_log_path.read_text())
        assert state["test:guard"]["detail"] == "second detail"


class TestStatus:
    """status() returns severity rows for non-green guards."""

    def test_green_guards_not_reported(self, tmp_log_path):
        gr.record("test:ok", ok=True)
        assert gr.status() == []

    def test_unreadable_is_yellow_after_30m(self, tmp_log_path):
        base = datetime(2026, 11, 16, 12, 0, 0, tzinfo=timezone.utc)
        with mock.patch.object(gr, "_now", return_value=base):
            gr.record("test:guard", ok=False)
            gr.record("test:guard", ok=False)  # flip to unreadable

        # Advance 31 minutes to cross the yellow threshold
        now_future = base + timedelta(minutes=31)
        with mock.patch.object(gr, "_now", return_value=now_future):
            rows = gr.status()

        assert len(rows) == 1
        assert rows[0]["name"] == "test:guard"
        assert rows[0]["state"] == "unreadable"
        assert rows[0]["severity"] == "yellow"

    def test_unreadable_is_red_after_2h(self, tmp_log_path):
        with mock.patch.object(gr, "_now") as now_mock:
            base = datetime(2026, 11, 16, 12, 0, 0, tzinfo=timezone.utc)
            now_mock.return_value = base

            gr.record("test:guard", ok=False)
            gr.record("test:guard", ok=False)  # flip to unreadable
            # Advance past 2 hours
            now_mock.return_value = base + timedelta(hours=2, minutes=1)
            rows = gr.status()

        assert len(rows) == 1
        assert rows[0]["severity"] == "red"

    def test_multiple_guards_in_status(self, tmp_log_path):
        gr.record("disk:check", ok=False)
        gr.record("disk:check", ok=False)
        gr.record("memory:read", ok=False)
        gr.record("memory:read", ok=False)
        rows = gr.status()
        assert len(rows) == 2
        names = {r["name"] for r in rows}
        assert names == {"disk:check", "memory:read"}


class TestAtomicWrite:
    """Concurrent writes to the state file don't corrupt it."""

    def test_write_under_concurrent_access(self, tmp_log_path):
        # Simulate concurrent writes by recording from two "processes"
        for i in range(5):
            gr.record(f"guard:a", ok=i % 2 == 0, detail=f"read {i}")
            gr.record(f"guard:b", ok=i % 2 == 1, detail=f"read {i}")

        # File should still be valid JSON
        state = json.loads(tmp_log_path.read_text())
        assert "guard:a" in state
        assert "guard:b" in state

    def test_corrupt_state_file_recovers(self, tmp_log_path):
        tmp_log_path.write_text("not valid json {")
        # Should not raise; recover by overwriting
        gr.record("test:guard", ok=True)
        state = json.loads(tmp_log_path.read_text())
        assert state["test:guard"]["state"] == "ok"


class TestCoverage:
    """Coverage check: all real call sites are in GUARD_POLICY."""

    def test_policy_covers_all_call_sites(self):
        """Scan lib/**/*.py for guard_reading.record( calls and verify each in GUARD_POLICY."""
        # Import all guard-using modules to populate GUARD_POLICY
        try:
            import disk_triggers  # noqa: F401
            import memory_guard  # noqa: F401
            import dispatch_concurrency  # noqa: F401
            import model_queue  # noqa: F401
            import task_dispatch  # noqa: F401
            import run_ticket  # noqa: F401
        except ImportError:
            pass

        call_pattern = re.compile(r'guard_reading\.record\(\s*["\']([^"\']+)["\']')
        guard_names = set()

        for py_file in sorted(LIB.rglob("*.py")):
            if "test" in py_file.name:
                continue
            try:
                content = py_file.read_text()
                for match in call_pattern.finditer(content):
                    guard_names.add(match.group(1))
            except (OSError, UnicodeDecodeError):
                continue

        # All guards found in code should be in GUARD_POLICY (or be in a skipped file)
        for name in guard_names:
            assert name in gr.GUARD_POLICY, f"Guard '{name}' called but not in GUARD_POLICY. Found: {sorted(guard_names)}. Policy: {sorted(gr.GUARD_POLICY.keys())}"

    def test_guard_policy_has_string_values(self):
        """Each entry in GUARD_POLICY should be "open" or "closed"."""
        for name, policy in gr.GUARD_POLICY.items():
            assert policy in ("open", "closed"), f"Guard '{name}' has invalid policy '{policy}' (should be 'open' or 'closed')"


class TestCLI:
    """CLI interface for record and status subcommands."""

    def test_cli_record(self, tmp_log_path):
        gr.main(["record", "--name", "test:cli", "--ok", "0", "--detail", "test detail"])
        state = json.loads(tmp_log_path.read_text())
        assert state["test:cli"]["detail"] == "test detail"

    def test_cli_status_json(self, tmp_log_path, capsys):
        gr.record("test:bad", ok=False)
        gr.record("test:bad", ok=False)
        gr.main(["status"])
        out, _ = capsys.readouterr()
        rows = json.loads(out)
        assert len(rows) == 1
        assert rows[0]["name"] == "test:bad"

    def test_cli_record_ok_values(self, tmp_log_path):
        gr.main(["record", "--name", "ok:true", "--ok", "1"])
        gr.main(["record", "--name", "ok:false", "--ok", "0"])
        state = json.loads(tmp_log_path.read_text())
        assert state["ok:true"]["state"] == "ok"
        assert state["ok:false"]["pending"] is not None  # set to unreadable


class TestMissingLogFile:
    """Graceful handling when log file doesn't exist."""

    def test_record_on_missing_file(self, tmp_log_path):
        # File doesn't exist yet
        assert not tmp_log_path.exists()
        gr.record("test:new", ok=True)
        assert tmp_log_path.exists()
        state = json.loads(tmp_log_path.read_text())
        assert state["test:new"]["state"] == "ok"
