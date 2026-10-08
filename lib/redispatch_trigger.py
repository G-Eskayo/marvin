"""Debounce mechanism for refilling dispatch slots (ADR 0052, ticket #196).

When a run finishes, _trigger_redispatch in run_ticket.py asks for a new scan.
Without debounce, N tickets finishing within seconds spawn N separate full scans.
With file-based leading-edge debounce, only the first request in a burst spawns
a scan after a short delay, allowing subsequent bursts to batch together.
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path


def request_scan(
    lock_path: Path | None = None,
    debounce_s: float = 3,
    acquire: callable = None,
    spawn_worker: callable = None,
) -> bool:
    """Try to acquire a debounce lock and spawn a delayed scan worker if this is the first caller.

    Returns True if we acquired the lock and spawned a worker, False if a scan was already scheduled.
    On first acquire, spawns _spawn_worker (injected for testing) which will sleep and then kick the scan.
    On later calls within the debounce window, returns False immediately.

    Args:
        lock_path: path to the lock file (default ~/.claude/dispatch/scan-pending.lock)
        debounce_s: seconds to wait before spawning the scan (default 3)
        acquire: injected lock-acquire function (default _acquire_lock); signature (path: Path) -> bool
        spawn_worker: injected worker-spawn function; signature (lock_path, debounce_s) -> None
    """
    lock_path = lock_path or Path.home() / ".claude" / "dispatch" / "scan-pending.lock"
    acquire = acquire or _acquire_lock
    spawn_worker = spawn_worker or _spawn_worker

    if acquire(lock_path):
        spawn_worker(lock_path, debounce_s)
        return True
    return False


def _acquire_lock(path: Path) -> bool:
    """Atomically create a lock file via os.O_CREAT | os.O_EXCL. Return True on success, False if already exists."""
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        os.close(fd)
        return True
    except FileExistsError:
        return False


def _spawn_worker(lock_path: Path, debounce_s: float) -> None:
    """Spawn a detached worker process that will sleep, delete the lock, and kick the scan.

    This runs in a separate session so the parent doesn't wait for it.
    """
    script = Path(__file__).resolve().parent / "redispatch_trigger.py"
    subprocess.Popen(
        [sys.executable, str(script), "--worker", str(lock_path), str(debounce_s)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL,
        start_new_session=True,
    )


def _worker_main(lock_path: Path, debounce_s: float) -> None:
    """Worker body: sleep, delete the lock, then spawn the real scan.

    This runs in its own session after being spawned by _spawn_worker.
    """
    time.sleep(debounce_s)
    lock_path.unlink(missing_ok=True)
    _spawn_scan()


def _spawn_scan() -> None:
    """Spawn the actual ticket_pipeline.py scan (same as the old _trigger_redispatch)."""
    script = Path(__file__).resolve().parent / "ticket_pipeline.py"
    subprocess.Popen(
        [sys.executable, str(script)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL,
        start_new_session=True,
    )


def _cli(argv: list[str]) -> None:
    """CLI entry for the worker: redispatch_trigger.py --worker <lock_path> <debounce_s>"""
    if len(argv) >= 3 and argv[0] == "--worker":
        try:
            lock_path = Path(argv[1])
            debounce_s = float(argv[2])
            _worker_main(lock_path, debounce_s)
        except (ValueError, OSError) as exc:
            print(f"[redispatch_trigger] worker failed: {exc}", file=sys.stderr)
            sys.exit(1)
    else:
        print("usage: redispatch_trigger.py --worker <lock_path> <debounce_s>", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    _cli(sys.argv[1:])
