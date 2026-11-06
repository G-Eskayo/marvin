"""Serialize chromadb's lazy ONNX model download with fcntl.flock to prevent race on cold CI runners.

marvin#1156: ONNXMiniLM_L6_V2._download_model_if_not_exists does an unlocked check-then-act on a
shared path (~/.cache/chroma/...). Under pytest-xdist (-n auto), workers are separate OS processes
sharing one real ~/.cache, so concurrent first calls race on the single tar.gz file: one worker's
_verify_sha256 loses a TOCTOU race to another's os.remove(), producing FileNotFoundError.

This module provides protect(cls), which wraps _download_model_if_not_exists with an fcntl.flock
keyed on the model's cache path. The lock is acquired before the original method, released in a
finally, and idempotent (calling protect() twice is a no-op).
"""
import fcntl
import inspect
from functools import wraps
from pathlib import Path


def protect(cls: type) -> None:
    """Wrap cls._download_model_if_not_exists with fcntl.flock.

    Args:
        cls: A class with DOWNLOAD_PATH (Path) and _download_model_if_not_exists (callable).
             If the method is already wrapped, this is a no-op (idempotent).
             If _download_model_if_not_exists is missing, this silently returns (robustness).

    Raises:
        PermissionError: If the lock file's parent directory can't be created or written.
    """
    # Robustness: if the method is missing (chromadb upgraded and renamed it), silently skip.
    if not hasattr(cls, "_download_model_if_not_exists"):
        return

    # Detect if the original is a classmethod by checking the raw descriptor.
    descriptor = inspect.getattr_static(cls, "_download_model_if_not_exists")
    is_classmethod = isinstance(descriptor, classmethod)

    # Idempotence: if already wrapped, skip.
    # For classmethods, check the underlying function; for others, check the method/function directly.
    if is_classmethod:
        check_obj = descriptor.__func__
    else:
        check_obj = descriptor

    if getattr(check_obj, "__protected_by_chroma_onnx_lock__", False):
        return

    # Ensure the lock's parent directory exists. Lock path is in the same directory as DOWNLOAD_PATH.
    # E.g., if DOWNLOAD_PATH is ~/.cache/chroma/onnx.tar.gz, lock is ~/.cache/chroma/.onnx.tar.gz.lock
    download_path: Path = cls.DOWNLOAD_PATH
    lock_dir = download_path.parent
    lock_dir.mkdir(parents=True, exist_ok=True)

    lock_path = lock_dir / f".{download_path.name}.lock"

    if is_classmethod:
        # Extract the underlying function from the classmethod descriptor.
        original_func = descriptor.__func__

        def protected_download(cls_arg):
            """Acquire lock, call original, release in finally."""
            with open(lock_path, "a") as lock_file:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
                try:
                    return original_func(cls_arg)
                finally:
                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

        protected_download.__protected_by_chroma_onnx_lock__ = True
        protected_download.__wrapped__ = original_func
        cls._download_model_if_not_exists = classmethod(protected_download)
    else:
        # For instance methods or regular methods.
        original = cls._download_model_if_not_exists

        @wraps(original)
        def protected_download(self):
            """Acquire lock, call original, release in finally."""
            with open(lock_path, "a") as lock_file:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
                try:
                    return original(self)
                finally:
                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

        protected_download.__protected_by_chroma_onnx_lock__ = True
        cls._download_model_if_not_exists = protected_download
