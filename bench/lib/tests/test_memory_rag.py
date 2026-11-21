#!/usr/bin/env python3
"""Test suite for bench/lib/memory_rag.py embedding function error handling."""
import sys
from pathlib import Path
from unittest import mock

import pytest

# Add parent directories to path for imports
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lib"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import model_calls
from memory_rag import _CustomEmbeddingFunction


class TestMemoryRagEmbeddingErrorHandling:
    """Test that _CustomEmbeddingFunction handles embedding errors gracefully."""

    def test_embedding_function_handles_prompt_too_large(self):
        """_CustomEmbeddingFunction should return zero vector on PromptTooLargeError instead of raising."""
        ef = _CustomEmbeddingFunction()

        # Mock model_calls.embed to raise PromptTooLargeError
        with mock.patch("model_calls.embed") as mock_embed:
            mock_embed.side_effect = model_calls.PromptTooLargeError("Text too large")

            # Should not raise; should return a zero vector as placeholder
            result = ef(["some text that is too large"])

            # Should return one embedding per input
            assert len(result) == 1
            # Should be a 768-dim zero vector (nomic-embed-text dimensionality)
            assert len(result[0]) == 768
            assert all(v == 0.0 for v in result[0])

    def test_embedding_function_handles_multiple_texts_with_mixed_errors(self):
        """_CustomEmbeddingFunction should embed successful texts and return zeros for failed ones."""
        ef = _CustomEmbeddingFunction()

        # Mock model_calls.embed to succeed for first text, fail for second
        def mock_embed_impl(model, text, **kwargs):
            if "small" in text:
                return {"embedding": [0.1, 0.2] + [0.0] * 766}
            else:
                raise model_calls.PromptTooLargeError("Too large")

        with mock.patch("model_calls.embed", side_effect=mock_embed_impl):
            result = ef(["small text", "very large text that exceeds context"])

            # Should return embeddings for both
            assert len(result) == 2
            # First should be the real embedding
            assert result[0][0] == 0.1
            assert result[0][1] == 0.2
            # Second should be a zero vector
            assert all(v == 0.0 for v in result[1])

    def test_embedding_function_raises_on_ollama_unavailable(self):
        """_CustomEmbeddingFunction should raise on OllamaUnavailableError, not silently fail."""
        ef = _CustomEmbeddingFunction()

        # Mock model_calls.embed to raise OllamaUnavailableError
        with mock.patch("model_calls.embed") as mock_embed:
            mock_embed.side_effect = model_calls.OllamaUnavailableError("Ollama down")

            # Should raise (Ollama down is a real failure, not a text-too-large situation)
            with pytest.raises(RuntimeError, match="Cannot embed text"):
                ef(["some text"])

    def test_embedding_function_signature_matches_chromadb_protocol(self):
        """_CustomEmbeddingFunction __call__ should accept 'input' parameter (ChromaDB convention)."""
        ef = _CustomEmbeddingFunction()

        # Should accept 'input' as parameter name (required by ChromaDB protocol)
        with mock.patch("model_calls.embed") as mock_embed:
            mock_embed.return_value = {"embedding": [0.1] * 768}

            # Call with 'input' keyword argument (ChromaDB protocol)
            result = ef(input=["test"])
            assert len(result) == 1
            assert len(result[0]) == 768
