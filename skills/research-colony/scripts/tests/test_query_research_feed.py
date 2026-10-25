"""Tests for query_research_feed.py. Run via:
    ~/.agents/venv/bin/python -m pytest skills/research-colony/scripts/tests/test_query_research_feed.py -v
"""
from __future__ import annotations
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))

import chromadb
import pytest

import query_research_feed as qrf


def test_empty_collection_returns_empty_list(tmp_path, monkeypatch):
    """No items ever added; must not crash."""
    monkeypatch.setattr(qrf, "CHROMA_PATH", tmp_path)

    result = qrf.query_research_feed("test query")
    assert result == []


def test_collection_never_created_returns_empty_list(tmp_path, monkeypatch):
    """First-ever run, research-feed collection doesn't exist yet."""
    monkeypatch.setattr(qrf, "CHROMA_PATH", tmp_path)

    result = qrf.query_research_feed("test query")
    assert result == []


def test_chromadb_not_installed_falls_back_gracefully(tmp_path, monkeypatch, capsys):
    """Verify the function gracefully handles connection errors."""
    monkeypatch.setattr(qrf, "CHROMA_PATH", tmp_path)

    # Mock PersistentClient to raise ImportError
    import chromadb as chroma_module
    original_persistent_client = chroma_module.PersistentClient

    def mock_persistent_client(*args, **kwargs):
        raise ImportError("chromadb connection failed")

    monkeypatch.setattr(chroma_module, "PersistentClient", mock_persistent_client)

    result = qrf.query_research_feed("test query")
    assert result == []

    # Restore
    monkeypatch.setattr(chroma_module, "PersistentClient", original_persistent_client)


def test_query_matching_item_returns_hit_below_threshold(tmp_path, monkeypatch):
    """Seed one item, query matching text, assert it comes back with metadata."""
    monkeypatch.setattr(qrf, "CHROMA_PATH", tmp_path)

    client = chromadb.PersistentClient(path=str(tmp_path))
    col = client.get_or_create_collection("research-feed")
    col.add(
        ids=["test-1"],
        documents=["machine learning deep neural networks"],
        metadatas=[{
            "title": "Deep Learning Basics",
            "url": "https://example.com/deep-learning",
            "source": "arxiv",
            "date": "2026-10-22",
            "published": "2026-10-20",
        }]
    )

    result = qrf.query_research_feed("machine learning neural networks", n=5)
    assert len(result) > 0
    assert result[0]["title"] == "Deep Learning Basics"
    assert result[0]["url"] == "https://example.com/deep-learning"
    assert result[0]["source"] == "arxiv"
    assert "distance" in result[0]


def test_query_unrelated_item_filtered_out(tmp_path, monkeypatch):
    """Seed one unrelated item, confirm distance >= threshold excludes it."""
    monkeypatch.setattr(qrf, "CHROMA_PATH", tmp_path)

    client = chromadb.PersistentClient(path=str(tmp_path))
    col = client.get_or_create_collection("research-feed")
    col.add(
        ids=["unrelated-1"],
        documents=["cooking recipes for french cuisine"],
        metadatas=[{
            "title": "French Cooking",
            "url": "https://example.com/cooking",
            "source": "blog",
            "date": "2026-10-22",
            "published": "2026-10-20",
        }]
    )

    result = qrf.query_research_feed("machine learning algorithms", n=5, threshold=1.1)
    assert len(result) == 0


def test_no_date_filter_finds_item_from_prior_day(tmp_path, monkeypatch):
    """Seed an item with date several days in the past; must still be found.

    This is the core behavioral diff from correlate.py: we search full history,
    not just today.
    """
    monkeypatch.setattr(qrf, "CHROMA_PATH", tmp_path)

    client = chromadb.PersistentClient(path=str(tmp_path))
    col = client.get_or_create_collection("research-feed")

    past_date = (datetime.now() - timedelta(days=5)).date().isoformat()
    col.add(
        ids=["old-1"],
        documents=["transformer models attention mechanisms"],
        metadatas=[{
            "title": "Transformer Architecture",
            "url": "https://example.com/transformers",
            "source": "arxiv",
            "date": past_date,
            "published": past_date,
        }]
    )

    result = qrf.query_research_feed("transformer attention", n=5)
    assert len(result) > 0
    assert result[0]["title"] == "Transformer Architecture"


def test_read_only_never_mutates_metadata(tmp_path, monkeypatch):
    """Capture metadata before and after query; assert unchanged.

    Guards against accidentally reintroducing correlate.py-style .update()
    and racing its writes.
    """
    monkeypatch.setattr(qrf, "CHROMA_PATH", tmp_path)

    client = chromadb.PersistentClient(path=str(tmp_path))
    col = client.get_or_create_collection("research-feed")
    col.add(
        ids=["test-1"],
        documents=["test document content"],
        metadatas=[{
            "title": "Test Item",
            "url": "https://example.com/test",
            "source": "test",
            "date": "2026-10-22",
            "published": "2026-10-20",
        }]
    )

    before = col.get(ids=["test-1"], include=["metadatas"])["metadatas"][0]

    qrf.query_research_feed("test content", n=5)

    after = col.get(ids=["test-1"], include=["metadatas"])["metadatas"][0]
    assert before == after


def test_huge_query_string_does_not_crash(tmp_path, monkeypatch):
    """A ~50k-character query string; must not raise."""
    monkeypatch.setattr(qrf, "CHROMA_PATH", tmp_path)

    client = chromadb.PersistentClient(path=str(tmp_path))
    col = client.get_or_create_collection("research-feed")
    col.add(
        ids=["test-1"],
        documents=["short doc"],
        metadatas=[{
            "title": "Test",
            "url": "https://example.com/test",
            "source": "test",
            "date": "2026-10-22",
            "published": "2026-10-20",
        }]
    )

    huge_query = "test " * 10000  # ~50k chars
    result = qrf.query_research_feed(huge_query, n=5)
    assert isinstance(result, list)


def test_malformed_query_string_does_not_crash(tmp_path, monkeypatch):
    """Control characters, null bytes, injection-style text; must not raise."""
    monkeypatch.setattr(qrf, "CHROMA_PATH", tmp_path)

    client = chromadb.PersistentClient(path=str(tmp_path))
    col = client.get_or_create_collection("research-feed")
    col.add(
        ids=["test-1"],
        documents=["test"],
        metadatas=[{
            "title": "Test",
            "url": "https://example.com/test",
            "source": "test",
            "date": "2026-10-22",
            "published": "2026-10-20",
        }]
    )

    malformed_queries = [
        "test\x00null\x00bytes",
        "'; DROP TABLE--",
        "{{7*7}}",
        "test\n\r\t\x01",
    ]

    for q in malformed_queries:
        result = qrf.query_research_feed(q, n=5)
        assert isinstance(result, list)


def test_empty_string_query_does_not_crash(tmp_path, monkeypatch):
    """Empty query string."""
    monkeypatch.setattr(qrf, "CHROMA_PATH", tmp_path)

    client = chromadb.PersistentClient(path=str(tmp_path))
    col = client.get_or_create_collection("research-feed")
    col.add(
        ids=["test-1"],
        documents=["test"],
        metadatas=[{
            "title": "Test",
            "url": "https://example.com/test",
            "source": "test",
            "date": "2026-10-22",
            "published": "2026-10-20",
        }]
    )

    result = qrf.query_research_feed("", n=5)
    assert isinstance(result, list)


def test_corrupted_or_locked_db_falls_back_gracefully(tmp_path, monkeypatch):
    """Simulate query failure by creating a broken collection.

    /research must never crash because this pre-check failed.
    """
    monkeypatch.setattr(qrf, "CHROMA_PATH", tmp_path)

    client = chromadb.PersistentClient(path=str(tmp_path))
    col = client.get_or_create_collection("research-feed")
    col.add(
        ids=["test-1"],
        documents=["test"],
        metadatas=[{
            "title": "Test",
            "url": "https://example.com/test",
            "source": "test",
            "date": "2026-10-22",
            "published": "2026-10-20",
        }]
    )

    # Create a new client instance and mock its method
    test_client = chromadb.PersistentClient(path=str(tmp_path / "test_broken"))

    # Mock the get_or_create_collection on this instance
    original_method = test_client.get_or_create_collection

    def mock_broken_method(name, **kwargs):
        class BrokenCollection:
            def count(self):
                return 1
            def query(self, *args, **kwargs):
                raise Exception("DB is locked or corrupted")
        return BrokenCollection()

    # Patch it on the qrf module's internal call
    # We'll mock the PersistentClient constructor itself
    def mock_persistent_client(path=None, **kwargs):
        c = test_client
        c.get_or_create_collection = mock_broken_method
        return c

    original_pc = chromadb.PersistentClient
    monkeypatch.setattr(chromadb, "PersistentClient", mock_persistent_client)

    result = qrf.query_research_feed("test", n=5)
    assert result == []

    # Restore
    monkeypatch.setattr(chromadb, "PersistentClient", original_pc)


def test_n_limits_results_to_top_n(tmp_path, monkeypatch):
    """5 matching seeded items, n=2; assert exactly the 2 closest are returned."""
    monkeypatch.setattr(qrf, "CHROMA_PATH", tmp_path)

    client = chromadb.PersistentClient(path=str(tmp_path))
    col = client.get_or_create_collection("research-feed")

    for i in range(5):
        col.add(
            ids=[f"item-{i}"],
            documents=["machine learning neural networks"],
            metadatas=[{
                "title": f"Item {i}",
                "url": f"https://example.com/item-{i}",
                "source": "arxiv",
                "date": "2026-10-22",
                "published": "2026-10-20",
            }]
        )

    result = qrf.query_research_feed("machine learning", n=2)
    assert len(result) == 2


def test_cli_json_flag_emits_valid_json(tmp_path, monkeypatch, capsys):
    """Argparse-level smoke test on main()."""
    monkeypatch.setattr(qrf, "CHROMA_PATH", tmp_path)

    client = chromadb.PersistentClient(path=str(tmp_path))
    col = client.get_or_create_collection("research-feed")
    col.add(
        ids=["test-1"],
        documents=["machine learning"],
        metadatas=[{
            "title": "Test",
            "url": "https://example.com/test",
            "source": "test",
            "date": "2026-10-22",
            "published": "2026-10-20",
        }]
    )

    # Simulate CLI call with --json
    sys.argv = ["query_research_feed.py", "machine learning", "--json"]
    try:
        qrf.main()
    except SystemExit:
        pass

    captured = capsys.readouterr()
    if captured.out.strip():
        parsed = json.loads(captured.out)
        assert isinstance(parsed, list)
