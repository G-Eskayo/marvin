#!/usr/bin/env python3
"""Test suite for retrieve.py error handling with PromptTooLargeError."""
import sys
from pathlib import Path
from unittest import mock

import pytest

# Add parent directories to path for imports
sys.path.insert(0, str(Path.home() / ".agents" / "lib"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import model_calls
from retrieve import embed_query, retrieve


class TestEmbedQueryErrorHandling:
    """Test that embed_query handles PromptTooLargeError distinctly from other errors."""

    def test_embed_query_propagates_prompt_too_large_error(self):
        """embed_query should propagate PromptTooLargeError, not silently return None."""
        with mock.patch("retrieve.model_calls.embed") as mock_embed:
            mock_embed.side_effect = model_calls.PromptTooLargeError("Query too large")

            # Should raise, not return None
            with pytest.raises(model_calls.PromptTooLargeError):
                embed_query("very long query" * 10000)

    def test_embed_query_returns_none_on_ollama_unavailable(self):
        """embed_query should return None when Ollama is unavailable."""
        with mock.patch("retrieve.model_calls.embed") as mock_embed:
            mock_embed.side_effect = model_calls.OllamaUnavailableError("Ollama down")

            # Should return None, not raise
            result = embed_query("test query")
            assert result is None

    def test_embed_query_returns_none_on_generic_exception(self):
        """embed_query should return None on generic exceptions."""
        with mock.patch("retrieve.model_calls.embed") as mock_embed:
            mock_embed.side_effect = Exception("Generic error")

            # Should return None
            result = embed_query("test query")
            assert result is None

    def test_embed_query_returns_embedding_on_success(self):
        """embed_query should return the embedding vector on success."""
        fake_embedding = [0.1, 0.2, 0.3, 0.4]
        with mock.patch("retrieve.model_calls.embed") as mock_embed:
            mock_embed.return_value = {"embedding": fake_embedding}

            result = embed_query("test query")
            assert result == fake_embedding


class TestRetrieveErrorHandling:
    """Test that retrieve() handles PromptTooLargeError in embed_query."""

    def test_retrieve_fallback_on_query_too_large(self):
        """retrieve() should fall back to tag_fallback when query is too large."""
        with mock.patch("retrieve.embed_query") as mock_embed_query:
            with mock.patch("retrieve.tag_fallback") as mock_fallback:
                mock_embed_query.side_effect = model_calls.PromptTooLargeError("Query too large")
                mock_fallback.return_value = [{"path": "test.md", "name": "test"}]

                result = retrieve("very long query" * 10000)

                # Should have called tag_fallback instead
                mock_fallback.assert_called_once()
                assert len(result) > 0

    def test_retrieve_fallback_on_ollama_unavailable(self):
        """retrieve() should fall back to tag_fallback when Ollama is unavailable."""
        with mock.patch("retrieve.embed_query") as mock_embed_query:
            with mock.patch("retrieve.tag_fallback") as mock_fallback:
                mock_embed_query.return_value = None  # embed_query returns None on unavailable
                mock_fallback.return_value = [{"path": "test.md", "name": "test"}]

                result = retrieve("test query")

                # Should have called tag_fallback
                mock_fallback.assert_called_once()
                assert len(result) > 0

    def test_retrieve_continues_to_semantic_search_on_success(self):
        """retrieve() should proceed to semantic search when embedding succeeds."""
        fake_embedding = [0.1, 0.2, 0.3]
        with mock.patch("retrieve.embed_query") as mock_embed_query:
            with mock.patch("retrieve.semantic_search") as mock_semantic:
                with mock.patch("retrieve.bm25_rerank") as mock_bm25:
                    with mock.patch("retrieve.rrf_merge") as mock_rrf:
                        mock_embed_query.return_value = fake_embedding
                        mock_semantic.return_value = [
                            {"path": "test.md", "name": "test", "score": 0.9, "source": "semantic"}
                        ]
                        mock_bm25.return_value = [
                            {"path": "test.md", "name": "test", "score": 0.9, "source": "semantic"}
                        ]
                        mock_rrf.return_value = [
                            {"path": "test.md", "name": "test", "score": 0.9, "source": "semantic"}
                        ]

                        result = retrieve("test query")

                        # Should have proceeded to semantic search
                        mock_semantic.assert_called_once()
                        mock_bm25.assert_called_once()
                        mock_rrf.assert_called_once()
                        assert len(result) > 0
