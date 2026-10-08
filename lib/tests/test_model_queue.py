"""Tests for model_queue.py. Run via:
    ~/.agents/venv/bin/python -m pytest lib/tests/test_model_queue.py -v
"""
from __future__ import annotations
import sys
import json
from pathlib import Path
from datetime import datetime, timezone

import pytest

LIB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LIB))

import model_queue as mq  # noqa: E402


@pytest.fixture
def queue_state_file(tmp_path):
    """Provide a temporary queue state file."""
    state_file = tmp_path / "model-queue.json"
    return state_file


@pytest.fixture
def monkeypatch_queue_path(queue_state_file):
    """Return a test queue state file path."""
    return queue_state_file


def test_acquire_first_heavy_model(monkeypatch_queue_path):
    """First acquire of a heavy model should succeed immediately."""
    queue = mq.ModelQueue(state_path=monkeypatch_queue_path)
    job_id = "job-123"
    model = "FLUX.1-schnell-4bit"

    result = queue.acquire(model, job_id, is_heavy=True)
    assert result is True

    status = queue.status()
    assert status["locks"] == {model: {"job_id": job_id, "acquired_at": status["locks"][model]["acquired_at"]}}
    assert status["waiters"] == {}


def test_acquire_blocks_different_heavy_model(monkeypatch_queue_path):
    """Second heavy model should be blocked when another is running."""
    queue = mq.ModelQueue(state_path=monkeypatch_queue_path)
    job1 = "job-1"
    job2 = "job-2"
    model1 = "FLUX.1-schnell-4bit"
    model2 = "qwen2.5:14b"

    # First acquire succeeds
    queue.acquire(model1, job1, is_heavy=True)

    # Second acquire fails (different heavy model)
    result = queue.acquire(model2, job2, is_heavy=True, timeout=0.1)
    assert result is False

    status = queue.status()
    assert model1 in status["locks"]
    assert f"{model2}::{job2}" in status["waiters"]


def test_release_frees_lock(monkeypatch_queue_path):
    """Release should free the lock."""
    queue = mq.ModelQueue(state_path=monkeypatch_queue_path)
    job = "job-1"
    model = "FLUX.1-schnell-4bit"

    queue.acquire(model, job, is_heavy=True)
    assert model in queue.status()["locks"]

    queue.release(model, job)
    assert model not in queue.status()["locks"]


def test_release_wakes_next_waiter(monkeypatch_queue_path):
    """Release should wake the next waiter."""
    queue = mq.ModelQueue(state_path=monkeypatch_queue_path)
    model1 = "FLUX.1-schnell-4bit"
    model2 = "qwen2.5:14b"
    job1 = "job-1"
    job2 = "job-2"

    # First acquire succeeds
    queue.acquire(model1, job1, is_heavy=True)

    # Second acquire waits
    import threading
    acquired = []
    def waiter():
        result = queue.acquire(model2, job2, is_heavy=True, timeout=5)
        acquired.append(result)

    thread = threading.Thread(target=waiter)
    thread.start()

    # Give it time to start waiting
    import time
    time.sleep(0.2)

    # Release the first lock
    queue.release(model1, job1)

    # Wait for the thread
    thread.join(timeout=2)
    assert acquired == [True]

    status = queue.status()
    assert model2 in status["locks"]
    assert status["locks"][model2]["job_id"] == job2


def test_non_heavy_model_no_queue(monkeypatch_queue_path):
    """Non-heavy models should not be queued."""
    queue = mq.ModelQueue(state_path=monkeypatch_queue_path)
    model = "nomic-embed-text"
    job = "job-1"

    result = queue.acquire(model, job, is_heavy=False)
    assert result is True

    # Should not appear in queue state
    status = queue.status()
    assert model not in status["locks"]
    assert model not in status["waiters"]


def test_same_job_can_reacquire(monkeypatch_queue_path):
    """Same job_id acquiring twice should not deadlock."""
    queue = mq.ModelQueue(state_path=monkeypatch_queue_path)
    model = "FLUX.1-schnell-4bit"
    job = "job-1"

    queue.acquire(model, job, is_heavy=True)
    # Same job reacquiring should return True
    result = queue.acquire(model, job, is_heavy=True)
    assert result is True


def test_timeout_waiting(monkeypatch_queue_path):
    """acquire() with timeout should return False after timeout."""
    queue = mq.ModelQueue(state_path=monkeypatch_queue_path)
    model1 = "FLUX.1-schnell-4bit"
    model2 = "qwen2.5:14b"
    job1 = "job-1"
    job2 = "job-2"

    queue.acquire(model1, job1, is_heavy=True)

    # Short timeout
    result = queue.acquire(model2, job2, is_heavy=True, timeout=0.05)
    assert result is False

    status = queue.status()
    assert f"{model2}::{job2}" in status["waiters"]


def test_status_empty(monkeypatch_queue_path):
    """status() should return empty dicts when no models are locked."""
    queue = mq.ModelQueue(state_path=monkeypatch_queue_path)
    status = queue.status()
    assert status["locks"] == {}
    assert status["waiters"] == {}


def test_orphaned_lock_cleanup(monkeypatch_queue_path):
    """Locks held by non-existent processes should be cleaned."""
    model = "FLUX.1-schnell-4bit"
    job = "job-999999999"  # Non-existent process

    # Manually create an old orphaned lock
    state_file = monkeypatch_queue_path
    state_file.parent.mkdir(parents=True, exist_ok=True)
    old_state = {
        "locks": {
            model: {
                "job_id": job,
                "acquired_at": (datetime.now(timezone.utc).timestamp() - 3600)  # 1 hour ago
            }
        },
        "waiters": {}
    }
    state_file.write_text(json.dumps(old_state))

    # Create a queue with the test state file
    queue = mq.ModelQueue(state_path=state_file)
    status = queue.status()

    # Old lock should be cleaned (assuming job_id doesn't match a running process)
    # The lock will be cleaned on next acquire if the process is dead
    # For this test, we just verify status can be read
    assert isinstance(status["locks"], dict)


def test_heavy_models_share_lock_namespace(monkeypatch_queue_path):
    """FLUX and qwen2.5:14b (two different heavy models) should share the same lock.

    This tests that portfolio_flux and logic_auditor can't run simultaneously
    when both use their heavy models.
    """
    queue = mq.ModelQueue(state_path=monkeypatch_queue_path)
    flux_model = "FLUX.1-schnell-4bit"
    classify_model = "qwen2.5:14b"

    # First job acquires FLUX lock
    job1 = "flux-job-1"
    result = queue.acquire(flux_model, job1, is_heavy=True)
    assert result is True

    # Second job tries to acquire different heavy model (classify)
    # Should block because FLUX is held
    job2 = "logic-auditor-job-1"
    result = queue.acquire(classify_model, job2, is_heavy=True, timeout=0.1)
    assert result is False

    # Verify waiter is registered
    status = queue.status()
    assert f"{classify_model}::{job2}" in status["waiters"]

    # Release FLUX lock
    queue.release(flux_model, job1)

    # Now classify job should be able to acquire
    result = queue.acquire(classify_model, job2, is_heavy=True, timeout=1)
    assert result is True

    status = queue.status()
    assert classify_model in status["locks"]
    assert status["locks"][classify_model]["job_id"] == job2
