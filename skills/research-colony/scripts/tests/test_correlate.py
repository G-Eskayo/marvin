"""Regression tests for correlate.py functionality."""
import sys
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from correlate import roadmap_match, correlate


def mock_chromadb_import(mock_chroma_module):
    """Helper to mock chromadb import inside functions."""
    import builtins
    original_import = builtins.__import__

    def mock_import(name, *args, **kwargs):
        if name == "chromadb":
            return mock_chroma_module
        return original_import(name, *args, **kwargs)

    return mock_import


class TestRoadmapMatch:
    """Test roadmap_match() keyword detection."""

    def test_exact_keyword_match(self):
        """Test matching a single exact keyword."""
        result = roadmap_match("This paper is about quantization techniques")
        assert "A.quantization" in result

    def test_multiple_keyword_match(self):
        """Test matching multiple keywords in same text."""
        result = roadmap_match("quantization and RAG systems with embeddings")
        assert "A.quantization" in result
        assert "A.rag" in result
        assert "C.embedding" in result

    def test_no_match(self):
        """Test when no keywords are found."""
        result = roadmap_match("This is about cooking recipes and gardening")
        assert result == ""

    def test_case_insensitive(self):
        """Test keyword matching is case-insensitive."""
        result = roadmap_match("QUANTIZATION is important for LLMs")
        assert "A.quantization" in result

    def test_partial_keyword_match(self):
        """Test that keywords match substrings."""
        result = roadmap_match("fine-tuning models is common")
        assert "G.fine-tuning" in result

    def test_sorted_output(self):
        """Test that results are sorted alphabetically."""
        text = "rag and quantization and benchmark all matter"
        result = roadmap_match(text)
        # Results should come in sorted order
        parts = result.split(", ")
        assert parts == sorted(parts)

    def test_space_keywords(self):
        """Test keywords with spaces in them (e.g., ' mcp ')."""
        result = roadmap_match("the MCP protocol is important")
        assert "B.mcp" in result

    def test_multi_word_phrase(self):
        """Test multi-word keyword matching."""
        result = roadmap_match("retrieval augmented generation with vectors")
        assert "A.rag" in result

    def test_unique_sections_only(self):
        """Test that duplicate section matches are deduplicated."""
        # Test with text that might match the same section multiple ways
        result = roadmap_match("model context protocol and MCP protocol")
        parts = result.split(", ")
        # Should not have duplicates
        assert len(parts) == len(set(parts))


class TestCorrelateFunction:
    """Test correlate() function behavior with real ChromaDB."""

    def test_correlate_chromadb_import_missing(self):
        """Test graceful handling when chromadb is not installed."""
        import builtins
        original_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if name == "chromadb":
                raise ImportError("chromadb not installed")
            return original_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=mock_import):
            result = correlate()
            assert result == []

    def test_correlate_empty_research_feed(self, tmp_path, monkeypatch):
        """Test with empty research-feed collection."""
        import chromadb

        # Use temp directory for ChromaDB
        client = chromadb.PersistentClient(path=str(tmp_path / "chroma"))
        research_col = client.get_or_create_collection("research-feed")

        # Patch the CHROMA_PATH to use our temp directory
        monkeypatch.setattr("correlate.CHROMA_PATH", tmp_path / "chroma")

        result = correlate()
        assert result == []

    def test_correlate_roadmap_keyword_match(self, tmp_path, monkeypatch):
        """Test correlation based on roadmap keyword matching."""
        import chromadb
        from datetime import date

        # Create real ChromaDB with test data
        client = chromadb.PersistentClient(path=str(tmp_path / "chroma"))
        research_col = client.get_or_create_collection("research-feed")

        today = date.today().isoformat()
        research_col.add(
            documents=["This paper is about quantization techniques"],
            metadatas=[{
                "title": "Quantization Paper",
                "url": "http://example.com",
                "source": "arxiv",
                "date": today,
            }],
            ids=["rf-test123"],
        )

        monkeypatch.setattr("correlate.CHROMA_PATH", tmp_path / "chroma")

        result = correlate()
        assert len(result) == 1
        assert result[0]["title"] == "Quantization Paper"
        assert "A.quantization" in result[0]["matched"]

    def test_correlate_no_match(self, tmp_path, monkeypatch):
        """Test items that don't match any roadmap keywords."""
        import chromadb
        from datetime import date

        client = chromadb.PersistentClient(path=str(tmp_path / "chroma"))
        research_col = client.get_or_create_collection("research-feed")

        today = date.today().isoformat()
        research_col.add(
            documents=["Random topic about cooking recipes"],
            metadatas=[{
                "title": "Cooking Tips",
                "url": "http://example.com",
                "source": "hackernews",
                "date": today,
            }],
            ids=["rf-test789"],
        )

        monkeypatch.setattr("correlate.CHROMA_PATH", tmp_path / "chroma")

        result = correlate()
        assert len(result) == 0

    def test_correlate_multiple_keywords(self, tmp_path, monkeypatch):
        """Test correlation matching multiple roadmap keywords."""
        import chromadb
        from datetime import date

        client = chromadb.PersistentClient(path=str(tmp_path / "chroma"))
        research_col = client.get_or_create_collection("research-feed")

        today = date.today().isoformat()
        research_col.add(
            documents=["Paper combining quantization with RAG and embeddings"],
            metadatas=[{
                "title": "Multi-Topic Paper",
                "url": "http://example.com/paper1",
                "source": "arxiv",
                "date": today,
            }],
            ids=["rf-test456"],
        )

        monkeypatch.setattr("correlate.CHROMA_PATH", tmp_path / "chroma")

        result = correlate()
        assert len(result) == 1
        matched = result[0]["matched"]
        assert "A.quantization" in matched
        assert "A.rag" in matched
        assert "C.embedding" in matched

    def test_correlate_metadata_truncation(self, tmp_path, monkeypatch):
        """Test that matched_topics is truncated to 300 chars."""
        import chromadb
        from datetime import date

        client = chromadb.PersistentClient(path=str(tmp_path / "chroma"))
        research_col = client.get_or_create_collection("research-feed")

        # Create a very long document that matches many keywords
        long_doc = " ".join(["quantization rag mcp embedding"] * 50)

        today = date.today().isoformat()
        research_col.add(
            documents=[long_doc],
            metadatas=[{
                "title": "Long Paper",
                "url": "http://example.com/long",
                "source": "arxiv",
                "date": today,
            }],
            ids=["rf-long"],
        )

        monkeypatch.setattr("correlate.CHROMA_PATH", tmp_path / "chroma")

        result = correlate()
        assert len(result) == 1
        matched = result[0]["matched"]
        assert len(matched) <= 300

    def test_correlate_date_filtering(self, tmp_path, monkeypatch):
        """Test that only today's items are correlated."""
        import chromadb
        from datetime import date, timedelta

        client = chromadb.PersistentClient(path=str(tmp_path / "chroma"))
        research_col = client.get_or_create_collection("research-feed")

        today = date.today().isoformat()
        yesterday = (date.today() - timedelta(days=1)).isoformat()

        # Add items from both today and yesterday
        research_col.add(
            documents=[
                "This paper is about quantization",
                "Yesterday's quantization paper"
            ],
            metadatas=[
                {
                    "title": "Today's Quantization Paper",
                    "url": "http://example.com/today",
                    "source": "arxiv",
                    "date": today,
                },
                {
                    "title": "Yesterday's Quantization Paper",
                    "url": "http://example.com/yesterday",
                    "source": "arxiv",
                    "date": yesterday,
                }
            ],
            ids=["rf-today", "rf-yesterday"],
        )

        monkeypatch.setattr("correlate.CHROMA_PATH", tmp_path / "chroma")

        result = correlate()
        # Should only correlate today's item
        assert len(result) == 1
        assert result[0]["title"] == "Today's Quantization Paper"
