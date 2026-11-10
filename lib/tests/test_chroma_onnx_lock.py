"""Lock wrapper for chromadb's ONNX model download (marvin#1156).

Tests that chroma_onnx_lock.protect(cls) guards concurrent downloads of the ONNX model
across pytest-xdist workers, preventing race conditions in ~/.cache/chroma.
"""
import fcntl
import threading
import time
from pathlib import Path
from unittest import mock

import pytest

import chroma_onnx_lock


class MockONNXClass:
    """Mock chromadb ONNX embedding class for testing."""
    DOWNLOAD_PATH = Path("/tmp/test_model.onnx")
    call_count = 0
    slow_calls = []

    @classmethod
    def _download_model_if_not_exists(cls):
        """Simulate model download."""
        cls.call_count += 1
        # Record slow calls to detect concurrency
        cls.slow_calls.append(time.time())
        time.sleep(0.1)


class MockONNXNoPath:
    """ONNX class without DOWNLOAD_PATH."""
    @classmethod
    def _download_model_if_not_exists(cls):
        pass


class MockONNXNoMethod:
    """ONNX class without _download_model_if_not_exists."""
    DOWNLOAD_PATH = Path("/tmp/test_model.onnx")


def test_protect_wraps_download_method():
    """Test 1: protect() wraps _download_model_if_not_exists."""
    cls = MockONNXClass
    cls.call_count = 0
    chroma_onnx_lock.protect(cls)
    assert hasattr(cls._download_model_if_not_exists, "_chroma_onnx_protected")


def test_protect_is_idempotent():
    """Test 2: calling protect() twice on the same class is safe."""
    cls = MockONNXClass
    cls.call_count = 0
    chroma_onnx_lock.protect(cls)
    first_wrapped = cls.__dict__['_download_model_if_not_exists']
    chroma_onnx_lock.protect(cls)
    second_wrapped = cls.__dict__['_download_model_if_not_exists']
    # Should still be marked as protected, not double-wrapped
    assert hasattr(first_wrapped.__func__, "_chroma_onnx_protected")
    # Should be the same object (not re-wrapped)
    assert first_wrapped is second_wrapped


def test_protect_noop_without_download_path():
    """Test 3: protect() no-ops if class lacks DOWNLOAD_PATH."""
    cls = MockONNXNoPath
    original = cls.__dict__['_download_model_if_not_exists']
    chroma_onnx_lock.protect(cls)
    assert cls.__dict__['_download_model_if_not_exists'] is original


def test_protect_noop_without_download_method():
    """Test 4: protect() no-ops if class lacks _download_model_if_not_exists."""
    cls = MockONNXNoMethod
    original_attrs = set(dir(cls))
    chroma_onnx_lock.protect(cls)
    assert set(dir(cls)) == original_attrs


def test_protected_method_acquires_lock(tmp_path):
    """Test 5: wrapped method acquires a file lock during execution."""
    cls = MockONNXClass
    cls.DOWNLOAD_PATH = tmp_path / "model.onnx"
    cls.call_count = 0
    chroma_onnx_lock.protect(cls)

    lock_path = tmp_path / ".model.onnx.lock"
    acquired_locks = []
    started_event = threading.Event()

    def try_acquire_during_call():
        # Wait for the main thread to signal that it's in the protected call
        started_event.wait(timeout=2)
        # Now try to acquire the lock (non-blocking)
        try:
            with open(lock_path, "w") as f:
                fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired_locks.append(False)  # We got it (shouldn't happen)
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
        except IOError:
            acquired_locks.append(True)  # Lock held by first call (expected)

    thread = threading.Thread(target=try_acquire_during_call)
    thread.start()

    # Signal the thread from inside the protected call by using a wrapper
    original_download = cls._download_model_if_not_exists
    calls_started = []

    def signaling_download(kls):
        calls_started.append(True)
        started_event.set()
        original_download()

    cls._download_model_if_not_exists = classmethod(signaling_download)
    cls._download_model_if_not_exists()
    thread.join()

    assert acquired_locks, "Lock check thread did not run"
    assert acquired_locks[0], "Lock was not held during protected call"


def test_protected_method_releases_lock(tmp_path):
    """Test 6: wrapped method releases lock after execution."""
    cls = MockONNXClass
    cls.DOWNLOAD_PATH = tmp_path / "model.onnx"
    cls.call_count = 0
    chroma_onnx_lock.protect(cls)

    cls._download_model_if_not_exists()

    lock_path = tmp_path / ".model.onnx.lock"
    # Try to acquire the lock after the call
    with open(lock_path, "w") as f:
        try:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)
            lock_acquired = True
        except IOError:
            lock_acquired = False

    assert lock_acquired, "Lock was not released after protected call"


def test_protected_method_propagates_exceptions(tmp_path):
    """Test 7: wrapped method propagates exceptions from the original."""
    cls = MockONNXClass
    cls.DOWNLOAD_PATH = tmp_path / "model.onnx"

    def raise_error(kls):
        raise ValueError("Download failed")

    cls._download_model_if_not_exists = classmethod(raise_error)
    chroma_onnx_lock.protect(cls)

    with pytest.raises(ValueError, match="Download failed"):
        cls._download_model_if_not_exists()


def test_protected_method_releases_lock_on_exception(tmp_path):
    """Test 8: wrapped method releases lock even if original raises."""
    cls = MockONNXClass
    cls.DOWNLOAD_PATH = tmp_path / "model.onnx"

    def raise_error(kls):
        raise ValueError("Download failed")

    cls._download_model_if_not_exists = classmethod(raise_error)
    chroma_onnx_lock.protect(cls)

    with pytest.raises(ValueError):
        cls._download_model_if_not_exists()

    lock_path = tmp_path / ".model.onnx.lock"
    # Try to acquire the lock after the exception
    with open(lock_path, "w") as f:
        try:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)
            lock_acquired = True
        except IOError:
            lock_acquired = False

    assert lock_acquired, "Lock was not released after exception"


def test_concurrent_calls_serialize_with_lock(tmp_path):
    """Test 9: concurrent calls to protected method are serialized by the lock."""
    # Use a fresh class to avoid state pollution from previous tests
    class MockONNXForConcurrency:
        DOWNLOAD_PATH = tmp_path / "model.onnx"
        call_count = 0

        @classmethod
        def _download_model_if_not_exists(cls):
            cls.call_count += 1
            time.sleep(0.1)

    cls = MockONNXForConcurrency
    chroma_onnx_lock.protect(cls)

    results = []

    def call_download():
        cls._download_model_if_not_exists()
        results.append("done")

    # Start two threads that try to call the protected method
    threads = [threading.Thread(target=call_download) for _ in range(2)]
    start = time.time()
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    elapsed = time.time() - start

    # Both should have completed
    assert len(results) == 2
    # Should have taken roughly 0.2 seconds (two serialized calls of 0.1s each)
    # not 0.1 seconds (parallel calls)
    assert elapsed >= 0.15, f"Calls were concurrent (took {elapsed:.2f}s, expected >0.15s)"
