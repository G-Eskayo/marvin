"""Lock wrapper for chromadb's ONNX model download (marvin#1156).

chromadb downloads the ONNX embedding model to ~/.cache/chroma. When pytest-xdist runs
multiple workers in parallel, concurrent downloads race and corrupt the cache. This module
provides a file-lock guard to serialize downloads across workers.
"""
import fcntl
from pathlib import Path


def protect(cls):
    """Wrap cls._download_model_if_not_exists with an fcntl.flock guard.

    No-ops if cls lacks _download_model_if_not_exists or DOWNLOAD_PATH.
    Idempotent: calling protect() twice on the same class is safe.
    """
    # Check preconditions first
    if not hasattr(cls, "_download_model_if_not_exists"):
        return
    if not hasattr(cls, "DOWNLOAD_PATH"):
        return

    # Check if already protected (must inspect the descriptor directly)
    descriptor = cls.__dict__.get("_download_model_if_not_exists")
    if descriptor is not None and isinstance(descriptor, classmethod):
        if hasattr(descriptor.__func__, "_chroma_onnx_protected"):
            return

    original_method = cls._download_model_if_not_exists

    def locked_download(kls):
        """Acquire lock, call original, release lock in finally."""
        # Handle DOWNLOAD_PATH being either a Path or string
        download_path = kls.DOWNLOAD_PATH
        if not isinstance(download_path, Path):
            download_path = Path(download_path)

        lock_dir = download_path.parent
        lock_dir.mkdir(parents=True, exist_ok=True)
        lock_path = lock_dir / f".{download_path.name}.lock"

        with open(lock_path, "w") as lock_file:
            try:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
                original_method()
            finally:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

    # Mark for idempotency
    locked_download._chroma_onnx_protected = True
    cls._download_model_if_not_exists = classmethod(locked_download)
