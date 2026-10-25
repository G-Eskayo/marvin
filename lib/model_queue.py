#!/usr/bin/env python3
"""Heavy-model task queue — per-machine coordination for models that can't coexist in 16GB.

Task records live in ~/.claude/model-queue/tasks/*.json with format:
{task_id, model, machine, caller, pid, status: "running"|"completed"|"failed"}

acquire() is a context manager that:
1. Checks if any other "running" heavy task exists on the same machine
2. If so, polls until cleared or timeout
3. Creates this task's record with status=running
4. On exit, updates status to completed/failed
5. Dead task holders (crashed pids) are reaped via dispatch_concurrency helpers
"""
from __future__ import annotations

import json
import os
import sys
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Generator, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dispatch_concurrency
import model_registry

HOME = Path.home()
QUEUE_DIR = HOME / ".claude" / "model-queue" / "tasks"


@dataclass
class TaskRecord:
    task_id: str
    model: str
    machine: str
    caller: str
    pid: int
    status: str  # running, completed, failed
    created_at: str
    updated_at: str

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "model": self.model,
            "machine": self.machine,
            "caller": self.caller,
            "pid": self.pid,
            "status": self.status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @staticmethod
    def from_dict(data: dict) -> TaskRecord:
        return TaskRecord(
            task_id=data["task_id"],
            model=data["model"],
            machine=data["machine"],
            caller=data["caller"],
            pid=data["pid"],
            status=data["status"],
            created_at=data["created_at"],
            updated_at=data["updated_at"],
        )


def _timestamp() -> str:
    """ISO 8601 timestamp."""
    return datetime.now(timezone.utc).isoformat()


def _task_path(task_id: str) -> Path:
    """Path to a task record file."""
    return QUEUE_DIR / f"{task_id}.json"


def _write_task(task: TaskRecord) -> None:
    """Write a task record atomically."""
    QUEUE_DIR.mkdir(parents=True, exist_ok=True)
    path = _task_path(task.task_id)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(task.to_dict(), indent=2))
    os.replace(tmp, path)


def _read_task(task_id: str) -> Optional[TaskRecord]:
    """Read a task record, or None if not found."""
    path = _task_path(task_id)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
        return TaskRecord.from_dict(data)
    except Exception:
        return None


def _list_tasks(machine: Optional[str] = None, status: Optional[str] = None) -> list[TaskRecord]:
    """List all task records, optionally filtered by machine and status."""
    if not QUEUE_DIR.exists():
        return []
    tasks = []
    for path in QUEUE_DIR.glob("*.json"):
        try:
            data = json.loads(path.read_text())
            task = TaskRecord.from_dict(data)
            if machine and task.machine != machine:
                continue
            if status and task.status != status:
                continue
            tasks.append(task)
        except Exception:
            continue
    return tasks


def _is_pid_alive(pid: int) -> bool:
    """Check if a process is still alive (via dispatch_concurrency if available)."""
    try:
        if hasattr(dispatch_concurrency, '_pid_alive'):
            return dispatch_concurrency._pid_alive(pid)
    except Exception:
        pass
    # Fallback: try to send signal 0 (check if process exists)
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except Exception:
        return True  # assume alive if we can't check


def _reap_dead_tasks(machine: str) -> None:
    """Remove task records for dead processes on the machine."""
    tasks = _list_tasks(machine=machine, status="running")
    for task in tasks:
        if not _is_pid_alive(task.pid):
            path = _task_path(task.task_id)
            try:
                path.unlink()
            except Exception:
                pass


def current_queue(machine: Optional[str] = None) -> list[TaskRecord]:
    """Get current queue: all running tasks, optionally filtered by machine."""
    tasks = _list_tasks(status="running")
    if machine:
        tasks = [t for t in tasks if t.machine == machine]
    return sorted(tasks, key=lambda t: t.created_at)


@contextmanager
def acquire(
    model: str,
    machine: str,
    caller: str,
    task_id: Optional[str] = None,
    timeout: int = 600,
    poll_interval: float = 1.0,
) -> Generator[TaskRecord, None, None]:
    """Acquire a heavy-model task lock, blocking until no other heavy task is running.

    Args:
        model: Model name (e.g., "FLUX.1-schnell-4bit")
        machine: Machine label (e.g., "macbook-pro")
        caller: Caller identifier (e.g., "portfolio-flux")
        task_id: Unique task ID (auto-generated if None)
        timeout: Max wait time in seconds
        poll_interval: Check interval in seconds

    Context manager yields the TaskRecord, updates its status on exit.
    Raises TimeoutError if timeout exceeded.
    """
    if not model_registry.is_heavy(model):
        # Light models pass through with no queueing
        dummy = TaskRecord(
            task_id=task_id or f"{caller}-{int(time.time())}",
            model=model,
            machine=machine,
            caller=caller,
            pid=os.getpid(),
            status="running",
            created_at=_timestamp(),
            updated_at=_timestamp(),
        )
        yield dummy
        return

    task_id = task_id or f"{caller}-{int(time.time()*1000)}"
    start = time.time()
    task = TaskRecord(
        task_id=task_id,
        model=model,
        machine=machine,
        caller=caller,
        pid=os.getpid(),
        status="running",
        created_at=_timestamp(),
        updated_at=_timestamp(),
    )

    try:
        # Poll until no other heavy task is running on this machine
        while True:
            _reap_dead_tasks(machine)
            other_running = [
                t for t in current_queue(machine=machine)
                if t.task_id != task_id and t.status == "running"
            ]
            if not other_running:
                break

            elapsed = time.time() - start
            if elapsed > timeout:
                raise TimeoutError(f"model queue timeout after {elapsed:.1f}s waiting for {model}")

            time.sleep(poll_interval)

        # Write our task record
        _write_task(task)
        yield task

    finally:
        # Mark as completed (or failed if exception occurred)
        task.status = "completed"
        task.updated_at = _timestamp()
        _write_task(task)


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description=__doc__)
    subparsers = ap.add_subparsers(dest="cmd")

    current_cmd = subparsers.add_parser("current", help="Show current queue")
    current_cmd.add_argument("--machine", help="Filter by machine")

    args = ap.parse_args()

    if args.cmd == "current":
        queue = current_queue(machine=args.machine)
        for task in queue:
            print(json.dumps(task.to_dict(), indent=2))
    else:
        print("model_queue.py [current [--machine ID]]")
