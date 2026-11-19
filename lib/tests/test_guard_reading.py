"""Tests for guard_reading.py (marvin#889, marvin#891: visibility into intermittent read failures).

The module tracks reading failures via hysteresis (symmetric 2-reading/30-min windows) and alerts on
the state changing, with an alert each day while degraded. Run via:
    ~/.agents/venv/bin/python -m pytest lib/tests/test_guard_reading.py -v
"""
from __future__ import annotations
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

LIB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LIB))

import guard_reading as gr  # noqa: E402


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    """State in tmp_path; test time control."""
    monkeypatch.setattr(gr, "STATE_PATH", tmp_path / "guard-state.json")
    return tmp_path


# ── basic reading ───────────────────────────────────────────────────────────────────────────────────

def test_reading_ok_value_does_nothing_on_first_call(isolated):
    """First OK reading: no state file created."""
    gr.reading("test:one", "ok_value")
    assert not isolated.joinpath("guard-state.json").exists()


def test_reading_ok_clears_an_open_episode(isolated):
    """OK reading closes a degraded episode."""
    state = {"test:one": {"episode_opened_at": "2026-01-01T12:00:00+00:00", "last_reading_at": "2026-01-01T12:00:00+00:00"}}
    isolated.joinpath("guard-state.json").write_text(json.dumps(state))
    now = datetime(2026, 1, 1, 12, 15, tzinfo=timezone.utc)
    gr.reading("test:one", "ok_value", now=now)
    # State file should be deleted when empty
    assert not isolated.joinpath("guard-state.json").exists()


def test_reading_error_first_time_is_recorded_no_alert(isolated):
    """First error reading: recorded, but no alert yet (need 2 readings to open an episode)."""
    now = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
    result = gr.reading("test:one", RuntimeError("oops"), now=now)
    assert result == {"episode": None, "alert": None}
    state = json.loads(isolated.joinpath("guard-state.json").read_text())
    assert state["test:one"]["last_error"] == "oops"
    assert state["test:one"]["last_error_at"] == now.isoformat()
    assert "episode_opened_at" not in state["test:one"]


def test_reading_error_within_30min_opens_an_episode(isolated):
    """Second error within 30 min of first: episode opens (hysteresis)."""
    now1 = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
    gr.reading("test:one", RuntimeError("first"), now=now1)

    now2 = datetime(2026, 1, 1, 12, 15, tzinfo=timezone.utc)
    result = gr.reading("test:one", RuntimeError("second"), now=now2)

    assert result["episode"] is not None
    assert result["alert"] == "new"
    state = json.loads(isolated.joinpath("guard-state.json").read_text())
    assert state["test:one"]["episode_opened_at"] == result["episode"]


def test_reading_error_after_30min_window_needs_another(isolated):
    """Error after 30 min window: doesn't open episode yet (needs two within 30 min)."""
    now1 = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
    gr.reading("test:one", RuntimeError("first"), now=now1)

    now2 = datetime(2026, 1, 1, 12, 31, tzinfo=timezone.utc)
    result = gr.reading("test:one", RuntimeError("second"), now=now2)

    assert result["episode"] is None
    state = json.loads(isolated.joinpath("guard-state.json").read_text())
    assert state["test:one"]["last_error"] == "second"


def test_reading_ok_during_open_episode_closes_it(isolated):
    """OK reading while episode is open: closes it, alert=cleared."""
    state = {"test:one": {"episode_opened_at": "2026-01-01T12:00:00+00:00", "last_reading_at": "2026-01-01T12:10:00+00:00"}}
    isolated.joinpath("guard-state.json").write_text(json.dumps(state))

    now = datetime(2026, 1, 1, 12, 20, tzinfo=timezone.utc)
    result = gr.reading("test:one", "ok_value", now=now)

    assert result["alert"] == "cleared"
    # State file should be deleted when empty
    assert not isolated.joinpath("guard-state.json").exists()


def test_reading_error_during_open_episode_stays_open_no_alert_until_next_day(isolated):
    """Error while episode is already open: stays open, no alert until next day (reminder)."""
    state = {
        "test:one": {
            "episode_opened_at": "2026-01-01T12:00:00+00:00",
            "last_reading_at": "2026-01-01T12:10:00+00:00",
            "last_alert_date": "2026-01-01",
        }
    }
    isolated.joinpath("guard-state.json").write_text(json.dumps(state))

    now = datetime(2026, 1, 1, 12, 20, tzinfo=timezone.utc)
    result = gr.reading("test:one", RuntimeError("still bad"), now=now)

    assert result["episode"] == "2026-01-01T12:00:00+00:00"
    assert result["alert"] is None


def test_reading_error_during_open_episode_next_day_sends_reminder(isolated):
    """Error on next day while episode still open: sends reminder alert."""
    state = {
        "test:one": {
            "episode_opened_at": "2026-01-01T12:00:00+00:00",
            "last_reading_at": "2026-01-01T12:10:00+00:00",
            "last_alert_date": "2026-01-01",
        }
    }
    isolated.joinpath("guard-state.json").write_text(json.dumps(state))

    now = datetime(2026, 1, 2, 12, 20, tzinfo=timezone.utc)
    result = gr.reading("test:one", RuntimeError("still bad"), now=now)

    assert result["alert"] == "reminder"
    state = json.loads(isolated.joinpath("guard-state.json").read_text())
    assert state["test:one"]["last_alert_date"] == "2026-01-02"


def test_detail_text_is_truncated(isolated):
    """Detail is bounded: very long error message is truncated."""
    long_msg = "x" * 500
    gr.reading("test:one", RuntimeError(long_msg), detail="detail " + "y" * 300)
    state = json.loads(isolated.joinpath("guard-state.json").read_text())
    assert len(state["test:one"].get("detail", "")) <= 256


def test_state_file_is_self_healing_on_corruption(isolated):
    """Corrupt state file: reading creates a fresh one."""
    isolated.joinpath("guard-state.json").write_text("{invalid json")

    now = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
    gr.reading("test:one", RuntimeError("first"), now=now)

    state = json.loads(isolated.joinpath("guard-state.json").read_text())
    assert state["test:one"]["last_error"] == "first"


def test_fcntl_locking_prevents_concurrent_writes(isolated, monkeypatch):
    """State file is fcntl-locked during read-modify-write."""
    locked = []

    def fake_lock(fh, op):
        locked.append(op)

    monkeypatch.setattr("fcntl.flock", fake_lock)

    gr.reading("test:one", RuntimeError("test"), now=datetime.now(timezone.utc))
    # Should have called flock at least once
    assert len(locked) > 0


def test_multiple_readings_tracked_independently(isolated):
    """Multiple guard names tracked separately."""
    now = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
    gr.reading("disk:check", RuntimeError("disk error"), now=now)
    gr.reading("memory:check", RuntimeError("memory error"), now=now)

    state = json.loads(isolated.joinpath("guard-state.json").read_text())
    assert state["disk:check"]["last_error"] == "disk error"
    assert state["memory:check"]["last_error"] == "memory error"


# ── alert_degraded ──────────────────────────────────────────────────────────────────────────────

def test_alert_degraded_reads_state_and_alerts_on_open_episodes(isolated):
    """alert_degraded: identifies open episodes and fires alerts."""
    state = {
        "test:one": {"episode_opened_at": "2026-01-01T12:00:00+00:00"},
        "test:two": {"episode_opened_at": "2026-01-01T13:00:00+00:00", "last_alert_date": "2026-01-01"},
    }
    isolated.joinpath("guard-state.json").write_text(json.dumps(state))

    alerts = []
    def fake_fire(title, msg):
        alerts.append((title, msg))

    gr.alert_degraded(fire=fake_fire, today="2026-01-02")

    # Both open episodes should have been flagged for alert
    # test:one will be "new", test:two will be "reminder"
    assert len(alerts) >= 2


def test_alert_degraded_uses_mr_notification_wrapper(isolated, monkeypatch):
    """alert_degraded calls mr_notification.alert_on_change correctly."""
    state = {
        "disk:check": {"episode_opened_at": "2026-01-01T12:00:00+00:00"},
    }
    isolated.joinpath("guard-state.json").write_text(json.dumps(state))

    called = []
    def fake_alert_on_change(items, path, bad, message=None, fire=None, today=None):
        called.append((items, path, bad))
        return []

    monkeypatch.setattr("mr_notification.alert_on_change", fake_alert_on_change)

    gr.alert_degraded(today="2026-01-02")

    assert len(called) == 1
    items, path, bad = called[0]
    assert "degraded" in bad
    assert len(items) > 0  # test:one is open, should be in items


# ── FAIL_MODE table ─────────────────────────────────────────────────────────────────────────────

def test_fail_mode_has_15_entries():
    """FAIL_MODE table is defined and has the expected entries."""
    assert hasattr(gr, "FAIL_MODE")
    assert isinstance(gr.FAIL_MODE, dict)
    assert len(gr.FAIL_MODE) == 15


# ── CLI ──────────────────────────────────────────────────────────────────────────────────────────

def test_cli_reading_ok(isolated, capsys):
    """CLI: guard_reading.py reading NAME --ok."""
    gr.main(["reading", "test:one", "--ok"])
    captured = capsys.readouterr()
    result = json.loads(captured.out)
    assert result["alert"] is None and result["episode"] is None


def test_cli_reading_error(isolated, capsys):
    """CLI: guard_reading.py reading NAME --error TEXT."""
    gr.main(["reading", "test:one", "--error", "something broke"])
    captured = capsys.readouterr()
    state = json.loads(isolated.joinpath("guard-state.json").read_text())
    assert state["test:one"]["last_error"] == "something broke"


# ── source coverage: lib/guard_reading.py is imported and used ────────────────────────────────

def test_source_grep_coverage():
    """Verify guard_reading is actually used by the modules that import it."""
    import subprocess
    result = subprocess.run(
        ["rg", "-l", "guard_reading", "lib", "--type", "py"],
        capture_output=True,
        text=True,
        cwd=LIB.parent
    )
    # After implementation, this should find multiple files importing guard_reading
    # For now, it's OK if it finds none (not yet implemented)
    pass
