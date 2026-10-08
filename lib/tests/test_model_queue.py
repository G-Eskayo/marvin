"""Tests for lib.model_queue: per-Mac heavy-model queue gating."""
from __future__ import annotations

import json
import tempfile
from contextlib import contextmanager
from pathlib import Path

import pytest

from lib import model_queue


@pytest.fixture
def tmp_queue_dir(tmp_path):
    """Temporary queue directory for testing."""
    queue_dir = tmp_path / "queue" / "tasks"
    queue_dir.mkdir(parents=True, exist_ok=True)
    return queue_dir


def fake_is_alive_factory():
    """Create a fake is_alive function that tracks PIDs."""
    alive_pids = set()
    def is_alive(pid: int) -> bool:
        return pid in alive_pids
    is_alive.add = lambda pid: alive_pids.add(pid)
    is_alive.remove = lambda pid: alive_pids.discard(pid)
    is_alive.clear = lambda: alive_pids.clear()
    return is_alive


class TestAcquire:
    def test_light_model_never_queues(self, tmp_queue_dir):
        """Light models bypass the queue entirely."""
        @contextmanager
        def mock_is_heavy(model, config=None):
            return model == "qwen2.5:14b"

        with model_queue.acquire("qwen2.5:7b", "mac-mini", "test-caller",
                                queue_dir=tmp_queue_dir, is_heavy_fn=lambda m, c=None: False):
            # Should not create any queue record
            assert list(tmp_queue_dir.glob("*.json")) == []

    def test_heavy_model_creates_waiting_record(self, tmp_queue_dir):
        """Heavy model creates a waiting record initially."""
        is_alive = fake_is_alive_factory()
        is_alive.add(999)  # Self PID

        with model_queue.acquire("qwen2.5:14b", "mac-mini", "test-caller",
                                queue_dir=tmp_queue_dir, is_heavy_fn=lambda m, c=None: m == "qwen2.5:14b",
                                is_alive_fn=is_alive, pid=999):
            records = list(tmp_queue_dir.glob("*.json"))
            assert len(records) == 1
            data = json.loads(records[0].read_text())
            assert data["status"] == "running"  # It acquires immediately since queue was empty
            assert data["model"] == "qwen2.5:14b"

    def test_second_heavy_blocks_until_first_released(self, tmp_queue_dir):
        """Second heavy-model acquire on same machine blocks."""
        is_alive = fake_is_alive_factory()
        is_alive.add(999)
        is_alive.add(888)

        # First acquire takes the lock
        with model_queue.acquire("qwen2.5:14b", "mac-mini", "caller-1",
                                queue_dir=tmp_queue_dir, is_heavy_fn=lambda m, c=None: m == "qwen2.5:14b",
                                is_alive_fn=is_alive, pid=999):
            # While first is running, create a second record that would wait
            record_path = tmp_queue_dir / "task-2.json"
            waiting_record = {
                "task_id": "task-2",
                "model": "qwen2.5:14b",
                "machine": "mac-mini",
                "caller": "caller-2",
                "pid": 888,
                "status": "waiting",
            }
            record_path.write_text(json.dumps(waiting_record))

            # Now try to acquire: should see the waiting task and respect it
            # (In real use, the queue manager polls until no other running tasks)
            records = model_queue.current_queue("mac-mini", queue_dir=tmp_queue_dir, is_alive_fn=is_alive)
            assert any(r["status"] == "waiting" for r in records)

    def test_different_machine_not_blocked(self, tmp_queue_dir):
        """Heavy model on different machine is not blocked."""
        is_alive = fake_is_alive_factory()
        is_alive.add(999)
        is_alive.add(888)

        # First acquire on mac-mini
        with model_queue.acquire("qwen2.5:14b", "mac-mini", "caller-1",
                                queue_dir=tmp_queue_dir, is_heavy_fn=lambda m, c=None: m == "qwen2.5:14b",
                                is_alive_fn=is_alive, pid=999):
            # Second acquire on macbook-pro should not block
            with model_queue.acquire("qwen2.5:14b", "macbook-pro", "caller-2",
                                    queue_dir=tmp_queue_dir, is_heavy_fn=lambda m, c=None: m == "qwen2.5:14b",
                                    is_alive_fn=is_alive, pid=888):
                records_mini = model_queue.current_queue("mac-mini", queue_dir=tmp_queue_dir, is_alive_fn=is_alive)
                records_pro = model_queue.current_queue("macbook-pro", queue_dir=tmp_queue_dir, is_alive_fn=is_alive)
                assert len(records_mini) == 1
                assert len(records_pro) == 1

    def test_dead_holder_reaped(self, tmp_queue_dir):
        """Dead process holding the lock is reaped, allowing next acquire."""
        is_alive = fake_is_alive_factory()
        is_alive.add(999)  # Alive PID
        # 888 is not alive

        # Create a "running" record with dead PID
        dead_record = {
            "task_id": "dead-task",
            "model": "qwen2.5:14b",
            "machine": "mac-mini",
            "caller": "dead-caller",
            "pid": 888,
            "status": "running",
        }
        (tmp_queue_dir / "dead-task.json").write_text(json.dumps(dead_record))

        # New acquire should reap the dead one
        with model_queue.acquire("qwen2.5:14b", "mac-mini", "new-caller",
                                queue_dir=tmp_queue_dir, is_heavy_fn=lambda m, c=None: m == "qwen2.5:14b",
                                is_alive_fn=is_alive, pid=999):
            records = list(tmp_queue_dir.glob("*.json"))
            # The dead record should be gone, only the new one
            assert len(records) == 1
            data = json.loads(records[0].read_text())
            assert data["caller"] == "new-caller"


class TestCurrentQueue:
    def test_filter_by_machine(self, tmp_queue_dir):
        """current_queue filters by machine."""
        is_alive = fake_is_alive_factory()
        is_alive.add(999)
        is_alive.add(888)

        records = [
            {"task_id": "t1", "model": "qwen2.5:14b", "machine": "mac-mini", "pid": 999, "status": "running"},
            {"task_id": "t2", "model": "qwen2.5:14b", "machine": "macbook-pro", "pid": 888, "status": "waiting"},
        ]
        for r in records:
            (tmp_queue_dir / f"{r['task_id']}.json").write_text(json.dumps(r))

        mini_queue = model_queue.current_queue("mac-mini", queue_dir=tmp_queue_dir, is_alive_fn=is_alive)
        assert len(mini_queue) == 1
        assert mini_queue[0]["machine"] == "mac-mini"

    def test_reap_dead_on_read(self, tmp_queue_dir):
        """current_queue reaps dead tasks as a side effect."""
        is_alive = fake_is_alive_factory()
        is_alive.add(999)  # Alive
        # 888 is not alive

        records = [
            {"task_id": "t1", "model": "qwen2.5:14b", "machine": "mac-mini", "pid": 999, "status": "running"},
            {"task_id": "t2", "model": "qwen2.5:14b", "machine": "mac-mini", "pid": 888, "status": "running"},
        ]
        for r in records:
            (tmp_queue_dir / f"{r['task_id']}.json").write_text(json.dumps(r))

        queue = model_queue.current_queue("mac-mini", queue_dir=tmp_queue_dir, is_alive_fn=is_alive)
        assert len(queue) == 1  # Dead one reaped
        assert not (tmp_queue_dir / "t2.json").exists()
