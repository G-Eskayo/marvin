"""Cross-Mac deploy trigger on merge (ticket #278).

Debounces rapid merges, dispatches code-sync + webhook-restart to remote machines,
and records the run via job_events for dashboard visibility.
"""
from __future__ import annotations
import sys
from pathlib import Path
from unittest.mock import Mock, patch, call

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import deploy_on_merge as dom  # noqa: E402


# --- debounce lock acquisition ---


def test_acquire_lock_first_call_succeeds(tmp_path):
    """First call acquires the lock."""
    lock_path = tmp_path / "deploy-pending-mini.lock"
    assert dom._acquire_lock(lock_path) is True
    assert lock_path.exists()


def test_acquire_lock_second_call_fails(tmp_path):
    """Second call sees lock already exists, returns False."""
    lock_path = tmp_path / "deploy-pending-mini.lock"
    assert dom._acquire_lock(lock_path) is True
    assert dom._acquire_lock(lock_path) is False


def test_acquire_lock_creates_parent_dirs(tmp_path):
    """Missing parent directories are created."""
    lock_path = tmp_path / "a" / "b" / "deploy.lock"
    assert dom._acquire_lock(lock_path) is True
    assert lock_path.exists()


# --- per-device lock paths ---


def test_deploy_on_merge_first_device_acquires_lock(tmp_path, monkeypatch):
    """First merge for a device acquires its per-device lock and dispatches."""
    lock_dir = tmp_path / "locks"
    monkeypatch.setenv("HOME", str(tmp_path))

    dispatched = []
    def fake_dispatch(cmd, **kwargs):
        dispatched.append((cmd, kwargs))
        from task_dispatch import DispatchResult
        return DispatchResult(ok=True, device_id=kwargs.get("target"))

    with patch("deploy_on_merge.task_dispatch.dispatch", fake_dispatch):
        with patch("deploy_on_merge.job_events"):
            result = dom.deploy_on_merge("mac-mini")

    assert result is True
    assert len(dispatched) == 1
    assert "mac-mini" in dispatched[0][1].get("target", "")


def test_deploy_on_merge_second_device_independent(tmp_path, monkeypatch):
    """Two devices have independent locks (not blocked by each other)."""
    monkeypatch.setenv("HOME", str(tmp_path))

    dispatched = []
    def fake_dispatch(cmd, **kwargs):
        dispatched.append(kwargs.get("target"))
        from task_dispatch import DispatchResult
        return DispatchResult(ok=True, device_id=kwargs.get("target"))

    with patch("deploy_on_merge.task_dispatch.dispatch", fake_dispatch):
        with patch("deploy_on_merge.job_events"):
            result1 = dom.deploy_on_merge("mac-mini")
            result2 = dom.deploy_on_merge("macbook-pro")

    assert result1 is True
    assert result2 is True
    assert dispatched == ["mac-mini", "macbook-pro"]


def test_deploy_on_merge_same_device_debounced(tmp_path, monkeypatch):
    """Two merges for the same device within debounce window: only first dispatches."""
    monkeypatch.setenv("HOME", str(tmp_path))

    dispatched = []
    def fake_dispatch(cmd, **kwargs):
        dispatched.append(kwargs.get("target"))
        from task_dispatch import DispatchResult
        return DispatchResult(ok=True, device_id=kwargs.get("target"))

    with patch("deploy_on_merge.task_dispatch.dispatch", fake_dispatch):
        with patch("deploy_on_merge.job_events"):
            result1 = dom.deploy_on_merge("mac-mini")
            result2 = dom.deploy_on_merge("mac-mini")

    assert result1 is True
    assert result2 is False  # debounced
    assert dispatched == ["mac-mini"]  # only one dispatch


# --- dispatch command safety ---


def test_deploy_on_merge_command_is_fixed_string(tmp_path, monkeypatch):
    """Dispatched command is a fixed string, independent of device_id or input."""
    monkeypatch.setenv("HOME", str(tmp_path))

    commands = []
    def fake_dispatch(cmd, **kwargs):
        commands.append(cmd)
        from task_dispatch import DispatchResult
        return DispatchResult(ok=True, device_id=kwargs.get("target"))

    with patch("deploy_on_merge.task_dispatch.dispatch", fake_dispatch):
        with patch("deploy_on_merge.job_events"):
            dom.deploy_on_merge("mac-mini")
            # clear and try another device
            commands.clear()
            # clean up the lock manually to allow a new call
            lock_dir = tmp_path / ".claude" / "dispatch"
            if (lock_dir / "deploy-pending-mac-mini.lock").exists():
                (lock_dir / "deploy-pending-mac-mini.lock").unlink()
            dom.deploy_on_merge("macbook-pro")

    # Both should have the exact same command (no interpolation)
    assert commands[0] == commands[1]
    assert "cd ~/.agents && venv/bin/python" in commands[0]


# --- dispatch failure handling ---


def test_deploy_on_merge_dispatch_error_is_caught_and_logged(tmp_path, monkeypatch):
    """If dispatch returns ok=False, it's caught and logged, not raised."""
    monkeypatch.setenv("HOME", str(tmp_path))

    def fake_dispatch(cmd, **kwargs):
        from task_dispatch import DispatchResult
        return DispatchResult(ok=False, error="target offline")

    run_calls = []
    mock_run = Mock()
    mock_run.fail = lambda msg: run_calls.append(("fail", msg))

    with patch("deploy_on_merge.task_dispatch.dispatch", fake_dispatch):
        with patch("deploy_on_merge.job_events.job_run") as mock_job_run:
            mock_job_run.return_value.__enter__.return_value = mock_run
            # Should not raise; should call run.fail()
            try:
                result = dom.deploy_on_merge("offline-device")
            except Exception as e:
                pytest.fail(f"Should not raise, got {e}")

    assert any("offline" in str(call[1]).lower() for call in run_calls)


# --- stale lock cleanup ---


def test_deploy_on_merge_with_stale_lock_file(tmp_path, monkeypatch):
    """A stale lock file from a crashed run doesn't permanently wedge future pings."""
    monkeypatch.setenv("HOME", str(tmp_path))
    lock_path = tmp_path / ".claude" / "dispatch" / "deploy-pending-mac-mini.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    # Create a stale lock file
    lock_path.write_text("stale")

    # The lock exists, so first call sees it and returns False (debounced).
    # But if we manually clean it up (simulating TTL or manual clear), second call should work.

    result1 = dom.deploy_on_merge("mac-mini")
    assert result1 is False  # lock exists, debounced

    # Manually clean up (simulating TTL or manual intervention)
    lock_path.unlink()

    dispatched = []
    def fake_dispatch(cmd, **kwargs):
        dispatched.append(True)
        from task_dispatch import DispatchResult
        return DispatchResult(ok=True, device_id=kwargs.get("target"))

    with patch("deploy_on_merge.task_dispatch.dispatch", fake_dispatch):
        with patch("deploy_on_merge.job_events"):
            result2 = dom.deploy_on_merge("mac-mini")

    assert result2 is True
    assert dispatched == [True]


# --- new machine, first run ---


def test_deploy_on_merge_creates_lock_dir_first_time(tmp_path, monkeypatch):
    """First run ever on a fresh machine: mkdir(parents=True) creates the dir."""
    monkeypatch.setenv("HOME", str(tmp_path))
    lock_dir = tmp_path / ".claude" / "dispatch"
    assert not lock_dir.exists()

    dispatched = []
    def fake_dispatch(cmd, **kwargs):
        dispatched.append(True)
        from task_dispatch import DispatchResult
        return DispatchResult(ok=True, device_id=kwargs.get("target"))

    with patch("deploy_on_merge.task_dispatch.dispatch", fake_dispatch):
        with patch("deploy_on_merge.job_events"):
            dom.deploy_on_merge("mac-mini")

    assert lock_dir.exists()
    assert dispatched == [True]


# --- invalid device_id ---


def test_deploy_on_merge_invalid_device_id_fails_loud(tmp_path, monkeypatch):
    """Called with an unknown device_id: dispatch fails and logs error."""
    monkeypatch.setenv("HOME", str(tmp_path))

    # dispatch() will return ok=False for an unknown device
    def fake_dispatch(cmd, **kwargs):
        target = kwargs.get("target", "")
        from task_dispatch import DispatchResult
        if target == "unknown-device":
            return DispatchResult(ok=False, error="unknown device")
        return DispatchResult(ok=True, device_id=target)

    run_calls = []
    mock_run = Mock()
    mock_run.fail = lambda msg: run_calls.append(("fail", msg))

    with patch("deploy_on_merge.task_dispatch.dispatch", fake_dispatch):
        with patch("deploy_on_merge.job_events.job_run") as mock_job_run:
            mock_job_run.return_value.__enter__.return_value = mock_run
            dom.deploy_on_merge("unknown-device")

    # Should have logged the error
    assert any("unknown-device" in str(call[1]) or "unknown device" in str(call[1])
               for call in run_calls)


# --- job_events integration ---


def test_deploy_on_merge_records_via_job_events(tmp_path, monkeypatch):
    """Run is recorded with job_events steps."""
    monkeypatch.setenv("HOME", str(tmp_path))

    def fake_dispatch(cmd, **kwargs):
        from task_dispatch import DispatchResult
        return DispatchResult(ok=True, device_id=kwargs.get("target"))

    with patch("deploy_on_merge.task_dispatch.dispatch", fake_dispatch):
        with patch("deploy_on_merge.job_events.job_run") as mock_job_run:
            mock_run = Mock()
            mock_job_run.return_value.__enter__.return_value = mock_run

            dom.deploy_on_merge("mac-mini")

            # Should have called job_run
            mock_job_run.assert_called_once()
            # Should have logged steps
            assert mock_run.step.called or mock_run.summary.called
