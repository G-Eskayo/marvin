"""Per-Mac heavy-model queue: serializes access to models that can't coexist in memory (qwen2.5:14b, FLUX).

Records live in ~/.claude/model-queue/tasks/*.json with {task_id, model, machine, caller, pid, status}.
acquire() is a context manager: creates "waiting" record, polls until no other running heavy task on
the same machine, flips to "running", deletes on exit. Dead holders (crashed process) are reaped automatically.
"""
from __future__ import annotations

import json
import os
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

from dispatch_concurrency import partition_alive, _pid_alive

QUEUE_DIR = Path.home() / ".claude" / "model-queue" / "tasks"


def _read_task_records(tasks_dir: Path | None = None) -> list[dict]:
    """Glob *.json files in tasks_dir, skip unreadable/malformed files."""
    tasks_dir = tasks_dir or QUEUE_DIR
    records = []
    if not tasks_dir.exists():
        return records
    for f in tasks_dir.glob("*.json"):
        try:
            records.append(json.loads(f.read_text()))
        except (OSError, ValueError):
            pass
    return records


def _reap(dead: list[dict], tasks_dir: Path | None = None) -> None:
    """Unlink dead task record files."""
    tasks_dir = tasks_dir or QUEUE_DIR
    for rec in dead:
        task_id = rec.get("task_id")
        if task_id:
            (tasks_dir / f"{task_id}.json").unlink(missing_ok=True)


def current_queue(machine: str | None = None, queue_dir: Path | None = None,
                 reader=None, is_alive_fn=None) -> list[dict]:
    """Read alive task records, reaping dead ones as a side effect. Filter by machine if provided."""
    queue_dir = queue_dir or QUEUE_DIR
    reader = reader or _read_task_records
    is_alive = is_alive_fn or _pid_alive

    records = reader(queue_dir)
    alive, dead = partition_alive(records, is_alive)
    if dead:
        _reap(dead, queue_dir)

    if machine:
        alive = [r for r in alive if r.get("machine") == machine]

    return alive


@contextmanager
def acquire(model: str, machine: str, caller: str, queue_dir: Path | None = None,
           is_heavy_fn=None, is_alive_fn=None, pid: int | None = None):
    """Context manager for heavy-model queue gating. Light models pass through immediately.

    Only gates when is_heavy_fn(model) is true. Creates a task record, polls until no other
    running heavy task on the same machine, flips to running, yields, then deletes on exit.
    Dead holders are reaped automatically.
    """
    queue_dir = queue_dir or QUEUE_DIR
    is_heavy = is_heavy_fn or (lambda m, c=None: False)  # Default: everything is light
    is_alive = is_alive_fn or _pid_alive
    pid = pid or os.getpid()

    if not is_heavy(model):
        yield
        return

    queue_dir.mkdir(parents=True, exist_ok=True)
    task_id = uuid.uuid4().hex[:8]
    task_file = queue_dir / f"{task_id}.json"

    record = {
        "task_id": task_id,
        "model": model,
        "machine": machine,
        "caller": caller,
        "pid": pid,
        "status": "waiting",
    }

    try:
        task_file.write_text(json.dumps(record))

        while True:
            alive = current_queue(machine, queue_dir=queue_dir, is_alive_fn=is_alive)
            running = [r for r in alive if r["status"] == "running"]

            if not running:
                record["status"] = "running"
                task_file.write_text(json.dumps(record))
                break

            time.sleep(0.5)

        yield
    finally:
        task_file.unlink(missing_ok=True)


def _cli(argv: list[str]) -> int:
    """`model_queue.py current [--machine ID]` prints alive queue records as JSON."""
    import sys
    if argv[:1] == ["current"]:
        machine = None
        if len(argv) >= 3 and argv[1] == "--machine":
            machine = argv[2]
        print(json.dumps(current_queue(machine)))
        return 0
    print("usage: model_queue.py current [--machine ID]", file=sys.stderr)
    return 2


if __name__ == "__main__":
    import sys
    sys.exit(_cli(sys.argv[1:]))
