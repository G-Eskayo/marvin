"""Tests for chroma_onnx_lock.py (marvin#1156: serialize chromadb's lazy ONNX model download to prevent
race on cold CI runners).

The module under test protects ONNXMiniLM_L6_V2._download_model_if_not_exists with fcntl.flock to
serialize concurrent workers and close a TOCTOU race under -n auto (pytest-xdist). Tests run offline,
against a stub shaped like ONNXMiniLM_L6_V2, plus one integration check against the real class.

Run via: ~/.agents/venv/bin/python -m pytest lib/tests/test_chroma_onnx_lock.py -v
"""
from __future__ import annotations
import fcntl
import os
import sys
import tempfile
import threading
import time
from pathlib import Path
from unittest import mock

import pytest

LIB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LIB))

import chroma_onnx_lock  # noqa: E402


def make_stub_class(download_path):
    """Create a stub class shaped like ONNXMiniLM_L6_V2."""
    class StubONNX:
        DOWNLOAD_PATH = download_path
        call_count = 0
        call_times = []

        @classmethod
        def _download_model_if_not_exists(cls):
            """Simulate the real control flow: check exists → verify (TOCTOU gap) → extract."""
            cls.call_count += 1
            cls.call_times.append(time.time())

            # Simulate exists check.
            if cls.DOWNLOAD_PATH.exists():
                return

            # Simulate the real TOCTOU gap: check passes, but before we verify/extract,
            # another thread might delete the file.
            time.sleep(0.01)

            # Now try to "verify" by opening. This is where the real code hits
            # FileNotFoundError if another thread deleted it mid-gap.
            try:
                with open(cls.DOWNLOAD_PATH, "rb") as f:
                    pass  # Simulate verification read.
            except FileNotFoundError:
                raise  # Re-raise to match real behavior.

    return StubONNX


@pytest.fixture
def temp_cache_dir(tmp_path):
    """Create a temporary cache directory shaped like chromadb's real cache."""
    cache_dir = tmp_path / "cache" / "chroma"
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir


def test_1_race_unprotected_fails_protected_succeeds(temp_cache_dir):
    """Test 1: Concurrent execution: unprotected allows overlapping calls, protected serializes."""
    # Track concurrent execution depth (max threads in method at once)
    unprotected_depth = {"current": 0, "max": 0}
    unprotected_depth_lock = threading.Lock()
    unprotected_barrier = threading.Barrier(2)

    class RacyUnprotected:
        DOWNLOAD_PATH = temp_cache_dir / "unprotected.tar.gz"

        @classmethod
        def _download_model_if_not_exists(cls):
            if cls.DOWNLOAD_PATH.exists():
                return

            # Track entry: increment depth
            with unprotected_depth_lock:
                unprotected_depth["current"] += 1
                unprotected_depth["max"] = max(unprotected_depth["max"], unprotected_depth["current"])

            # Sync both threads to ensure they're in the method at the same time.
            unprotected_barrier.wait()
            time.sleep(0.01)

            # Track exit: decrement depth
            with unprotected_depth_lock:
                unprotected_depth["current"] -= 1

            cls.DOWNLOAD_PATH.write_bytes(b"fake model")

    def caller_unprotected():
        RacyUnprotected._download_model_if_not_exists()

    t1 = threading.Thread(target=caller_unprotected, daemon=True)
    t2 = threading.Thread(target=caller_unprotected, daemon=True)
    t1.start()
    t2.start()
    t1.join(timeout=5)
    t2.join(timeout=5)

    # Unprotected should allow concurrent execution (both threads in method at once).
    assert unprotected_depth["max"] == 2, (
        f"Unprotected: expected max concurrent depth of 2, got {unprotected_depth['max']}. "
        f"Test failed to demonstrate concurrent execution."
    )

    # Part B: Protected - same scenario, but lock serializes
    protected_depth = {"current": 0, "max": 0}
    protected_depth_lock = threading.Lock()
    protected_barrier = threading.Barrier(2)

    class RacyProtected:
        DOWNLOAD_PATH = temp_cache_dir / "protected.tar.gz"

        @classmethod
        def _download_model_if_not_exists(cls):
            if cls.DOWNLOAD_PATH.exists():
                return

            # Track entry
            with protected_depth_lock:
                protected_depth["current"] += 1
                protected_depth["max"] = max(protected_depth["max"], protected_depth["current"])

            # Sync (but lock will prevent both being here at once)
            protected_barrier.wait()
            time.sleep(0.01)

            # Track exit
            with protected_depth_lock:
                protected_depth["current"] -= 1

            cls.DOWNLOAD_PATH.write_bytes(b"fake model")

    # Protect before use.
    chroma_onnx_lock.protect(RacyProtected)

    def caller_protected():
        RacyProtected._download_model_if_not_exists()

    t1 = threading.Thread(target=caller_protected, daemon=True)
    t2 = threading.Thread(target=caller_protected, daemon=True)
    t1.start()
    t2.start()
    t1.join(timeout=5)
    t2.join(timeout=5)

    # Protected should serialize execution (only one thread in method at a time).
    assert protected_depth["max"] == 1, (
        f"Protected: expected max concurrent depth of 1 (serialized), got {protected_depth['max']}. "
        f"The lock should have prevented concurrent execution."
    )


def test_2_protected_serializes_concurrent_callers(temp_cache_dir):
    """Test 2: Wrapped with protect(), concurrent callers serialize (peak concurrency = 1)."""
    download_path = temp_cache_dir / "onnx.tar.gz"
    download_path.write_bytes(b"fake model")
    call_stack = []

    class TrackedStub:
        DOWNLOAD_PATH = download_path

        @classmethod
        def _download_model_if_not_exists(cls):
            call_stack.append("start")
            time.sleep(0.02)
            call_stack.append("end")

    chroma_onnx_lock.protect(TrackedStub)

    # Now call it from two threads at once.
    t1 = threading.Thread(target=TrackedStub._download_model_if_not_exists, daemon=True)
    t2 = threading.Thread(target=TrackedStub._download_model_if_not_exists, daemon=True)

    t1.start()
    time.sleep(0.005)  # Let t1 acquire the lock.
    t2.start()

    t1.join(timeout=5)
    t2.join(timeout=5)

    # Both called, but serialized: "start" appears twice, separated by "end"s, never concurrent.
    assert call_stack.count("start") == 2
    assert call_stack.count("end") == 2
    # Verify serialization: no interleaving of starts.
    assert call_stack == ["start", "end", "start", "end"]


def test_3_protected_still_calls_through(temp_cache_dir):
    """Test 3: Wrapped original's side effects still happen."""
    download_path = temp_cache_dir / "onnx.tar.gz"
    download_path.write_bytes(b"fake model")

    class CountingStub:
        DOWNLOAD_PATH = download_path
        call_count = 0

        @classmethod
        def _download_model_if_not_exists(cls):
            cls.call_count += 1

    chroma_onnx_lock.protect(CountingStub)

    initial_count = CountingStub.call_count
    CountingStub._download_model_if_not_exists()
    assert CountingStub.call_count == initial_count + 1, "Original method not called"


def test_4_protected_propagates_exception(temp_cache_dir):
    """Test 4: Wrapped original raises an exception; wrapper propagates it."""
    download_path = temp_cache_dir / "onnx.tar.gz"
    # Don't create the file; real method will raise FileNotFoundError.

    class ExceptionStub:
        DOWNLOAD_PATH = download_path

        @classmethod
        def _download_model_if_not_exists(cls):
            with open(cls.DOWNLOAD_PATH, "rb") as f:
                pass

    chroma_onnx_lock.protect(ExceptionStub)

    with pytest.raises(FileNotFoundError):
        ExceptionStub._download_model_if_not_exists()


def test_5_lock_released_after_exception(temp_cache_dir):
    """Test 5: After a failing call, lock is released; next call doesn't hang."""
    download_path = temp_cache_dir / "onnx.tar.gz"
    call_count = [0]

    class FailingThenSuccessStub:
        DOWNLOAD_PATH = download_path

        @classmethod
        def _download_model_if_not_exists(cls):
            call_count[0] += 1
            if call_count[0] == 1:
                raise RuntimeError("simulated network failure")
            # Second call succeeds.
            cls.DOWNLOAD_PATH.write_bytes(b"model")

    chroma_onnx_lock.protect(FailingThenSuccessStub)

    # First call fails.
    with pytest.raises(RuntimeError):
        FailingThenSuccessStub._download_model_if_not_exists()

    # Second call should not hang; lock was released in finally.
    FailingThenSuccessStub._download_model_if_not_exists()
    assert call_count[0] == 2


def test_6_idempotent_double_protect(temp_cache_dir):
    """Test 6: Calling protect() twice on same class is idempotent (no nesting/deadlock)."""
    download_path = temp_cache_dir / "onnx.tar.gz"
    download_path.write_bytes(b"fake model")
    call_count = [0]

    class IdempotentStub:
        DOWNLOAD_PATH = download_path

        @classmethod
        def _download_model_if_not_exists(cls):
            call_count[0] += 1

    # Protect once.
    chroma_onnx_lock.protect(IdempotentStub)
    first_id = id(IdempotentStub._download_model_if_not_exists)

    # Protect again: should recognize it's already protected and no-op (same method).
    chroma_onnx_lock.protect(IdempotentStub)
    second_id = id(IdempotentStub._download_model_if_not_exists)

    # Same object ID: truly idempotent.
    assert first_id == second_id, "protect() was not idempotent: wrapped twice"

    # Call works (no deadlock, no double-wrapping).
    call_count[0] = 0
    IdempotentStub._download_model_if_not_exists()
    assert call_count[0] == 1, "Method not called exactly once"


def test_7_missing_private_method_no_crash(temp_cache_dir):
    """Test 7: If _download_model_if_not_exists is missing (chromadb upgrade), protect() survives."""
    # Create a class without the method (future chromadb rename scenario).
    class BareClass:
        DOWNLOAD_PATH = temp_cache_dir / "onnx.tar.gz"

    # Must not raise; conftest import must survive even if method is missing.
    chroma_onnx_lock.protect(BareClass)


def test_8_creates_lock_parent_directory(temp_cache_dir):
    """Test 8: Lock's parent dir doesn't exist initially; protect() creates it."""
    deep_dir = temp_cache_dir / "very" / "deep" / "path"
    download_path = deep_dir / "onnx.tar.gz"

    class DeepStub:
        DOWNLOAD_PATH = download_path

        @classmethod
        def _download_model_if_not_exists(cls):
            pass

    chroma_onnx_lock.protect(DeepStub)

    # Protect should have created parents for the lock file.
    # Lock path is f"{DOWNLOAD_PATH.parent}/.{DOWNLOAD_PATH.name}.lock"
    lock_path = deep_dir / f".{download_path.name}.lock"
    assert lock_path.parent.exists(), f"Lock parent {lock_path.parent} not created"


def test_9_permission_error_on_lock_creation_fails_closed(temp_cache_dir):
    """Test 9: If lock file can't be created, protect() raises and fails closed."""
    # Create a situation where we can't create the lock file: parent is a file instead of dir.
    blocking_file = temp_cache_dir.parent / "blocking_file"
    blocking_file.touch()

    class BlockingStub:
        DOWNLOAD_PATH = blocking_file / "onnx.tar.gz"  # Parent is a file, not a dir.

        @classmethod
        def _download_model_if_not_exists(cls):
            pass

    try:
        with pytest.raises((PermissionError, OSError, IsADirectoryError)):
            chroma_onnx_lock.protect(BlockingStub)
    finally:
        blocking_file.unlink()


def test_10_integration_real_class_already_protected(tmp_path, monkeypatch):
    """Test 10: Import real ONNXMiniLM_L6_V2; assert conftest wiring already applied marker."""
    # This test verifies that conftest.py's protect() call actually runs and marks the class.
    try:
        from chromadb.utils.embedding_functions.onnx_mini_lm_l6_v2 import ONNXMiniLM_L6_V2
    except ImportError:
        pytest.skip("chromadb not available")

    # After conftest runs protect(ONNXMiniLM_L6_V2), the marker attribute should be set.
    marker = getattr(ONNXMiniLM_L6_V2._download_model_if_not_exists, "__protected_by_chroma_onnx_lock__", None)
    assert marker is True, (
        f"ONNXMiniLM_L6_V2._download_model_if_not_exists not marked as protected. "
        f"conftest.py wiring didn't run or didn't take effect. "
        f"Attribute: {marker}"
    )
