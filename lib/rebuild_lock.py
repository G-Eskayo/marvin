#!/usr/bin/env python3
"""Simple PID-based file lock for dashboard rebuilds.

Prevents two rebuilds from running concurrently: one process writes its PID to a lock
file; another checks whether the PID is alive before attempting to acquire it.
If alive, the lock is held; if dead or stale, it's taken.

This is not a reentrant lock and is not held across process boundaries (the rebuild script
runs detached from the checker). It's just a "is a rebuild already running?" gate.
"""
import os
import signal
from pathlib import Path


def pid_alive(pid: int) -> bool:
    """Check whether a process with this PID is still running."""
    try:
        os.kill(pid, 0)  # 0 signal is a no-op that only checks if the process exists
        return True
    except (OSError, ValueError):
        return False


def try_acquire(lock_dir: Path, pid: int) -> bool:
    """Attempt to acquire the lock. Returns True if successful, False if already held."""
    lock_dir.mkdir(parents=True, exist_ok=True)
    lock_file = lock_dir / "rebuild.lock"

    if lock_file.exists():
        try:
            existing_pid = int(lock_file.read_text().strip())
            if pid_alive(existing_pid):
                return False  # Lock is held
        except (ValueError, OSError):
            pass  # Stale or corrupt lock, we'll overwrite it

    # Write our PID and return success
    lock_file.write_text(str(pid))
    return True


def release(lock_dir: Path, pid: int) -> None:
    """Release the lock if we hold it (no-op if we don't)."""
    lock_file = lock_dir / "rebuild.lock"
    if lock_file.exists():
        try:
            existing_pid = int(lock_file.read_text().strip())
            if existing_pid == pid:
                lock_file.unlink()
        except (ValueError, OSError):
            pass


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 3:
        print(f"Usage: {sys.argv[0]} (acquire|release) <lock_dir>", file=sys.stderr)
        sys.exit(1)

    command = sys.argv[1]
    lock_dir = Path(sys.argv[2])
    pid = os.getpid()

    if command == "acquire":
        if try_acquire(lock_dir, pid):
            print("OK")
            sys.exit(0)
        else:
            print("BUSY")
            sys.exit(1)
    elif command == "release":
        release(lock_dir, pid)
        sys.exit(0)
    else:
        print(f"Unknown command: {command}", file=sys.stderr)
        sys.exit(1)
