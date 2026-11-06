"""Serialize concurrent ONNX model downloads via fcntl.flock to prevent file corruption.

Latent cross-process race exposed by parallel CI (#826): when multiple test processes
simultaneously import chromadb's ONNXMiniLM_L6_V2, each calls _download_model_if_not_exists
independently, corrupting the shared model file in ~/.cache. This module wraps that
method with a lock keyed on the model's download path, serializing downloads across
processes on the same machine.

Usage:
    from chromadb.utils.embedding_functions.onnx_mini_lm_l6_v2 import ONNXMiniLM_L6_V2
    import chroma_onnx_lock
    chroma_onnx_lock.protect(ONNXMiniLM_L6_V2)

The protect() function is idempotent and a no-op if the target method doesn't exist.
"""
from __future__ import annotations

import fcntl
import functools
from pathlib import Path

PROTECT_MARKER = "__chroma_onnx_locked__"


def protect(cls) -> None:
    """Wrap cls._download_model_if_not_exists with fcntl.flock, serializing downloads.

    Args:
        cls: A class (like chromadb's ONNXMiniLM_L6_V2) with DOWNLOAD_PATH and
             _download_model_if_not_exists attributes.

    Idempotent: calling protect() multiple times on the same class is safe.
    No-op: if the class lacks _download_model_if_not_exists, does nothing.
    """
    # No-op if the method doesn't exist
    if not hasattr(cls, "_download_model_if_not_exists"):
        return

    # Idempotent: if already wrapped, return
    method = cls._download_model_if_not_exists
    if hasattr(method, PROTECT_MARKER):
        return

    # Create the parent directory for the lock file (and the model itself)
    download_path = cls.DOWNLOAD_PATH
    if isinstance(download_path, str):
        download_path = Path(download_path)
    download_path.parent.mkdir(parents=True, exist_ok=True)

    # Lock file is named from the download path's name
    lock_path = download_path.parent / f"{download_path.name}.lock"

    @functools.wraps(method)
    def locked_download(*args, **kwargs):
        """Call the original method while holding an fcntl lock on the model file."""
        with open(lock_path, "w") as lock_file:
            try:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
                return method(*args, **kwargs)
            finally:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

    # Mark as protected so protect() is idempotent
    setattr(locked_download, PROTECT_MARKER, True)

    # Replace the original method
    cls._download_model_if_not_exists = locked_download
