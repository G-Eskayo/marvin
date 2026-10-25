"""Test model_queue: per-machine heavy-model task coordination."""
import json
import os
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import model_queue
import model_registry


def test_task_record_serialization(tmp_path):
    """TaskRecord can be serialized to/from dict."""
    task = model_queue.TaskRecord(
        task_id="test-1",
        model="qwen2.5:14b",
        machine="macbook-pro",
        caller="paper-dive",
        pid=12345,
        status="running",
        created_at="2026-10-08T00:00:00+00:00",
        updated_at="2026-10-08T00:00:01+00:00",
    )
    data = task.to_dict()
    restored = model_queue.TaskRecord.from_dict(data)
    assert restored.task_id == "test-1"
    assert restored.pid == 12345


def test_write_and_read_task(tmp_path):
    """Tasks can be written and read atomically."""
    with patch.object(model_queue, 'QUEUE_DIR', tmp_path):
        task = model_queue.TaskRecord(
            task_id="test-1",
            model="FLUX.1-schnell-4bit",
            machine="mac-mini",
            caller="portfolio-flux",
            pid=os.getpid(),
            status="running",
            created_at=model_queue._timestamp(),
            updated_at=model_queue._timestamp(),
        )
        model_queue._write_task(task)
        restored = model_queue._read_task("test-1")
        assert restored is not None
        assert restored.model == "FLUX.1-schnell-4bit"


def test_list_tasks_filters_by_machine(tmp_path):
    """_list_tasks() filters by machine."""
    with patch.object(model_queue, 'QUEUE_DIR', tmp_path):
        task1 = model_queue.TaskRecord(
            task_id="test-1", model="model1", machine="macbook-pro",
            caller="caller1", pid=100, status="running",
            created_at="2026-10-08T00:00:00+00:00",
            updated_at="2026-10-08T00:00:00+00:00",
        )
        task2 = model_queue.TaskRecord(
            task_id="test-2", model="model2", machine="mac-mini",
            caller="caller2", pid=101, status="running",
            created_at="2026-10-08T00:00:00+00:00",
            updated_at="2026-10-08T00:00:00+00:00",
        )
        model_queue._write_task(task1)
        model_queue._write_task(task2)

        all_tasks = model_queue._list_tasks()
        assert len(all_tasks) == 2

        mac_mini_tasks = model_queue._list_tasks(machine="mac-mini")
        assert len(mac_mini_tasks) == 1
        assert mac_mini_tasks[0].machine == "mac-mini"


def test_list_tasks_filters_by_status(tmp_path):
    """_list_tasks() filters by status."""
    with patch.object(model_queue, 'QUEUE_DIR', tmp_path):
        task1 = model_queue.TaskRecord(
            task_id="test-1", model="model1", machine="mac",
            caller="caller1", pid=100, status="running",
            created_at="2026-10-08T00:00:00+00:00",
            updated_at="2026-10-08T00:00:00+00:00",
        )
        task2 = model_queue.TaskRecord(
            task_id="test-2", model="model2", machine="mac",
            caller="caller2", pid=101, status="completed",
            created_at="2026-10-08T00:00:00+00:00",
            updated_at="2026-10-08T00:00:00+00:00",
        )
        model_queue._write_task(task1)
        model_queue._write_task(task2)

        running = model_queue._list_tasks(status="running")
        assert len(running) == 1
        assert running[0].status == "running"


def test_is_pid_alive_with_current_pid():
    """_is_pid_alive() returns True for the current process."""
    assert model_queue._is_pid_alive(os.getpid()) is True


def test_is_pid_alive_with_dead_pid():
    """_is_pid_alive() returns False for a non-existent process."""
    # Use a very high PID that's unlikely to exist
    assert model_queue._is_pid_alive(999999999) is False


def test_acquire_light_model_passes_through(tmp_path):
    """Light models (non-heavy) pass through acquire() with no queueing."""
    with patch.object(model_queue, 'QUEUE_DIR', tmp_path):
        with patch.object(model_registry, 'is_heavy', return_value=False):
            with model_queue.acquire("qwen2.5:3b", "mac-mini", "test") as task:
                assert task.model == "qwen2.5:3b"
                assert task.status == "running"
            # No queue entry should exist for light models
            tasks = model_queue._list_tasks()
            assert len(tasks) == 0


def test_acquire_heavy_model_creates_queue_entry(tmp_path):
    """Heavy models create task records in the queue."""
    with patch.object(model_queue, 'QUEUE_DIR', tmp_path):
        with patch.object(model_registry, 'is_heavy', return_value=True):
            with model_queue.acquire("qwen2.5:14b", "macbook-pro", "paper-dive") as task:
                assert task.model == "qwen2.5:14b"
                assert task.status == "running"
                # Task should be in queue while context is active
                tasks = model_queue._list_tasks(status="running")
                assert any(t.task_id == task.task_id for t in tasks)

            # After context exit, task should be completed
            tasks = model_queue._list_tasks(status="completed")
            assert any(t.task_id == task.task_id for t in tasks)


def test_acquire_blocks_on_concurrent_heavy_task(tmp_path):
    """acquire() blocks when another heavy task is running on the same machine."""
    with patch.object(model_queue, 'QUEUE_DIR', tmp_path):
        with patch.object(model_registry, 'is_heavy', return_value=True):
            # Manually create a running task
            existing = model_queue.TaskRecord(
                task_id="existing", model="qwen2.5:14b", machine="mac-mini",
                caller="other", pid=99999,  # dead pid
                status="running",
                created_at=model_queue._timestamp(),
                updated_at=model_queue._timestamp(),
            )
            model_queue._write_task(existing)

            # Try to acquire with a short timeout and expect failure
            with pytest.raises(TimeoutError):
                with model_queue.acquire(
                    "qwen2.5:14b", "mac-mini", "test",
                    timeout=0.1, poll_interval=0.05
                ) as task:
                    pass


def test_acquire_ignores_dead_tasks(tmp_path):
    """acquire() reaps dead tasks and proceeds."""
    with patch.object(model_queue, 'QUEUE_DIR', tmp_path):
        with patch.object(model_registry, 'is_heavy', return_value=True):
            # Create a task with a dead PID
            dead = model_queue.TaskRecord(
                task_id="dead-task", model="qwen2.5:14b", machine="mac-mini",
                caller="dead-caller", pid=999999999,  # non-existent
                status="running",
                created_at=model_queue._timestamp(),
                updated_at=model_queue._timestamp(),
            )
            model_queue._write_task(dead)

            # Should acquire without blocking (dead task reaped)
            with model_queue.acquire("qwen2.5:14b", "mac-mini", "test") as task:
                assert task.model == "qwen2.5:14b"
                # Dead task should be reaped
                remaining = model_queue._list_tasks()
                assert not any(t.task_id == "dead-task" for t in remaining)


def test_current_queue_returns_running_tasks(tmp_path):
    """current_queue() returns all running tasks, sorted by creation time."""
    with patch.object(model_queue, 'QUEUE_DIR', tmp_path):
        # Create some tasks
        for i in range(3):
            task = model_queue.TaskRecord(
                task_id=f"task-{i}", model="model", machine="mac",
                caller=f"caller-{i}", pid=100+i, status="running",
                created_at=f"2026-10-08T00:00:{i:02d}+00:00",
                updated_at=f"2026-10-08T00:00:{i:02d}+00:00",
            )
            model_queue._write_task(task)

        queue = model_queue.current_queue()
        assert len(queue) == 3
        # Should be sorted by creation time
        for i in range(len(queue) - 1):
            assert queue[i].created_at <= queue[i+1].created_at


def test_current_queue_filters_by_machine(tmp_path):
    """current_queue() filters by machine when specified."""
    with patch.object(model_queue, 'QUEUE_DIR', tmp_path):
        task1 = model_queue.TaskRecord(
            task_id="task-1", model="model", machine="macbook-pro",
            caller="c1", pid=100, status="running",
            created_at="2026-10-08T00:00:00+00:00",
            updated_at="2026-10-08T00:00:00+00:00",
        )
        task2 = model_queue.TaskRecord(
            task_id="task-2", model="model", machine="mac-mini",
            caller="c2", pid=101, status="running",
            created_at="2026-10-08T00:00:00+00:00",
            updated_at="2026-10-08T00:00:00+00:00",
        )
        model_queue._write_task(task1)
        model_queue._write_task(task2)

        queue = model_queue.current_queue(machine="mac-mini")
        assert len(queue) == 1
        assert queue[0].machine == "mac-mini"
