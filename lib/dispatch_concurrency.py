#!/usr/bin/env python3
"""Per-task dispatch concurrency: tracks running tasks by recording them to disk,
reaps dead processes, and maintains dispatch-state.json summary. Implements the
counting/reaping logic from ADR 0052.

Reuses DISPATCH_STATE_PATH from task_dispatch; per-task records live in
TASKS_DIR (one JSON file per running task, removed on exit). A liveness checker
partitions live from dead records; the summary refresher builds dispatch-state.json
from the alive set.

Run standalone:
  ~/.agents/venv/bin/python dispatch_concurrency.py slots-in-use [--machine ID]
  ~/.agents/venv/bin/python dispatch_concurrency.py refresh-summary
"""
from __future__ import annotations
import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

DISPATCH_STATE_PATH = Path.home() / ".claude" / "dispatch-state.json"
TASKS_DIR = Path.home() / ".claude" / "dispatch" / "tasks"
SSH_OPTS = ["-o", "ConnectTimeout=5", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=accept-new"]


def partition_alive(records: list[dict], is_alive) -> tuple[list[dict], list[dict]]:
    """Pure: split records into (alive, dead) based on injected liveness checker."""
    alive = []
    dead = []
    for record in records:
        pid = record.get("pid")
        if pid and is_alive(pid):
            alive.append(record)
        else:
            dead.append(record)
    return alive, dead


def _pid_alive(pid: int) -> bool:
    """Real liveness check: send signal 0 to the process (no-op signal, just tests existence)."""
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False


def _read_records() -> list[dict]:
    """Read all task records from TASKS_DIR. Returns empty list if dir doesn't exist."""
    if not TASKS_DIR.exists():
        return []
    records = []
    try:
        for record_file in TASKS_DIR.glob("*.json"):
            try:
                record = json.loads(record_file.read_text())
                records.append(record)
            except (json.JSONDecodeError, OSError):
                pass  # skip malformed or inaccessible records
    except OSError:
        pass  # TASKS_DIR exists but is unreadable
    return records


def _reap(dead: list[dict]) -> None:
    """Remove dead process records from disk."""
    if not TASKS_DIR.exists():
        return
    for record in dead:
        task_id = record.get("task_id")
        if task_id:
            record_file = TASKS_DIR / f"{task_id}.json"
            try:
                record_file.unlink(missing_ok=True)
            except OSError:
                pass


def machine_slot_ceiling(machine: str) -> int:
    """Hardcoded per-machine slot limit from ADR 0052 D2."""
    ceilings = {
        "mac-mini-1": 2,
        "macbook-pro-1": 1,
    }
    return ceilings.get(machine, 1)


def slots_in_use(machine: str | None = None, is_alive=None, reader=None) -> list[dict]:
    """Read local task records, optionally filtered by machine, reap dead ones, return alive list."""
    if is_alive is None:
        is_alive = _pid_alive
    if reader is None:
        reader = _read_records

    records = reader()
    if machine:
        records = [r for r in records if r.get("machine") == machine]

    alive, dead = partition_alive(records, is_alive)
    _reap(dead)
    return alive


def slots_in_use_remote(host: str, machine: str, run=None) -> list[dict] | None:
    """SSH into remote host and invoke this module to get its slot usage.
    Returns None on ssh/parse failure (distinguishable from empty list)."""
    if run is None:
        run = subprocess.run

    try:
        proc = run(
            ["ssh", *SSH_OPTS, host,
             f"~/.agents/venv/bin/python ~/.agents/lib/dispatch_concurrency.py slots-in-use --machine {machine}"],
            capture_output=True, text=True, timeout=10,
        )
        if proc.returncode != 0 or not proc.stdout.strip():
            return None
        return json.loads(proc.stdout)
    except Exception:
        return None


def refresh_dispatch_state_summary() -> None:
    """Recompute dispatch-state.json from current alive records.
    If any records exist, mark busy with the earliest-started one; else idle."""
    alive = slots_in_use()
    if not alive:
        state = {"busy": False}
    else:
        earliest = min(alive, key=lambda r: r.get("started_at", ""))
        state = {
            "busy": True,
            "task": earliest.get("task"),
            "task_id": earliest.get("task_id"),
            "started_at": earliest.get("started_at"),
        }
    DISPATCH_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    DISPATCH_STATE_PATH.write_text(json.dumps(state))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    sp = ap.add_subparsers(dest="command")

    slots_cmd = sp.add_parser("slots-in-use", help="List running tasks")
    slots_cmd.add_argument("--machine", default=None, help="filter by machine id")

    sp.add_parser("refresh-summary", help="Recompute dispatch-state.json from task records")

    args = ap.parse_args()

    if args.command == "slots-in-use":
        records = slots_in_use(machine=args.machine)
        print(json.dumps(records))
    elif args.command == "refresh-summary":
        refresh_dispatch_state_summary()
    else:
        ap.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
