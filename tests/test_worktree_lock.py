#!/usr/bin/env python3
"""Tests for lib/worktree_lock.py -- flock-based worktree concurrency control."""
import json
import os
import subprocess
import tempfile
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))
import worktree_lock as wl


# ─── Fixture: temp repository structure ────────────────────────────────────

@pytest.fixture
def temp_repo():
    """Create a temporary directory structure resembling a git repo."""
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = Path(tmpdir) / "test_repo"
        repo.mkdir()
        git_dir = repo / ".git"
        git_dir.mkdir()
        yield repo


# ─── Test 1: _lock_path generates correct paths ────────────────────────────

def test_lock_path_basic(temp_repo):
    """_lock_path creates the lock directory and returns correct path."""
    lock_file = wl._lock_path(temp_repo, "pipeline/ticket-123")
    assert lock_file.parent == temp_repo / ".git" / "marvin-worktree-locks"
    assert lock_file.parent.exists()
    assert "pipeline-ticket-123" in str(lock_file)
    assert lock_file.name == "pipeline-ticket-123.lock"


def test_lock_path_escapes_special_chars(temp_repo):
    """_lock_path replaces / and # with - for safe filenames."""
    lock_file = wl._lock_path(temp_repo, "pipeline/ticket#123")
    assert "/" not in lock_file.name
    assert "#" not in lock_file.name
    assert lock_file.name == "pipeline-ticket-123.lock"


# ─── Test 2: acquire() gets exclusive lock and writes holder state ────────

def test_acquire_basic(temp_repo):
    """acquire() locks the file and writes holder state."""
    handle = wl.acquire(temp_repo, "pipeline/ticket-1", "ticket-1")
    try:
        assert handle.fd >= 0
        assert handle.path.exists()
        holder = json.loads(handle.path.read_text())
        assert holder["pid"] == os.getpid()
        assert holder["who"] == "ticket-1"
        assert "started_at" in holder
    finally:
        handle.release()


def test_acquire_no_wait_fails_if_locked(temp_repo):
    """acquire() with wait_s=0 raises immediately if already locked."""
    handle1 = wl.acquire(temp_repo, "pipeline/ticket-2", "holder1")
    try:
        with pytest.raises(wl.WorktreeBusy) as exc_info:
            wl.acquire(temp_repo, "pipeline/ticket-2", "holder2", wait_s=0.0)
        assert exc_info.value.holder["who"] == "holder1"
    finally:
        handle1.release()


def test_acquire_waits_then_raises(temp_repo):
    """acquire() waits wait_s seconds before raising."""
    handle1 = wl.acquire(temp_repo, "pipeline/ticket-3", "holder1")
    try:
        start = time.time()
        with pytest.raises(wl.WorktreeBusy):
            wl.acquire(temp_repo, "pipeline/ticket-3", "holder2", wait_s=0.3)
        elapsed = time.time() - start
        assert 0.2 < elapsed < 0.6  # Allow some jitter
    finally:
        handle1.release()


def test_acquire_different_branches_dont_conflict(temp_repo):
    """acquire() on different branches succeeds independently."""
    handle1 = wl.acquire(temp_repo, "pipeline/ticket-4a", "ticket4a")
    handle2 = wl.acquire(temp_repo, "pipeline/ticket-4b", "ticket4b")
    try:
        assert handle1.fd != handle2.fd
        h1 = json.loads(handle1.path.read_text())
        h2 = json.loads(handle2.path.read_text())
        assert h1["who"] == "ticket4a"
        assert h2["who"] == "ticket4b"
    finally:
        handle1.release()
        handle2.release()


# ─── Test 3: LockHandle.release() unlocks and closes fd ────────────────────

def test_lock_handle_release(temp_repo):
    """LockHandle.release() unlocks the file and closes the fd."""
    handle = wl.acquire(temp_repo, "pipeline/ticket-5", "holder")
    fd = handle.fd
    path = handle.path

    handle.release()

    # After release, the fd should be invalid
    with pytest.raises(OSError):
        os.fstat(fd)

    # After release, we should be able to acquire a new lock on the same path
    handle2 = wl.acquire(temp_repo, "pipeline/ticket-5", "new_holder", wait_s=0.1)
    try:
        # Verify the new lock succeeded and has different holder info
        holder = json.loads(path.read_text())
        assert holder["who"] == "new_holder"
        # The new lock should be open (fd should be valid)
        assert os.fstat(handle2.fd) is not None
    finally:
        handle2.release()


# ─── Test 4: read() peeks at lock state without acquiring ──────────────────

def test_read_locked(temp_repo):
    """read() returns holder state without acquiring the lock."""
    handle = wl.acquire(temp_repo, "pipeline/ticket-6", "holder_a")
    try:
        holder = wl.read(temp_repo, "pipeline/ticket-6")
        assert holder["pid"] == os.getpid()
        assert holder["who"] == "holder_a"
        # The lock is still held by the original acquire
        with pytest.raises(wl.WorktreeBusy):
            wl.acquire(temp_repo, "pipeline/ticket-6", "holder_b", wait_s=0)
    finally:
        handle.release()


def test_read_unlocked(temp_repo):
    """read() on an unlocked branch returns empty dict."""
    holder = wl.read(temp_repo, "pipeline/ticket-7")
    assert holder == {}


def test_read_malformed_lock_file(temp_repo):
    """read() tolerates a corrupted lock file (returns empty dict)."""
    lock_file = wl._lock_path(temp_repo, "pipeline/ticket-8")
    lock_file.write_text("{ invalid json")
    holder = wl.read(temp_repo, "pipeline/ticket-8")
    assert holder == {}


# ─── Test 5: is_locked() quick boolean check ──────────────────────────────

def test_is_locked_locked(temp_repo):
    """is_locked() returns True for a locked branch."""
    handle = wl.acquire(temp_repo, "pipeline/ticket-9", "holder")
    try:
        assert wl.is_locked(temp_repo, "pipeline/ticket-9") is True
    finally:
        handle.release()


def test_is_locked_unlocked(temp_repo):
    """is_locked() returns False for an unlocked branch."""
    assert wl.is_locked(temp_repo, "pipeline/ticket-10") is False


def test_is_locked_no_wait(temp_repo):
    """is_locked() doesn't block; it's a quick try-lock."""
    handle = wl.acquire(temp_repo, "pipeline/ticket-11", "holder")
    try:
        start = time.time()
        result = wl.is_locked(temp_repo, "pipeline/ticket-11")
        elapsed = time.time() - start
        assert result is True
        assert elapsed < 0.5  # Should be nearly instant
    finally:
        handle.release()


def test_is_locked_missing_lock_file(temp_repo):
    """is_locked() returns False if lock file doesn't exist."""
    # Explicitly ensure lock file doesn't exist
    lock_file = wl._lock_path(temp_repo, "pipeline/ticket-12")
    if lock_file.exists():
        lock_file.unlink()
    assert wl.is_locked(temp_repo, "pipeline/ticket-12") is False


# ─── Test 6: WorktreeBusy exception carries holder info ────────────────────

def test_worktree_busy_exception(temp_repo):
    """WorktreeBusy exception includes holder information."""
    handle = wl.acquire(temp_repo, "pipeline/ticket-13", "blocker")
    try:
        with pytest.raises(wl.WorktreeBusy) as exc_info:
            wl.acquire(temp_repo, "pipeline/ticket-13", "attempt", wait_s=0)
        exc = exc_info.value
        assert exc.holder["who"] == "blocker"
        assert exc.holder["pid"] == os.getpid()
        assert "blocker" in str(exc)
        assert str(exc.holder["pid"]) in str(exc)
    finally:
        handle.release()


# ─── Test 7: Locks persist across subprocess calls ────────────────────────

def test_lock_held_across_external_check(temp_repo):
    """Acquiring a lock prevents an external process from acquiring it."""
    handle = wl.acquire(temp_repo, "pipeline/ticket-14", "main_process")
    try:
        # Try to acquire the lock from a subprocess
        script = f"""
import sys
sys.path.insert(0, {str(Path(__file__).resolve().parent.parent / "lib")!r})
import worktree_lock as wl
from pathlib import Path
repo = Path({str(temp_repo)!r})
try:
    wl.acquire(repo, "pipeline/ticket-14", "subprocess", wait_s=0.1)
    sys.exit(0)  # Got lock (bad)
except wl.WorktreeBusy:
    sys.exit(1)  # Couldn't get lock (good)
"""
        result = subprocess.run(
            ["python3", "-c", script],
            capture_output=True,
            timeout=5
        )
        # Subprocess should have failed to acquire (exit 1)
        assert result.returncode == 1
    finally:
        handle.release()


# ─── Test 8: Multiple locks coexist independently ───────────────────────────

def test_multiple_independent_locks(temp_repo):
    """Many branches can be locked independently."""
    handles = []
    try:
        for i in range(5):
            handle = wl.acquire(temp_repo, f"pipeline/ticket-{15+i}", f"holder-{i}")
            handles.append(handle)

        # Verify all are locked
        for i in range(5):
            assert wl.is_locked(temp_repo, f"pipeline/ticket-{15+i}") is True

        # Verify each holder's state
        for i in range(5):
            holder = wl.read(temp_repo, f"pipeline/ticket-{15+i}")
            assert holder["who"] == f"holder-{i}"

        # Try to acquire any of them and fail
        with pytest.raises(wl.WorktreeBusy):
            wl.acquire(temp_repo, "pipeline/ticket-15", "interloper", wait_s=0)

    finally:
        for handle in handles:
            handle.release()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
