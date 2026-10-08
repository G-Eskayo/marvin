"""Debounce mechanism for refilling dispatch slots (ADR 0052, ticket #196).

Tests verify that:
1. First caller acquires lock and spawns worker
2. Concurrent callers during debounce window see the lock and return False
3. Worker removes the lock and spawns the actual scan after debounce sleep
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import redispatch_trigger as rt  # noqa: E402


# --- lock acquisition ---


def test_acquire_lock_succeeds_first_time(tmp_path):
    """First caller atomically creates the lock."""
    lock_path = tmp_path / "scan.lock"
    assert rt._acquire_lock(lock_path) is True
    assert lock_path.exists()


def test_acquire_lock_fails_second_time(tmp_path):
    """Second caller sees the lock already exists."""
    lock_path = tmp_path / "scan.lock"
    assert rt._acquire_lock(lock_path) is True
    assert rt._acquire_lock(lock_path) is False


def test_acquire_lock_creates_parent_dirs(tmp_path):
    """Missing parent directories are created."""
    lock_path = tmp_path / "a" / "b" / "c" / "scan.lock"
    assert rt._acquire_lock(lock_path) is True
    assert lock_path.exists()


# --- request_scan ---


def test_request_scan_first_caller_acquires_and_spawns(tmp_path):
    """First request acquires lock and calls spawn_worker."""
    lock_path = tmp_path / "scan.lock"
    spawned = []

    def fake_spawn(lp, debounce_s):
        spawned.append((lp, debounce_s))

    result = rt.request_scan(lock_path=lock_path, spawn_worker=fake_spawn)
    assert result is True
    assert len(spawned) == 1
    assert spawned[0][0] == lock_path
    assert lock_path.exists()


def test_request_scan_second_caller_sees_lock_and_returns_false(tmp_path):
    """Second request within debounce window returns False, no spawn."""
    lock_path = tmp_path / "scan.lock"
    spawned = []

    def fake_spawn(lp, debounce_s):
        spawned.append((lp, debounce_s))

    rt.request_scan(lock_path=lock_path, spawn_worker=fake_spawn)

    result = rt.request_scan(lock_path=lock_path, spawn_worker=fake_spawn)
    assert result is False
    assert len(spawned) == 1  # only first request spawned


def test_request_scan_respects_debounce_parameter(tmp_path):
    """Debounce seconds are passed to spawn_worker."""
    lock_path = tmp_path / "scan.lock"
    captured = []

    def fake_spawn(lp, debounce_s):
        captured.append(debounce_s)

    rt.request_scan(lock_path=lock_path, debounce_s=5.5, spawn_worker=fake_spawn)
    assert captured == [5.5]


def test_request_scan_uses_default_lock_path(tmp_path, monkeypatch):
    """If lock_path is not provided, uses ~/.claude/dispatch/scan-pending.lock."""
    monkeypatch.setenv("HOME", str(tmp_path))
    spawned = []

    def fake_spawn(lp, debounce_s):
        spawned.append(lp)

    rt.request_scan(spawn_worker=fake_spawn)
    assert len(spawned) == 1
    expected = tmp_path / ".claude" / "dispatch" / "scan-pending.lock"
    assert spawned[0] == expected


def test_request_scan_with_injected_acquire(tmp_path):
    """acquire function is injected and used."""
    lock_path = tmp_path / "scan.lock"
    acquire_calls = []
    spawn_calls = []

    def fake_acquire(lp):
        acquire_calls.append(lp)
        return True

    def fake_spawn(lp, debounce_s):
        spawn_calls.append((lp, debounce_s))

    result = rt.request_scan(lock_path=lock_path, acquire=fake_acquire, spawn_worker=fake_spawn)
    assert result is True
    assert acquire_calls == [lock_path]
    assert len(spawn_calls) == 1


# --- worker main ---


def test_worker_main_removes_lock_and_spawns_scan(tmp_path):
    """Worker removes lock, sleeps (injected), and spawns scan."""
    lock_path = tmp_path / "scan.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.write_text("")

    slept = []
    spawned = []

    def fake_sleep(s):
        slept.append(s)

    def fake_spawn_scan():
        spawned.append(True)

    # Monkeypatch time.sleep and _spawn_scan
    import redispatch_trigger
    old_sleep = redispatch_trigger.time.sleep
    old_spawn = redispatch_trigger._spawn_scan
    try:
        redispatch_trigger.time.sleep = fake_sleep
        redispatch_trigger._spawn_scan = fake_spawn_scan

        rt._worker_main(lock_path, debounce_s=2)
        assert slept == [2]
        assert not lock_path.exists()
        assert spawned == [True]
    finally:
        redispatch_trigger.time.sleep = old_sleep
        redispatch_trigger._spawn_scan = old_spawn


def test_worker_main_removes_lock_if_missing(tmp_path):
    """Worker handles missing lock gracefully (missing_ok=True)."""
    lock_path = tmp_path / "missing.lock"
    spawned = []

    def fake_spawn_scan():
        spawned.append(True)

    import redispatch_trigger
    old_sleep = redispatch_trigger.time.sleep
    old_spawn = redispatch_trigger._spawn_scan
    try:
        redispatch_trigger.time.sleep = lambda s: None
        redispatch_trigger._spawn_scan = fake_spawn_scan

        rt._worker_main(lock_path, debounce_s=0.1)
        assert spawned == [True]
    finally:
        redispatch_trigger.time.sleep = old_sleep
        redispatch_trigger._spawn_scan = old_spawn


# --- burst scenario ---


def test_burst_of_requests_only_spawns_once(tmp_path):
    """A burst of requests (simulating N tickets finishing at once) only spawns one scan."""
    lock_path = tmp_path / "scan.lock"
    spawned = []

    def fake_spawn(lp, debounce_s):
        spawned.append((lp, debounce_s))

    # Simulate 5 tickets finishing at once
    results = []
    for i in range(5):
        result = rt.request_scan(lock_path=lock_path, spawn_worker=fake_spawn)
        results.append(result)

    # Only the first should succeed
    assert results == [True, False, False, False, False]
    assert len(spawned) == 1


# --- _spawn_scan ---


def test_spawn_scan_spawns_ticket_pipeline_detached(monkeypatch):
    """_spawn_scan() spawns ticket_pipeline.py as a detached process."""
    calls = []

    class FakePopen:
        def __init__(self, cmd, **kwargs):
            calls.append((cmd, kwargs))

    monkeypatch.setattr(rt.subprocess, "Popen", FakePopen)
    rt._spawn_scan()

    cmd, kwargs = calls[0]
    assert cmd[0] == rt.sys.executable
    assert cmd[1].endswith("ticket_pipeline.py")
    assert kwargs.get("start_new_session") is True
