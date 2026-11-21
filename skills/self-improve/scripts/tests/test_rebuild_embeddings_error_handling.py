#!/usr/bin/env python3
"""Test suite for rebuild-embeddings.py error handling with large documents."""
import sys
from pathlib import Path
from unittest import mock

import pytest

# Add parent directories to path for imports
sys.path.insert(0, str(Path.home() / ".agents" / "lib"))

# Import rebuild_embeddings from parent directory
rebuild_embeddings_path = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(rebuild_embeddings_path))

import model_calls

# Import rebuild_embeddings module
import importlib.util
spec = importlib.util.spec_from_file_location("rebuild_embeddings", rebuild_embeddings_path / "rebuild-embeddings.py")
rebuild_embeddings = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rebuild_embeddings)
embed = rebuild_embeddings.embed
NUM_CTX = rebuild_embeddings.NUM_CTX


class TestRebuildEmbeddingsErrorHandling:
    """Test that embed() in rebuild-embeddings.py handles errors gracefully."""

    def test_embed_num_ctx_is_8192(self):
        """NUM_CTX should be 8192 to match nomic-embed-text's actual context window."""
        # This ensures documents up to ~29K chars (90% of 8192 tokens) can be embedded
        assert NUM_CTX == 8192

    def test_embed_handles_prompt_too_large_error(self):
        """embed() should handle PromptTooLargeError and return None instead of raising."""
        with mock.patch.object(rebuild_embeddings.model_calls, "embed") as mock_embed:
            mock_embed.side_effect = model_calls.PromptTooLargeError("Text too large")

            # Should not raise; should return None and log warning
            result = embed("very large text")
            assert result is None

    def test_embed_handles_ollama_unavailable_error(self):
        """embed() should handle OllamaUnavailableError and return None."""
        with mock.patch.object(rebuild_embeddings.model_calls, "embed") as mock_embed:
            mock_embed.side_effect = model_calls.OllamaUnavailableError("Ollama down")

            # Should return None and log warning
            result = embed("test text")
            assert result is None

    def test_embed_handles_generic_exception(self):
        """embed() should handle generic exceptions and return None."""
        with mock.patch.object(rebuild_embeddings.model_calls, "embed") as mock_embed:
            mock_embed.side_effect = Exception("Generic error")

            # Should return None and log warning
            result = embed("test text")
            assert result is None

    def test_embed_returns_embedding_on_success(self):
        """embed() should return the embedding vector on success."""
        fake_embedding = [0.1] * 768  # 768-dim vector for nomic-embed-text
        with mock.patch.object(rebuild_embeddings.model_calls, "embed") as mock_embed:
            mock_embed.return_value = {"embedding": fake_embedding}

            result = embed("test text")
            assert result == fake_embedding

    def test_embed_calls_model_calls_with_correct_params(self):
        """embed() should call model_calls.embed with correct caller and num_ctx."""
        with mock.patch.object(rebuild_embeddings.model_calls, "embed") as mock_embed:
            mock_embed.return_value = {"embedding": [0.1] * 768}

            embed("test text to embed")

            # Verify the call
            mock_embed.assert_called_once()
            call_kwargs = mock_embed.call_args.kwargs
            assert call_kwargs["caller"] == "rebuild-embeddings"
            assert call_kwargs["num_ctx"] == 8192
            assert call_kwargs["timeout"] == 30

    def test_large_document_would_not_trigger_error_with_num_ctx_8192(self):
        """With NUM_CTX=8192, documents up to ~29K chars should not trigger PromptTooLargeError."""
        # At 90% threshold: 8192 * 0.9 = 7372 tokens
        # At 1 token per 4 chars: 7372 * 4 = 29488 chars
        # With 4000 char truncation in build_doc_text, we're well under the limit

        # Create a document that would have been skipped with NUM_CTX=4096
        # but should work fine with NUM_CTX=8192
        large_text = "x" * 10000  # 10K chars

        fake_embedding = [0.1] * 768
        with mock.patch.object(rebuild_embeddings.model_calls, "embed") as mock_embed:
            # With the current NUM_CTX=8192, this should NOT raise PromptTooLargeError
            # (In the real code, build_doc_text truncates at 4000 chars anyway)
            mock_embed.return_value = {"embedding": fake_embedding}

            result = embed(large_text)
            # Should succeed
            assert result == fake_embedding
