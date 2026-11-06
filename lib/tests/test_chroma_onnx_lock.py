"""Tests for chroma_onnx_lock.py: serializing concurrent ONNX model downloads via fcntl.flock.

The latent race was exposed by parallel CI (#826): when multiple test processes simultaneously
import chromadb's ONNXMiniLM_L6_V2, each calls _download_model_if_not_exists independently,
corrupting the shared model file in ~/.cache. This module wraps that method with a lock keyed
on the model's download path, serializing downloads across processes on the same machine.
"""
from __future__ import annotations

import fcntl
import os
import sys
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import chroma_onnx_lock  # noqa: E402


class TestProtectFunctionality:
    """Test chroma_onnx_lock.protect(cls) wraps _download_model_if_not_exists with fcntl.flock."""

    def test_protect_wraps_download_method_with_lock(self, tmp_path):
        """Test 1: protect() successfully replaces _download_model_if_not_exists with a locked version."""
        fake_cls = Mock()
        fake_cls.DOWNLOAD_PATH = tmp_path / "model.onnx"
        fake_cls._download_model_if_not_exists = Mock(return_value=None)
        original_method = fake_cls._download_model_if_not_exists

        chroma_onnx_lock.protect(fake_cls)

        # Method should be wrapped (not the same object anymore)
        assert fake_cls._download_model_if_not_exists is not original_method
        assert callable(fake_cls._download_model_if_not_exists)

    def test_protect_idempotent(self, tmp_path):
        """Test 2: protect() is idempotent—calling it twice doesn't double-wrap."""
        fake_cls = Mock()
        fake_cls.DOWNLOAD_PATH = tmp_path / "model.onnx"
        fake_cls._download_model_if_not_exists = Mock(return_value=None)

        chroma_onnx_lock.protect(fake_cls)
        first_wrapped = fake_cls._download_model_if_not_exists

        chroma_onnx_lock.protect(fake_cls)
        second_wrapped = fake_cls._download_model_if_not_exists

        # Should be the exact same wrapped method, not wrapped again
        assert first_wrapped is second_wrapped

    def test_protect_creates_parent_directory(self, tmp_path):
        """Test 3: protect() creates the lock file's parent directory if it doesn't exist."""
        fake_cls = Mock()
        nested_path = tmp_path / "a" / "b" / "c" / "model.onnx"
        fake_cls.DOWNLOAD_PATH = nested_path
        fake_cls._download_model_if_not_exists = Mock(return_value=None)

        assert not nested_path.parent.exists()
        chroma_onnx_lock.protect(fake_cls)
        # Should create the parent on first wrap
        assert nested_path.parent.exists()

    def test_protect_names_lock_from_download_path(self, tmp_path):
        """Test 4: protect() names the lock file from cls.DOWNLOAD_PATH.name."""
        fake_cls = Mock()
        fake_cls.DOWNLOAD_PATH = tmp_path / "my-model-v2.onnx"
        fake_cls._download_model_if_not_exists = Mock(return_value=None)

        chroma_onnx_lock.protect(fake_cls)

        # Call the wrapped method and check that a lock file with the expected name is created
        fake_cls._download_model_if_not_exists()

        # Lock file should be <parent>/<download_path_name>.lock
        lock_path = (tmp_path / "my-model-v2.onnx.lock")
        assert lock_path.exists() or lock_path.with_suffix(".lock").exists()

    def test_protect_no_op_when_method_missing(self, tmp_path):
        """Test 5: protect() is a no-op when _download_model_if_not_exists doesn't exist."""
        fake_cls = Mock(spec=[])  # No methods
        fake_cls.DOWNLOAD_PATH = tmp_path / "model.onnx"

        # Should not raise
        chroma_onnx_lock.protect(fake_cls)

        # Should not have added the method
        assert not hasattr(fake_cls, "_download_model_if_not_exists")

    def test_wrapped_method_calls_original(self, tmp_path):
        """Test 6: calling the wrapped method actually calls the original _download_model_if_not_exists."""
        fake_cls = Mock()
        fake_cls.DOWNLOAD_PATH = tmp_path / "model.onnx"
        original_mock = Mock(return_value="result")
        fake_cls._download_model_if_not_exists = original_mock

        chroma_onnx_lock.protect(fake_cls)
        result = fake_cls._download_model_if_not_exists()

        # Original should have been called
        original_mock.assert_called_once()
        # And its result should be returned
        assert result == "result"

    def test_wrapped_method_propagates_exceptions(self, tmp_path):
        """Test 7: exceptions from the original method are propagated through the lock."""
        fake_cls = Mock()
        fake_cls.DOWNLOAD_PATH = tmp_path / "model.onnx"
        fake_cls._download_model_if_not_exists = Mock(side_effect=ValueError("download failed"))

        chroma_onnx_lock.protect(fake_cls)

        with pytest.raises(ValueError, match="download failed"):
            fake_cls._download_model_if_not_exists()

    def test_wrapped_method_releases_lock_on_exception(self, tmp_path):
        """Test 8: lock is released even when the original method raises an exception."""
        fake_cls = Mock()
        fake_cls.DOWNLOAD_PATH = tmp_path / "model.onnx"
        fake_cls._download_model_if_not_exists = Mock(side_effect=RuntimeError("boom"))

        chroma_onnx_lock.protect(fake_cls)

        # First call raises
        with pytest.raises(RuntimeError):
            fake_cls._download_model_if_not_exists()

        # Second call should be able to acquire the lock (not deadlocked)
        fake_cls._download_model_if_not_exists = Mock(return_value="ok")
        chroma_onnx_lock.protect(fake_cls)
        result = fake_cls._download_model_if_not_exists()
        assert result == "ok"

    def test_wrapped_method_with_args_and_kwargs(self, tmp_path):
        """Test 9: wrapped method preserves and forwards arguments and keyword arguments."""
        fake_cls = Mock()
        fake_cls.DOWNLOAD_PATH = tmp_path / "model.onnx"
        original_mock = Mock(return_value="success")
        fake_cls._download_model_if_not_exists = original_mock

        chroma_onnx_lock.protect(fake_cls)

        # Call with args and kwargs
        result = fake_cls._download_model_if_not_exists("arg1", "arg2", kw1="val1", kw2="val2")

        # Original should be called with the exact same args/kwargs
        original_mock.assert_called_once_with("arg1", "arg2", kw1="val1", kw2="val2")
        assert result == "success"

    def test_protect_marker_attribute_prevents_double_wrap(self, tmp_path):
        """Test 10: protect() uses a marker attribute to prevent double-wrapping."""
        fake_cls = Mock()
        fake_cls.DOWNLOAD_PATH = tmp_path / "model.onnx"
        fake_cls._download_model_if_not_exists = Mock(return_value=None)

        chroma_onnx_lock.protect(fake_cls)
        # Should have set a marker attribute
        assert hasattr(fake_cls._download_model_if_not_exists, chroma_onnx_lock.PROTECT_MARKER)

        first_wrapped = fake_cls._download_model_if_not_exists
        chroma_onnx_lock.protect(fake_cls)
        second_wrapped = fake_cls._download_model_if_not_exists

        # Same wrapped method
        assert first_wrapped is second_wrapped
