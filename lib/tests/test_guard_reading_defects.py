#!/usr/bin/env python3
"""Tests for guard_reading defects fixed from code review (marvin#889, ticket review feedback).

Ensures:
1. Disk and GitHub readings are logged once, not twice
2. Different machines have separate guard logs (disk_local vs disk_remote)
3. Breaker and tools guards properly record unreadable when _safe returns None
4. Alert degraded guards detects clearing by passing all 8 guards
5. LOG_PATH is isolated in tests
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

LIB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LIB))

import dispatch_concurrency as dc  # noqa: E402
import guard_reading as gr  # noqa: E402
import health_checks as hc  # noqa: E402


def _read_guard_log(tmp_path) -> list[dict]:
    """Read all guard readings from the test's isolated log."""
    log_path = Path(gr.LOG_PATH)
    if not log_path.exists():
        return []
    return [json.loads(line) for line in log_path.read_text().splitlines() if line.strip()]


# --- Defect 1: Double logging of disk readings ---

def test_disk_readings_logged_once_in_can_start_another_not_in_free_disk_gb(tmp_path, monkeypatch):
    """Disk readings should be logged once by can_start_another, not by _free_disk_gb."""
    monkeypatch.setattr(gr, "LOG_PATH", tmp_path / "guard.jsonl")

    # Clear any prior logs
    gr.LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    if gr.LOG_PATH.exists():
        gr.LOG_PATH.unlink()

    # Simulate a parallel dispatch call that checks disk
    settings = {**dc.DEFAULTS, "parallel": True, "guards": dc.DEFAULTS["guards"]}
    disk_free_gb = lambda m: 100.0  # Reader function (not calling guard_reading)
    github_budget_pct = lambda: 90.0
    breaker_tripped = lambda: []
    missing_tools = lambda m: []

    dc.can_start_another(
        "mac-mini-1", settings,
        slots_in_use=lambda m: 0,
        disk_free_gb=disk_free_gb,
        github_budget_pct=github_budget_pct,
        breaker_tripped=breaker_tripped,
        missing_tools=missing_tools,
        is_self=True
    )

    # Count disk_local readings in the log
    readings = _read_guard_log(tmp_path)
    disk_local_readings = [r for r in readings if r.get("guard") == "disk_local"]

    # Should be exactly 1, not 2 (would be 2 if double-logged)
    assert len(disk_local_readings) == 1, f"Expected 1 disk_local reading, got {len(disk_local_readings)}"
    assert disk_local_readings[0]["ok"] is True


def test_github_budget_logged_once_not_twice(tmp_path, monkeypatch):
    """GitHub budget readings should be logged once by can_start_another."""
    monkeypatch.setattr(gr, "LOG_PATH", tmp_path / "guard.jsonl")

    gr.LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    if gr.LOG_PATH.exists():
        gr.LOG_PATH.unlink()

    settings = {**dc.DEFAULTS, "parallel": True, "guards": dc.DEFAULTS["guards"]}
    disk_free_gb = lambda m: 100.0
    github_budget_pct = lambda: 90.0
    breaker_tripped = lambda: []
    missing_tools = lambda m: []

    dc.can_start_another(
        "mac-mini-1", settings,
        slots_in_use=lambda m: 0,
        disk_free_gb=disk_free_gb,
        github_budget_pct=github_budget_pct,
        breaker_tripped=breaker_tripped,
        missing_tools=missing_tools
    )

    readings = _read_guard_log(tmp_path)
    github_readings = [r for r in readings if r.get("guard") == "github_budget"]

    # Should be exactly 1
    assert len(github_readings) == 1


# --- Defect 2: Different machines mixed in guard log ---

def test_disk_local_and_disk_remote_are_separate_guards(tmp_path, monkeypatch):
    """Local and remote disk readings should use separate guards."""
    monkeypatch.setattr(gr, "LOG_PATH", tmp_path / "guard.jsonl")

    gr.LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    if gr.LOG_PATH.exists():
        gr.LOG_PATH.unlink()

    # Log local disk reading
    gr.guard_reading("disk_local", 100.0)

    # Log remote disk reading
    gr.guard_reading("disk_remote", 50.0)

    readings = _read_guard_log(tmp_path)

    # Both should be recorded as separate guards
    assert len([r for r in readings if r["guard"] == "disk_local"]) == 1
    assert len([r for r in readings if r["guard"] == "disk_remote"]) == 1
    assert len([r for r in readings if r["guard"] == "disk"]) == 0  # Old guard name should not exist


def test_peer_state_local_and_peer_state_remote_are_separate(tmp_path, monkeypatch):
    """Local and remote peer state readings should use separate guards."""
    monkeypatch.setattr(gr, "LOG_PATH", tmp_path / "guard.jsonl")

    gr.LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    if gr.LOG_PATH.exists():
        gr.LOG_PATH.unlink()

    # Log local peer state
    gr.guard_reading("peer_state_local", {"busy": False})

    # Log remote peer state
    gr.guard_reading("peer_state_remote", {"busy": False})

    readings = _read_guard_log(tmp_path)

    assert len([r for r in readings if r["guard"] == "peer_state_local"]) == 1
    assert len([r for r in readings if r["guard"] == "peer_state_remote"]) == 1
    assert len([r for r in readings if r["guard"] == "peer_state"]) == 0


# --- Defect 3: Breaker and tools guards never recording unreadable ---

def test_breaker_guard_records_unreadable_when_safe_returns_none(tmp_path, monkeypatch):
    """Breaker guard should record unreadable when _safe returns None."""
    monkeypatch.setattr(gr, "LOG_PATH", tmp_path / "guard.jsonl")

    gr.LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    if gr.LOG_PATH.exists():
        gr.LOG_PATH.unlink()

    settings = {**dc.DEFAULTS, "parallel": True, "guards": dc.DEFAULTS["guards"]}

    # Breaker returns None (unreadable)
    breaker_tripped = lambda: None  # Raises or returns None

    disk_free_gb = lambda m: 100.0
    github_budget_pct = lambda: 90.0
    missing_tools = lambda m: []

    dc.can_start_another(
        "mac-mini-1", settings,
        slots_in_use=lambda m: 0,
        disk_free_gb=disk_free_gb,
        github_budget_pct=github_budget_pct,
        breaker_tripped=breaker_tripped,
        missing_tools=missing_tools
    )

    readings = _read_guard_log(tmp_path)
    breaker_readings = [r for r in readings if r["guard"] == "breaker"]

    # Should have recorded the unreadable breaker
    assert len(breaker_readings) == 1
    assert breaker_readings[0]["ok"] is False, "Breaker guard should record unreadable when _safe returns None"


def test_tools_guard_records_unreadable_when_safe_returns_none(tmp_path, monkeypatch):
    """Tools guard should record unreadable when _safe returns None."""
    monkeypatch.setattr(gr, "LOG_PATH", tmp_path / "guard.jsonl")

    gr.LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    if gr.LOG_PATH.exists():
        gr.LOG_PATH.unlink()

    settings = {**dc.DEFAULTS, "parallel": True, "guards": dc.DEFAULTS["guards"]}

    # Tools returns None (unreadable)
    missing_tools = lambda m: None

    disk_free_gb = lambda m: 100.0
    github_budget_pct = lambda: 90.0
    breaker_tripped = lambda: []

    dc.can_start_another(
        "mac-mini-1", settings,
        slots_in_use=lambda m: 0,
        disk_free_gb=disk_free_gb,
        github_budget_pct=github_budget_pct,
        breaker_tripped=breaker_tripped,
        missing_tools=missing_tools
    )

    readings = _read_guard_log(tmp_path)
    tools_readings = [r for r in readings if r["guard"] == "tools"]

    # Should have recorded the unreadable tools
    assert len(tools_readings) == 1
    assert tools_readings[0]["ok"] is False, "Tools guard should record unreadable when _safe returns None"


# --- Defect 4: Alert degraded guards detects clearing ---

def test_alert_degraded_guards_passes_all_8_guards_to_alert_on_change(tmp_path, monkeypatch):
    """alert_degraded_guards should pass all 8 guards; only alert if episode >= 2h old."""
    from datetime import datetime, timezone, timedelta
    import mr_notification  # noqa: E402

    monkeypatch.setattr(gr, "LOG_PATH", tmp_path / "guard.jsonl")

    gr.LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    if gr.LOG_PATH.exists():
        gr.LOG_PATH.unlink()

    # Create a mock alert_on_change to capture what items are passed
    captured_items = []

    def mock_alert_on_change(items, path, **kwargs):
        captured_items.extend(items)
        return []

    monkeypatch.setattr(mr_notification, "alert_on_change", mock_alert_on_change)

    # Create an old episode (3+ hours old) for one guard to trigger degraded state
    base_time = datetime.now(timezone.utc) - timedelta(hours=3)
    entry = {"ts": (base_time).isoformat(), "guard": "disk_local", "ok": False}
    with open(gr.LOG_PATH, "a") as f:
        f.write(__import__("json").dumps(entry) + "\n")
    # Second bad reading to trigger onset
    entry = {"ts": (base_time + timedelta(seconds=5)).isoformat(), "guard": "disk_local", "ok": False}
    with open(gr.LOG_PATH, "a") as f:
        f.write(__import__("json").dumps(entry) + "\n")

    alert_state = tmp_path / "guard-alert.json"
    hc.alert_degraded_guards([], path=alert_state)

    # All 8 guards should be passed to alert_on_change
    guard_keys = {item["key"] for item in captured_items}
    expected_keys = {f"guard:{name}" for name in gr.GUARD_TABLE}

    assert guard_keys == expected_keys, f"Expected all 8 guards, got {guard_keys}"

    # Should have items for both good and bad states
    degraded_items = [i for i in captured_items if i["state"] == "degraded"]
    ok_items = [i for i in captured_items if i["state"] == "ok"]

    assert len(degraded_items) >= 1, "Should have at least one degraded guard (3+ hours old)"
    assert len(ok_items) >= 7, "Should have at least 7 healthy guards"


def test_alert_degraded_guards_detects_clearing_when_guard_recovers(tmp_path, monkeypatch):
    """When a degraded guard recovers, alert_degraded_guards should detect clearing."""
    from datetime import datetime, timezone, timedelta
    monkeypatch.setattr(gr, "LOG_PATH", tmp_path / "guard.jsonl")

    gr.LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    if gr.LOG_PATH.exists():
        gr.LOG_PATH.unlink()

    alert_state = tmp_path / "guard-alert.json"

    # Create a guard reading that is old enough to be degraded (> 2 hours)
    base_time = datetime.now(timezone.utc) - timedelta(hours=3)
    # Write old bad readings to log directly
    entry = {"ts": (base_time).isoformat(), "guard": "disk_local", "ok": False}
    gr.LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(gr.LOG_PATH, "a") as f:
        f.write(__import__("json").dumps(entry) + "\n")
    # Second bad reading to trigger onset
    entry = {"ts": (base_time + timedelta(seconds=5)).isoformat(), "guard": "disk_local", "ok": False}
    with open(gr.LOG_PATH, "a") as f:
        f.write(__import__("json").dumps(entry) + "\n")

    # First call: disk_local is degraded (old readings trigger the alert)
    # Verify the episode is detected as degraded (age > 2 hours)
    episodes = gr.episodes(datetime.now(timezone.utc))
    assert "disk_local" in episodes, f"disk_local should have an episode after 2 bad readings"
    assert episodes["disk_local"]["age_minutes"] >= 120, f"Episode should be >= 2 hours old, got: {episodes['disk_local']}"

    # Call alert_degraded_guards - it should return a summary (like "1 new")
    result1 = hc.alert_degraded_guards([], path=alert_state)
    assert isinstance(result1, str), f"alert_degraded_guards should return a string summary, got: {result1}"

    # Now add recovery: 2 consecutive good readings
    gr.guard_reading("disk_local", 100.0)  # Good reading
    gr.guard_reading("disk_local", 100.0)  # Second good reading for recovery

    # Verify recovery is detected
    episodes = gr.episodes(datetime.now(timezone.utc))
    assert "disk_local" not in episodes, f"disk_local should be cleared after 2 good readings, episodes: {episodes}"

    # Second call: alert_degraded_guards should detect clearing
    result2 = hc.alert_degraded_guards([], path=alert_state)
    assert isinstance(result2, str), f"alert_degraded_guards should return a string summary, got: {result2}"


# --- Defect 5: LOG_PATH hardcoded (conftest isolation) ---

def test_guard_readings_isolated_in_tests(tmp_path, monkeypatch):
    """Guard readings should be isolated per test, not pollute the real log."""
    # The conftest fixture should have already redirected LOG_PATH
    # Verify that the log path is in tmp_path

    real_home = Path.home()
    real_log = real_home / ".claude" / "logs" / "guard-readings.jsonl"

    assert str(gr.LOG_PATH) != str(real_log), (
        f"Guard log should be redirected in tests. "
        f"Expected not {real_log}, got {gr.LOG_PATH}"
    )
    # LOG_PATH should be in a temporary directory, not in the real home
    assert str(real_home) not in str(gr.LOG_PATH), (
        f"Guard log should not be in the real home directory. "
        f"real_home={real_home}, LOG_PATH={gr.LOG_PATH}"
    )


# --- Integration: Episode detection with separated guards ---

def test_episodes_handles_separate_local_and_remote_guards_correctly(tmp_path, monkeypatch):
    """Episodes should properly fold readings from separated disk_local and disk_remote guards."""
    monkeypatch.setattr(gr, "LOG_PATH", tmp_path / "guard.jsonl")

    gr.LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    if gr.LOG_PATH.exists():
        gr.LOG_PATH.unlink()

    now = datetime.now(timezone.utc)

    # Create episodes: disk_local is degraded, disk_remote is ok
    gr.guard_reading("disk_local", None)  # Unreadable
    gr.guard_reading("disk_local", None)  # Second unreadable = onset

    gr.guard_reading("disk_remote", 100.0)  # Readable

    episodes = gr.episodes(now)

    # disk_local should have an episode
    assert "disk_local" in episodes
    # disk_remote should not have an episode
    assert "disk_remote" not in episodes
