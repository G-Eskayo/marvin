"""Regression tests for source_monitor.py functionality."""
import sys
import json
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock, mock_open
from datetime import date, timedelta

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from source_monitor import fetch_arxiv, fetch_github, fetch_hackernews, store_items, save_raw_cache


def mock_chromadb_import(mock_chroma_module):
    """Helper to mock chromadb import inside functions."""
    import builtins
    original_import = builtins.__import__

    def mock_import(name, *args, **kwargs):
        if name == "chromadb":
            return mock_chroma_module
        return original_import(name, *args, **kwargs)

    return mock_import


class TestFetchArxiv:
    """Test fetch_arxiv() function."""

    def test_fetch_arxiv_success(self):
        """Test successful arXiv API fetch."""
        arxiv_response = b"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <title>Paper on Quantization</title>
    <summary>Abstract about efficient quantization techniques</summary>
    <id>http://arxiv.org/abs/2301.12345v1</id>
    <published>2023-01-15T00:00:00Z</published>
  </entry>
</feed>"""

        with patch("source_monitor.urlopen") as mock_urlopen:
            mock_urlopen.return_value.__enter__.return_value.read.return_value = arxiv_response
            result = fetch_arxiv()

            assert len(result) >= 1
            assert result[0]["title"] == "Paper on Quantization"
            assert "quantization" in result[0]["summary"].lower()
            assert result[0]["source"] == "arxiv"
            assert result[0]["date"] == "2023-01-15"

    def test_fetch_arxiv_network_error(self):
        """Test graceful handling of network errors."""
        with patch("source_monitor.urlopen") as mock_urlopen:
            mock_urlopen.side_effect = Exception("Network error")
            result = fetch_arxiv()
            assert result == []

    def test_fetch_arxiv_empty_response(self):
        """Test handling of empty feed."""
        empty_response = b"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
</feed>"""

        with patch("source_monitor.urlopen") as mock_urlopen:
            mock_urlopen.return_value.__enter__.return_value.read.return_value = empty_response
            result = fetch_arxiv()
            assert result == []


class TestFetchGithub:
    """Test fetch_github() function."""

    def test_fetch_github_success(self):
        """Test successful GitHub API fetch."""
        github_response = json.dumps({
            "items": [
                {
                    "full_name": "user/llm-project",
                    "description": "A great LLM framework",
                    "html_url": "https://github.com/user/llm-project",
                    "created_at": "2023-06-15T00:00:00Z",
                    "topics": ["llm", "ai", "python"],
                }
            ]
        }).encode()

        with patch("source_monitor.urlopen") as mock_urlopen:
            mock_urlopen.return_value.__enter__.return_value.read.return_value = github_response
            result = fetch_github()

            assert len(result) >= 1
            assert result[0]["title"] == "user/llm-project"
            assert result[0]["source"] == "github"
            assert result[0]["date"] == "2023-06-15"
            assert "llm" in result[0]["tags"]

    def test_fetch_github_network_error(self):
        """Test graceful handling of network errors."""
        with patch("source_monitor.urlopen") as mock_urlopen:
            mock_urlopen.side_effect = Exception("Network error")
            result = fetch_github()
            assert result == []

    def test_fetch_github_rate_limit(self):
        """Test handling of rate limit response."""
        with patch("source_monitor.urlopen") as mock_urlopen:
            mock_urlopen.side_effect = Exception("HTTP Error 403")
            result = fetch_github()
            assert result == []


class TestFetchHackernews:
    """Test fetch_hackernews() function."""

    def test_fetch_hackernews_success(self):
        """Test successful Hacker News API fetch."""
        hn_response = json.dumps({
            "hits": [
                {
                    "title": "New AI Model Breaks Records",
                    "url": "https://example.com/ai-model",
                    "objectID": "12345",
                    "created_at": "2023-08-20T10:00:00Z",
                },
                {
                    "title": "Breaking: New AI Paper Released",
                    "url": "https://example.com/paper",
                    "objectID": "12346",
                    "created_at": "2023-08-20T11:00:00Z",
                },
                {
                    "title": "Local Gardening Tips",
                    "url": "https://example.com/garden",
                    "objectID": "12347",
                    "created_at": "2023-08-20T12:00:00Z",
                }
            ]
        }).encode()

        with patch("source_monitor.urlopen") as mock_urlopen:
            mock_urlopen.return_value.__enter__.return_value.read.return_value = hn_response
            result = fetch_hackernews()

            # Should only include AI-related posts
            assert len(result) == 2
            assert any("AI" in item["title"] for item in result)
            assert result[0]["source"] == "hackernews"

    def test_fetch_hackernews_filters_non_ai(self):
        """Test that non-AI posts are filtered out."""
        hn_response = json.dumps({
            "hits": [
                {"title": "Weather Today", "url": "http://example.com/weather", "objectID": "1"},
                {"title": "Cooking Tips", "url": "http://example.com/cooking", "objectID": "2"},
                {"title": "LLM Breakthrough", "url": "http://example.com/llm", "objectID": "3"},
            ]
        }).encode()

        with patch("source_monitor.urlopen") as mock_urlopen:
            mock_urlopen.return_value.__enter__.return_value.read.return_value = hn_response
            result = fetch_hackernews()
            # Only LLM post should be included
            assert len(result) == 1
            assert "LLM" in result[0]["title"]

    def test_fetch_hackernews_network_error(self):
        """Test graceful handling of network errors."""
        with patch("source_monitor.urlopen") as mock_urlopen:
            mock_urlopen.side_effect = Exception("Network error")
            result = fetch_hackernews()
            assert result == []


class TestStoreItems:
    """Test store_items() function with real ChromaDB."""

    def test_store_items_chromadb_missing(self):
        """Test graceful handling when chromadb is not installed."""
        import builtins
        original_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if name == "chromadb":
                raise ImportError("chromadb not installed")
            return original_import(name, *args, **kwargs)

        items = [{"url": "http://example.com", "title": "Test", "summary": "Test summary", "source": "test", "date": "2023-01-15", "tags": "test"}]
        with patch("builtins.__import__", side_effect=mock_import):
            result = store_items(items)
            assert result == 0

    def test_store_items_new_items(self, tmp_path, monkeypatch):
        """Test storing new items."""
        import chromadb

        client = chromadb.PersistentClient(path=str(tmp_path / "chroma"))
        col = client.get_or_create_collection("research-feed")

        monkeypatch.setattr("source_monitor.CHROMA_PATH", tmp_path / "chroma")
        monkeypatch.setattr("source_monitor.machine_label", lambda: "test-machine")

        items = [
            {
                "url": "http://arxiv.org/abs/2301.12345",
                "title": "Quantization Paper",
                "summary": "About quantization",
                "source": "arxiv",
                "date": "2023-01-15",
                "tags": "ai,ml",
            }
        ]

        result = store_items(items)

        assert result == 1
        stored = col.get(limit=100, include=["documents", "metadatas"])
        assert len(stored["ids"]) == 1
        assert "Quantization Paper" in stored["documents"][0]
        assert stored["metadatas"][0]["title"] == "Quantization Paper"

    def test_store_items_deduplication(self, tmp_path, monkeypatch):
        """Test that duplicate items are not re-added."""
        import chromadb
        import hashlib

        client = chromadb.PersistentClient(path=str(tmp_path / "chroma"))
        col = client.get_or_create_collection("research-feed")

        # Pre-populate with one item
        existing_url = "http://arxiv.org/abs/2301.12345"
        existing_id = "rf-" + hashlib.sha256(existing_url.encode()).hexdigest()[:16]
        col.add(
            documents=["Existing quantization paper"],
            metadatas=[{
                "title": "Existing Paper",
                "url": existing_url,
                "source": "arxiv",
                "date": "2023-01-15",
                "published": "2023-01-15",
                "tags": "ai",
                "correlated": "false",
                "matched_topics": "",
                "source_machine": "test-machine",
            }],
            ids=[existing_id],
        )

        monkeypatch.setattr("source_monitor.CHROMA_PATH", tmp_path / "chroma")
        monkeypatch.setattr("source_monitor.machine_label", lambda: "test-machine")

        items = [
            {
                "url": existing_url,
                "title": "Duplicate Paper",
                "summary": "Should be skipped",
                "source": "arxiv",
                "date": "2023-01-15",
                "tags": "ai",
            },
            {
                "url": "http://example.com/new-paper",
                "title": "New Paper",
                "summary": "Should be added",
                "source": "github",
                "date": "2023-01-16",
                "tags": "ai",
            }
        ]

        result = store_items(items)

        # Should only add 1 new item
        assert result == 1
        stored = col.get(limit=100, include=["metadatas"])
        assert len(stored["ids"]) == 2
        titles = [m["title"] for m in stored["metadatas"]]
        assert "Existing Paper" in titles
        assert "New Paper" in titles

    def test_store_items_metadata_structure(self, tmp_path, monkeypatch):
        """Test that stored metadata has correct structure."""
        import chromadb

        client = chromadb.PersistentClient(path=str(tmp_path / "chroma"))
        col = client.get_or_create_collection("research-feed")

        monkeypatch.setattr("source_monitor.CHROMA_PATH", tmp_path / "chroma")
        monkeypatch.setattr("source_monitor.machine_label", lambda: "test-machine")

        items = [
            {
                "url": "http://example.com/paper",
                "title": "Test Paper",
                "summary": "Summary text",
                "source": "arxiv",
                "date": "2023-01-15",
                "tags": "ai,ml,research",
            }
        ]

        store_items(items)

        stored = col.get(limit=100, include=["metadatas"])
        assert len(stored["ids"]) == 1

        metadata = stored["metadatas"][0]

        # Verify required metadata fields
        assert metadata["title"] == "Test Paper"
        assert metadata["url"] == "http://example.com/paper"
        assert metadata["source"] == "arxiv"
        assert metadata["date"]  # fetch date
        assert metadata["published"] == "2023-01-15"  # publication date
        assert metadata["tags"] == "ai,ml,research"
        assert metadata["correlated"] == "false"
        assert metadata["matched_topics"] == ""
        assert metadata["source_machine"] == "test-machine"


class TestSaveRawCache:
    """Test save_raw_cache() function."""

    def test_save_raw_cache_creates_file(self):
        """Test that cache file is created with correct structure."""
        mock_path = MagicMock(spec=Path)
        mock_path.exists.return_value = False

        items = [
            {"url": "http://example1.com", "title": "Item 1"},
            {"url": "http://example2.com", "title": "Item 2"},
        ]

        with patch("source_monitor.CACHE_DIR", mock_path):
            with patch("source_monitor.date") as mock_date:
                mock_date.today.return_value.isoformat.return_value = "2023-08-20"
                mock_path.__truediv__.return_value = mock_path
                mock_path.exists.return_value = False

                save_raw_cache(items)

                # Verify directory was created
                mock_path.mkdir.assert_called_with(parents=True, exist_ok=True)
                # Verify file was written
                mock_path.write_text.assert_called_once()

    def test_save_raw_cache_deduplication(self):
        """Test that duplicate URLs are not re-saved."""
        mock_path = MagicMock(spec=Path)

        # Mock existing cache with one item
        existing_data = json.dumps([{"url": "http://example1.com", "title": "Existing Item"}])
        mock_path.exists.return_value = True
        mock_path.read_text.return_value = existing_data

        items = [
            {"url": "http://example1.com", "title": "Existing Item"},  # Duplicate
            {"url": "http://example2.com", "title": "New Item"},
        ]

        with patch("source_monitor.CACHE_DIR", mock_path):
            with patch("source_monitor.date") as mock_date:
                mock_date.today.return_value.isoformat.return_value = "2023-08-20"
                mock_path.__truediv__.return_value = mock_path

                save_raw_cache(items)

                # Verify write was called
                mock_path.write_text.assert_called_once()
                written_data = json.loads(mock_path.write_text.call_args[0][0])
                # Should have 2 items (existing + new, no duplicate)
                assert len(written_data) == 2
