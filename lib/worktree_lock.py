#!/usr/bin/env python3
"""Worktree concurrency isolation via flock-based locks (ADR 0XX).

Prevents concurrent `git worktree add` on the same branch when multiple
machines or processes try to work on the same ticket in parallel.
Holds the lock for the entire lifetime of _create_worktree and the work
that follows, bound by process exit (never explicitly released).
"""
from __future__ import annotations

import fcntl
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path


class WorktreeBusy(Exception):
    """The worktree for this branch is already locked by another process."""
    def __init__(self, holder: dict):
        self.holder = holder
        super().__init__(f"worktree locked by {holder.get('who')} (pid {holder.get('pid')}, started {holder.get('started_at')})")


@dataclass
class LockHandle:
    """Returned by acquire(): holds the lock file and its fd."""
    path: Path
    fd: int

    def release(self):
        """Release the lock (unlock and close fd). Called implicitly on process exit."""
        try:
            fcntl.flock(self.fd, fcntl.LOCK_UN)
        except (OSError, ValueError):
            pass
        try:
            os.close(self.fd)
        except (OSError, ValueError):
            pass


def _lock_path(clone: Path, branch: str) -> Path:
    """Compute the lock file path: clone/.git/marvin-worktree-locks/<safe-branch>.lock"""
    safe_branch = branch.replace("/", "-").replace("#", "-")
    lock_dir = clone / ".git" / "marvin-worktree-locks"
    lock_dir.mkdir(parents=True, exist_ok=True)
    return lock_dir / f"{safe_branch}.lock"


def acquire(clone: Path, branch: str, who: str, wait_s: float = 0.0) -> LockHandle:
    """Acquire an flock-based lock for this branch's worktree.

    Args:
        clone: path to the shared git repository
        branch: the branch name (e.g., "pipeline/ticket-123")
        who: a string identifying the holder (e.g., "ticket-123" or "auto-fix/2026-11-25")
        wait_s: seconds to wait if the lock is held; 0 = no wait (raises immediately)

    Returns:
        LockHandle (fd + path)

    Raises:
        WorktreeBusy: if the lock is held after wait_s seconds

    The lock is held by the process until it exits. Lock state (pid, who, started_at)
    is written to the lock file once acquired.
    """
    lock_file = _lock_path(clone, branch)
    lock_file.touch()

    fd = os.open(str(lock_file), os.O_WRONLY | os.O_CLOEXEC)
    try:
        end_time = time.time() + wait_s if wait_s > 0 else time.time()
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                # Lock acquired: write state
                holder = {
                    "pid": os.getpid(),
                    "who": who,
                    "started_at": time.time(),
                }
                lock_file.write_text(json.dumps(holder))
                return LockHandle(path=lock_file, fd=fd)
            except BlockingIOError:
                if time.time() >= end_time:
                    holder_state = read(clone, branch)
                    raise WorktreeBusy(holder_state)
                time.sleep(0.1)
    except Exception:
        os.close(fd)
        raise


def read(clone: Path, branch: str) -> dict:
    """Peek at the lock without acquiring it. Returns the holder dict (empty dict if unlocked/unreadable)."""
    lock_file = _lock_path(clone, branch)
    if not lock_file.exists():
        return {}
    try:
        return json.loads(lock_file.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def is_locked(clone: Path, branch: str) -> bool:
    """Quick check: is this branch's worktree currently locked?
    Uses a try-lock (no wait) to avoid blocking."""
    lock_file = _lock_path(clone, branch)
    if not lock_file.exists():
        return False

    try:
        fd = os.open(str(lock_file), os.O_WRONLY | os.O_CLOEXEC)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)
            return False  # We got the lock, so it wasn't held
        except BlockingIOError:
            os.close(fd)
            return True  # Couldn't get it, so it's locked
    except (OSError, ValueError):
        return False  # Can't check, assume unlocked


__all__ = [
    "WorktreeBusy",
    "LockHandle",
    "acquire",
    "read",
    "is_locked",
]
