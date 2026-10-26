"""Tests for benchmark_loader.py. Run via:
    ~/.agents/venv/bin/python -m pytest bench/lib/tests/test_benchmark_loader.py -v
"""
from __future__ import annotations
import json
import sys
import tempfile
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from benchmark_loader import (
    load_papers_from_chroma,
    load_benchmark_labels,
    save_benchmark_labels,
)


# ── load_papers_from_chroma ──────────────────────────────────────────────────

def test_load_papers_requires_chromadb():
    """If chromadb import fails, raises ImportError with helpful message."""
    def mock_import_func(name, *args, **kwargs):
        # Raise ImportError only for chromadb, let other imports proceed normally
        if name == "chromadb":
            raise ImportError("chromadb not installed")
        return __import__(name, *args, **kwargs)

    with mock.patch("builtins.__import__", side_effect=mock_import_func):
        with pytest.raises(ImportError, match="chromadb not installed"):
            load_papers_from_chroma()


def test_load_papers_from_chroma_missing_chroma_path():
    """If CHROMA_PATH doesn't exist, raises FileNotFoundError."""
    with mock.patch("benchmark_loader.CHROMA_PATH", Path("/nonexistent/path/xyz")):
        with pytest.raises(FileNotFoundError):
            load_papers_from_chroma()


def test_load_papers_from_chroma_missing_collection():
    """If the collection doesn't exist, raises ValueError."""
    mock_client = mock.MagicMock()
    mock_client.get_collection.side_effect = ValueError("not found")

    with mock.patch("benchmark_loader.CHROMA_PATH", Path("/tmp")):
        with mock.patch("chromadb.PersistentClient", return_value=mock_client):
            with pytest.raises(ValueError, match="Collection.*not found"):
                load_papers_from_chroma("missing-collection")


def test_load_papers_from_chroma_empty_collection():
    """If the collection returns no items, raises ValueError."""
    mock_collection = mock.MagicMock()
    mock_collection.get.return_value = {"ids": [], "documents": [], "metadatas": []}

    mock_client = mock.MagicMock()
    mock_client.get_collection.return_value = mock_collection

    with mock.patch("benchmark_loader.CHROMA_PATH", Path("/tmp")):
        with mock.patch("chromadb.PersistentClient", return_value=mock_client):
            with pytest.raises(ValueError, match="No papers with abstracts found"):
                load_papers_from_chroma()


def test_load_papers_from_chroma_filters_empty_abstracts():
    """Papers with empty/missing abstracts are skipped."""
    mock_collection = mock.MagicMock()
    mock_collection.get.return_value = {
        "ids": ["paper1", "paper2", "paper3"],
        "documents": ["Abstract 1", "", None],
        "metadatas": [
            {"title": "Title 1"},
            {"title": "Title 2"},
            {"title": "Title 3"},
        ],
    }

    mock_client = mock.MagicMock()
    mock_client.get_collection.return_value = mock_collection

    with mock.patch("benchmark_loader.CHROMA_PATH", Path("/tmp")):
        with mock.patch("chromadb.PersistentClient", return_value=mock_client):
            result = load_papers_from_chroma()
            assert len(result) == 1
            assert "paper1" in result
            assert result["paper1"] == ("Title 1", "Abstract 1")


def test_load_papers_from_chroma_uses_title_from_metadata():
    """Title comes from metadata['title'] if present."""
    mock_collection = mock.MagicMock()
    mock_collection.get.return_value = {
        "ids": ["paper1"],
        "documents": ["Abstract 1"],
        "metadatas": [{"title": "Custom Title"}],
    }

    mock_client = mock.MagicMock()
    mock_client.get_collection.return_value = mock_collection

    with mock.patch("benchmark_loader.CHROMA_PATH", Path("/tmp")):
        with mock.patch("chromadb.PersistentClient", return_value=mock_client):
            result = load_papers_from_chroma()
            assert result["paper1"][0] == "Custom Title"


def test_load_papers_from_chroma_fallback_title_from_slug():
    """Title falls back to humanized slug if metadata has no title."""
    mock_collection = mock.MagicMock()
    mock_collection.get.return_value = {
        "ids": ["my-paper-slug"],
        "documents": ["Abstract text"],
        "metadatas": [{}],
    }

    mock_client = mock.MagicMock()
    mock_client.get_collection.return_value = mock_collection

    with mock.patch("benchmark_loader.CHROMA_PATH", Path("/tmp")):
        with mock.patch("chromadb.PersistentClient", return_value=mock_client):
            result = load_papers_from_chroma()
            assert result["my-paper-slug"][0] == "My Paper Slug"


def test_load_papers_from_chroma_returns_dict():
    """Returns a dict mapping slug to (title, abstract) tuples."""
    mock_collection = mock.MagicMock()
    mock_collection.get.return_value = {
        "ids": ["paper1", "paper2"],
        "documents": ["Abstract 1", "Abstract 2"],
        "metadatas": [{"title": "Title 1"}, {"title": "Title 2"}],
    }

    mock_client = mock.MagicMock()
    mock_client.get_collection.return_value = mock_collection

    with mock.patch("benchmark_loader.CHROMA_PATH", Path("/tmp")):
        with mock.patch("chromadb.PersistentClient", return_value=mock_client):
            result = load_papers_from_chroma()
            assert isinstance(result, dict)
            assert result == {
                "paper1": ("Title 1", "Abstract 1"),
                "paper2": ("Title 2", "Abstract 2"),
            }


# ── load_benchmark_labels ────────────────────────────────────────────────────

def test_load_benchmark_labels_file_not_found():
    """Raises FileNotFoundError if the benchmark file doesn't exist."""
    with pytest.raises(FileNotFoundError):
        load_benchmark_labels(Path("/nonexistent/benchmark.json"))


def test_load_benchmark_labels_valid_json():
    """Loads and returns the JSON contents as a dict."""
    with tempfile.TemporaryDirectory() as tmpdir:
        bench_file = Path(tmpdir) / "benchmark.json"
        labels = {
            "paper1": {"layer1_findings": ["finding1"], "layer2_result": {"validity": "valid"}},
            "paper2": {"layer1_findings": [], "layer2_result": {"validity": "weak"}},
        }
        bench_file.write_text(json.dumps(labels))

        result = load_benchmark_labels(bench_file)
        assert result == labels


# ── save_benchmark_labels ────────────────────────────────────────────────────

def test_save_benchmark_labels_creates_parent_dirs():
    """Creates parent directories if they don't exist."""
    with tempfile.TemporaryDirectory() as tmpdir:
        bench_file = Path(tmpdir) / "subdir" / "benchmark.json"
        labels = {"paper1": {"findings": []}}

        save_benchmark_labels(labels, bench_file)

        assert bench_file.exists()
        assert json.loads(bench_file.read_text()) == labels


def test_save_benchmark_labels_atomic_write():
    """Uses atomic rename (temp file → final) to avoid corruption."""
    with tempfile.TemporaryDirectory() as tmpdir:
        bench_file = Path(tmpdir) / "benchmark.json"
        labels = {"paper1": {"findings": ["f1"]}}

        save_benchmark_labels(labels, bench_file)

        assert bench_file.exists()
        assert not bench_file.with_suffix(".tmp").exists()
        assert json.loads(bench_file.read_text()) == labels


def test_save_benchmark_labels_overwrites_existing():
    """Overwrites an existing file."""
    with tempfile.TemporaryDirectory() as tmpdir:
        bench_file = Path(tmpdir) / "benchmark.json"
        old_labels = {"old": "data"}
        bench_file.write_text(json.dumps(old_labels))

        new_labels = {"new": "data"}
        save_benchmark_labels(new_labels, bench_file)

        assert json.loads(bench_file.read_text()) == new_labels
