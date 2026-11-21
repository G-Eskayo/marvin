#!/usr/bin/env python3
"""Test suite for lib/model_calls.py wrapper functions.

Tests #1-12 from design doc: pre-flight guard, post-hoc flag, error handling,
concurrency/rotation, and behavior-preserving refactoring of existing call sites.
"""
import json
import tempfile
import threading
import time
from pathlib import Path
from unittest import mock

import pytest
import requests

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import model_calls


class TestChatPreflightGuard:
    """Tests #1-2: prompt too large errors before network call; boundary cases."""

    def test_chat_raises_prompt_too_large_before_network(self):
        """Test #1: chat() raises PromptTooLargeError before any network call."""
        # Estimate: "x" * 50000 / 4 = 12500 tokens, exceeds num_ctx=1000
        large_prompt = "x" * 50000
        messages = [{"role": "user", "content": large_prompt}]

        with pytest.raises(model_calls.PromptTooLargeError) as exc_info:
            model_calls.chat("test-model", messages, caller="test", num_ctx=1000)

        # Verify exception contains useful info
        assert "test" in str(exc_info.value)
        assert "1000" in str(exc_info.value)

    def test_chat_accepts_prompt_just_under_threshold(self):
        """Test #2: prompt just under threshold succeeds normally."""
        # Estimate: "x" * 3000 / 4 = 750 tokens, well under num_ctx=1000
        small_prompt = "x" * 3000
        messages = [{"role": "user", "content": small_prompt}]

        fake_response = {
            "model": "test-model",
            "created_at": "2026-01-01T00:00:00Z",
            "message": {"role": "assistant", "content": "test response"},
            "done": True,
            "prompt_eval_count": 100,
            "eval_count": 50,
        }

        with mock.patch("model_calls.requests.post") as mock_post:
            mock_post.return_value.json.return_value = fake_response
            result = model_calls.chat("test-model", messages, caller="test", num_ctx=1000)

        assert result["content"] == "test response"
        assert mock_post.called

    def test_chat_rejects_prompt_at_threshold(self):
        """Test #2b: prompt at exactly 90% of num_ctx is rejected."""
        # Estimate: 900 tokens exactly at num_ctx=1000 hits 90%
        large_prompt = "x" * 3600  # 3600/4 = 900
        messages = [{"role": "user", "content": large_prompt}]

        with pytest.raises(model_calls.PromptTooLargeError):
            model_calls.chat("test-model", messages, caller="test", num_ctx=1000)


class TestMandatoryKeywordArgs:
    """Test #3: omitting caller or num_ctx raises immediately."""

    def test_chat_missing_caller_raises(self):
        """Test #3: chat() raises ValueError if caller is missing."""
        messages = [{"role": "user", "content": "test"}]
        with pytest.raises((TypeError, ValueError)):
            model_calls.chat("test-model", messages, num_ctx=1000)

    def test_chat_missing_num_ctx_raises(self):
        """Test #3: chat() raises ValueError if num_ctx is missing."""
        messages = [{"role": "user", "content": "test"}]
        with pytest.raises((TypeError, ValueError)):
            model_calls.chat("test-model", messages, caller="test")

    def test_embed_missing_caller_raises(self):
        """Test #3: embed() raises ValueError if caller is missing."""
        with pytest.raises((TypeError, ValueError)):
            model_calls.embed("test-model", "test text", num_ctx=1000)

    def test_embed_missing_num_ctx_raises(self):
        """Test #3: embed() raises ValueError if caller is missing."""
        with pytest.raises((TypeError, ValueError)):
            model_calls.embed("test-model", "test text", caller="test")


class TestOllamaUnavailableError:
    """Test #4: connection/timeout errors return OllamaUnavailableError, never hang."""

    def test_chat_connection_refused(self):
        """Test #4: chat() catches connection refused and raises OllamaUnavailableError."""
        messages = [{"role": "user", "content": "test"}]
        with mock.patch("model_calls.requests.post") as mock_post:
            mock_post.side_effect = requests.ConnectionError("connection refused")

            with pytest.raises(model_calls.OllamaUnavailableError):
                model_calls.chat("test-model", messages, caller="test", num_ctx=1000)

    def test_chat_timeout(self):
        """Test #4: chat() catches timeout and raises OllamaUnavailableError."""
        messages = [{"role": "user", "content": "test"}]
        with mock.patch("model_calls.requests.post") as mock_post:
            mock_post.side_effect = requests.Timeout("connection timed out")

            with pytest.raises(model_calls.OllamaUnavailableError):
                model_calls.chat("test-model", messages, caller="test", num_ctx=1000, timeout=1)

    def test_embed_connection_refused(self):
        """Test #4: embed() catches connection errors."""
        with mock.patch("model_calls.requests.post") as mock_post:
            mock_post.side_effect = requests.ConnectionError("connection refused")

            with pytest.raises(model_calls.OllamaUnavailableError):
                model_calls.embed("test-model", "test text", caller="test", num_ctx=1000)


class TestUnknownTokenCounts:
    """Test #5: missing prompt_eval_count/eval_count logs as "unknown"."""

    def test_chat_missing_prompt_eval_count(self):
        """Test #5: response missing prompt_eval_count logs it as 'unknown'."""
        messages = [{"role": "user", "content": "test"}]
        fake_response = {
            "model": "test-model",
            "created_at": "2026-01-01T00:00:00Z",
            "message": {"role": "assistant", "content": "response"},
            "done": True,
            # deliberately omit prompt_eval_count
            "eval_count": 50,
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = Path(tmpdir) / "model-calls.jsonl"
            with mock.patch("model_calls.requests.post") as mock_post:
                mock_post.return_value.json.return_value = fake_response
                result = model_calls.chat(
                    "test-model", messages, caller="test", num_ctx=1000,
                    _log_path=log_path
                )

            assert result["prompt_tokens"] == "unknown"

            # Verify it was logged
            assert log_path.exists()
            logged = json.loads(log_path.read_text().strip())
            assert logged["prompt_tokens"] == "unknown"


class TestPossiblyTruncatedFlag:
    """Test #6: prompt_eval_count >= 90% of num_ctx sets possibly_truncated=True."""

    def test_chat_at_90_percent_flagged(self):
        """Test #6: prompt at 90% of num_ctx is flagged possibly_truncated."""
        messages = [{"role": "user", "content": "test"}]
        fake_response = {
            "model": "test-model",
            "created_at": "2026-01-01T00:00:00Z",
            "message": {"role": "assistant", "content": "response"},
            "done": True,
            "prompt_eval_count": 900,  # 90% of 1000
            "eval_count": 50,
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = Path(tmpdir) / "model-calls.jsonl"
            with mock.patch("model_calls.requests.post") as mock_post:
                mock_post.return_value.json.return_value = fake_response
                result = model_calls.chat(
                    "test-model", messages, caller="test", num_ctx=1000,
                    _log_path=log_path
                )

            assert result["possibly_truncated"] is True

    def test_chat_below_90_percent_not_flagged(self):
        """Test #6: prompt below 90% of num_ctx is not flagged."""
        messages = [{"role": "user", "content": "test"}]
        fake_response = {
            "model": "test-model",
            "created_at": "2026-01-01T00:00:00Z",
            "message": {"role": "assistant", "content": "response"},
            "done": True,
            "prompt_eval_count": 800,  # 80% of 1000
            "eval_count": 50,
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = Path(tmpdir) / "model-calls.jsonl"
            with mock.patch("model_calls.requests.post") as mock_post:
                mock_post.return_value.json.return_value = fake_response
                result = model_calls.chat(
                    "test-model", messages, caller="test", num_ctx=1000,
                    _log_path=log_path
                )

            assert result["possibly_truncated"] is False

    def test_chat_unknown_tokens_not_flagged(self):
        """Test #6: unknown prompt_tokens never flags possibly_truncated."""
        messages = [{"role": "user", "content": "test"}]
        fake_response = {
            "model": "test-model",
            "created_at": "2026-01-01T00:00:00Z",
            "message": {"role": "assistant", "content": "response"},
            "done": True,
            # omit prompt_eval_count
            "eval_count": 50,
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = Path(tmpdir) / "model-calls.jsonl"
            with mock.patch("model_calls.requests.post") as mock_post:
                mock_post.return_value.json.return_value = fake_response
                result = model_calls.chat(
                    "test-model", messages, caller="test", num_ctx=1000,
                    _log_path=log_path
                )

            assert result["possibly_truncated"] is False


class TestMalformedResponse:
    """Test #7: non-JSON response body is caught and logged as error."""

    def test_chat_malformed_json_response(self):
        """Test #7: malformed JSON from server raises OllamaUnavailableError."""
        messages = [{"role": "user", "content": "test"}]
        with mock.patch("model_calls.requests.post") as mock_post:
            mock_response = mock.MagicMock()
            mock_response.json.side_effect = json.JSONDecodeError("bad json", "", 0)
            mock_post.return_value = mock_response

            with pytest.raises(model_calls.OllamaUnavailableError):
                model_calls.chat("test-model", messages, caller="test", num_ctx=1000)


class TestBadInput:
    """Test #8: empty/None/wrong-type input is rejected immediately."""

    def test_chat_empty_messages_raises(self):
        """Test #8: chat() rejects empty messages list."""
        with pytest.raises(ValueError):
            model_calls.chat("test-model", [], caller="test", num_ctx=1000)

    def test_chat_none_messages_raises(self):
        """Test #8: chat() rejects None messages."""
        with pytest.raises((TypeError, ValueError)):
            model_calls.chat("test-model", None, caller="test", num_ctx=1000)

    def test_chat_wrong_type_messages_raises(self):
        """Test #8: chat() rejects non-list messages."""
        with pytest.raises((TypeError, ValueError)):
            model_calls.chat("test-model", "not a list", caller="test", num_ctx=1000)

    def test_embed_empty_text_raises(self):
        """Test #8: embed() rejects empty input_text."""
        with pytest.raises(ValueError):
            model_calls.embed("test-model", "", caller="test", num_ctx=1000)

    def test_embed_none_text_raises(self):
        """Test #8: embed() rejects None input_text."""
        with pytest.raises((TypeError, ValueError)):
            model_calls.embed("test-model", None, caller="test", num_ctx=1000)

    def test_embed_wrong_type_text_raises(self):
        """Test #8: embed() rejects non-string input_text."""
        with pytest.raises((TypeError, ValueError)):
            model_calls.embed("test-model", 123, caller="test", num_ctx=1000)


class TestConcurrency:
    """Test #9: N concurrent calls produce exactly N well-formed JSON lines."""

    def test_concurrent_appends_produce_n_lines(self):
        """Test #9: multiple concurrent chat() calls produce correct number of lines."""
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = Path(tmpdir) / "model-calls.jsonl"

            fake_response = {
                "model": "test-model",
                "created_at": "2026-01-01T00:00:00Z",
                "message": {"role": "assistant", "content": "response"},
                "done": True,
                "prompt_eval_count": 10,
                "eval_count": 5,
            }

            def make_call(i):
                messages = [{"role": "user", "content": f"test {i}"}]
                with mock.patch("model_calls.requests.post") as mock_post:
                    mock_post.return_value.json.return_value = fake_response
                    model_calls.chat(
                        "test-model", messages, caller="test", num_ctx=1000,
                        _log_path=log_path
                    )

            threads = [threading.Thread(target=make_call, args=(i,)) for i in range(5)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

            # Verify all lines are valid JSON
            lines = log_path.read_text().strip().split("\n")
            assert len(lines) == 5
            for line in lines:
                parsed = json.loads(line)
                assert "caller" in parsed
                assert "prompt_tokens" in parsed


class TestLoggingFailures:
    """Test #11: failing log destination never raises or blocks the caller."""

    def test_unwritable_log_does_not_raise(self):
        """Test #11: unreachable log directory does not raise."""
        messages = [{"role": "user", "content": "test"}]
        fake_response = {
            "model": "test-model",
            "created_at": "2026-01-01T00:00:00Z",
            "message": {"role": "assistant", "content": "response"},
            "done": True,
            "prompt_eval_count": 10,
            "eval_count": 5,
        }

        # Use a path that can't be written (deep nonexistent dir)
        bad_path = Path("/dev/null/nonexistent/model-calls.jsonl")

        with mock.patch("model_calls.requests.post") as mock_post:
            mock_post.return_value.json.return_value = fake_response
            # Should not raise even with bad log path
            result = model_calls.chat(
                "test-model", messages, caller="test", num_ctx=1000,
                _log_path=bad_path
            )

        assert result["content"] == "response"


class TestRepeatedCalls:
    """Test #12: repeated calls produce independent rows, no dedup."""

    def test_repeated_calls_produce_duplicate_rows(self):
        """Test #12: calling twice with same args produces two independent rows."""
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = Path(tmpdir) / "model-calls.jsonl"

            fake_response = {
                "model": "test-model",
                "created_at": "2026-01-01T00:00:00Z",
                "message": {"role": "assistant", "content": "response"},
                "done": True,
                "prompt_eval_count": 10,
                "eval_count": 5,
            }

            messages = [{"role": "user", "content": "identical test"}]

            with mock.patch("model_calls.requests.post") as mock_post:
                mock_post.return_value.json.return_value = fake_response

                # Call twice with identical args
                model_calls.chat(
                    "test-model", messages, caller="test", num_ctx=1000,
                    _log_path=log_path
                )
                model_calls.chat(
                    "test-model", messages, caller="test", num_ctx=1000,
                    _log_path=log_path
                )

            # Verify two independent rows were logged
            lines = log_path.read_text().strip().split("\n")
            assert len(lines) == 2
            line1 = json.loads(lines[0])
            line2 = json.loads(lines[1])
            # Same content, but separate rows
            assert line1["caller"] == line2["caller"] == "test"
            assert line1["prompt_tokens"] == line2["prompt_tokens"] == 10


class TestNonDictResponse:
    """Test: non-dict response from resp.json() raises OllamaUnavailableError."""

    def test_chat_response_is_list(self):
        """chat() should raise OllamaUnavailableError if response is a list instead of dict."""
        messages = [{"role": "user", "content": "test"}]
        with mock.patch("model_calls.requests.post") as mock_post:
            mock_response = mock.MagicMock()
            mock_response.json.return_value = []  # List instead of dict
            mock_post.return_value = mock_response

            with pytest.raises(model_calls.OllamaUnavailableError):
                model_calls.chat("test-model", messages, caller="test", num_ctx=1000)

    def test_chat_response_is_string(self):
        """chat() should raise OllamaUnavailableError if response is a string instead of dict."""
        messages = [{"role": "user", "content": "test"}]
        with mock.patch("model_calls.requests.post") as mock_post:
            mock_response = mock.MagicMock()
            mock_response.json.return_value = "not a dict"
            mock_post.return_value = mock_response

            with pytest.raises(model_calls.OllamaUnavailableError):
                model_calls.chat("test-model", messages, caller="test", num_ctx=1000)

    def test_chat_message_field_not_dict(self):
        """chat() should raise OllamaUnavailableError if message field is not a dict."""
        messages = [{"role": "user", "content": "test"}]
        fake_response = {
            "model": "test-model",
            "created_at": "2026-01-01T00:00:00Z",
            "message": "not a dict",  # Should be dict
            "done": True,
            "prompt_eval_count": 100,
            "eval_count": 50,
        }
        with mock.patch("model_calls.requests.post") as mock_post:
            mock_response = mock.MagicMock()
            mock_response.json.return_value = fake_response
            mock_post.return_value = mock_response

            with pytest.raises(model_calls.OllamaUnavailableError):
                model_calls.chat("test-model", messages, caller="test", num_ctx=1000)

    def test_embed_response_is_list(self):
        """embed() should raise OllamaUnavailableError if response is a list instead of dict."""
        with mock.patch("model_calls.requests.post") as mock_post:
            mock_response = mock.MagicMock()
            mock_response.json.return_value = []  # List instead of dict
            mock_post.return_value = mock_response

            with pytest.raises(model_calls.OllamaUnavailableError):
                model_calls.embed("test-model", "test text", caller="test", num_ctx=1000)


class TestEmbeddingsHandling:
    """Test: missing/empty embeddings raise OllamaUnavailableError."""

    def test_embed_missing_embeddings_key(self):
        """embed() should raise OllamaUnavailableError if 'embeddings' key is missing."""
        fake_response = {
            "model": "test-model",
            "prompt_eval_count": 10,
            # deliberately omit 'embeddings'
        }
        with mock.patch("model_calls.requests.post") as mock_post:
            mock_response = mock.MagicMock()
            mock_response.json.return_value = fake_response
            mock_post.return_value = mock_response

            with pytest.raises(model_calls.OllamaUnavailableError):
                model_calls.embed("test-model", "test text", caller="test", num_ctx=1000)

    def test_embed_empty_embeddings_list(self):
        """embed() should raise OllamaUnavailableError if 'embeddings' list is empty."""
        fake_response = {
            "model": "test-model",
            "embeddings": [],  # Empty list
            "prompt_eval_count": 10,
        }
        with mock.patch("model_calls.requests.post") as mock_post:
            mock_response = mock.MagicMock()
            mock_response.json.return_value = fake_response
            mock_post.return_value = mock_response

            with pytest.raises(model_calls.OllamaUnavailableError):
                model_calls.embed("test-model", "test text", caller="test", num_ctx=1000)

    def test_embed_embedding_is_empty_list(self):
        """embed() should raise OllamaUnavailableError if embedding vector is empty."""
        fake_response = {
            "model": "test-model",
            "embeddings": [[]],  # Embedding vector is empty list
            "prompt_eval_count": 10,
        }
        with mock.patch("model_calls.requests.post") as mock_post:
            mock_response = mock.MagicMock()
            mock_response.json.return_value = fake_response
            mock_post.return_value = mock_response

            with pytest.raises(model_calls.OllamaUnavailableError):
                model_calls.embed("test-model", "test text", caller="test", num_ctx=1000)

    def test_embed_success_with_valid_embedding(self):
        """embed() should succeed with valid embedding vector."""
        fake_response = {
            "model": "test-model",
            "embeddings": [[0.1, 0.2, 0.3, 0.4]],
            "prompt_eval_count": 10,
        }
        with mock.patch("model_calls.requests.post") as mock_post:
            mock_response = mock.MagicMock()
            mock_response.json.return_value = fake_response
            mock_post.return_value = mock_response

            result = model_calls.embed("test-model", "test text", caller="test", num_ctx=1000)
            assert result["embedding"] == [0.1, 0.2, 0.3, 0.4]


class TestDurationFields:
    """Test: duration fields are properly extracted and logged."""

    def test_chat_duration_fields_recorded(self):
        """chat() should extract and record duration fields in result and log."""
        messages = [{"role": "user", "content": "test"}]
        fake_response = {
            "model": "test-model",
            "created_at": "2026-01-01T00:00:00Z",
            "message": {"role": "assistant", "content": "response"},
            "done": True,
            "prompt_eval_count": 10,
            "eval_count": 5,
            "load_duration": 1_000_000,  # 1 ms in nanoseconds
            "prompt_eval_duration": 2_000_000,  # 2 ms in nanoseconds
            "eval_duration": 3_000_000,  # 3 ms in nanoseconds
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = Path(tmpdir) / "model-calls.jsonl"
            with mock.patch("model_calls.requests.post") as mock_post:
                mock_response = mock.MagicMock()
                mock_response.json.return_value = fake_response
                mock_post.return_value = mock_response

                result = model_calls.chat(
                    "test-model", messages, caller="test", num_ctx=1000,
                    _log_path=log_path
                )

            # Check result dict has duration fields
            assert result["load_duration_ms"] == 1
            assert result["prompt_eval_duration_ms"] == 2
            assert result["eval_duration_ms"] == 3

            # Check log entry has duration fields
            logged = json.loads(log_path.read_text().strip())
            assert logged["load_duration_ms"] == 1
            assert logged["prompt_eval_duration_ms"] == 2
            assert logged["eval_duration_ms"] == 3

    def test_chat_duration_fields_missing(self):
        """chat() should handle missing duration fields gracefully."""
        messages = [{"role": "user", "content": "test"}]
        fake_response = {
            "model": "test-model",
            "created_at": "2026-01-01T00:00:00Z",
            "message": {"role": "assistant", "content": "response"},
            "done": True,
            "prompt_eval_count": 10,
            "eval_count": 5,
            # Deliberately omit duration fields
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = Path(tmpdir) / "model-calls.jsonl"
            with mock.patch("model_calls.requests.post") as mock_post:
                mock_response = mock.MagicMock()
                mock_response.json.return_value = fake_response
                mock_post.return_value = mock_response

                result = model_calls.chat(
                    "test-model", messages, caller="test", num_ctx=1000,
                    _log_path=log_path
                )

            # Should default to None when missing
            assert result["load_duration_ms"] is None
            assert result["prompt_eval_duration_ms"] is None
            assert result["eval_duration_ms"] is None


class TestEmbedRequestBody:
    """Test: embed() request body includes num_ctx and truncate=False options."""

    def test_embed_sends_num_ctx_and_truncate_options(self):
        """embed() should send options with num_ctx and truncate=False to prevent server-side truncation."""
        fake_response = {
            "model": "test-model",
            "embeddings": [[0.1, 0.2, 0.3]],
            "prompt_eval_count": 100,
        }
        with mock.patch("model_calls.requests.post") as mock_post:
            mock_response = mock.MagicMock()
            mock_response.json.return_value = fake_response
            mock_post.return_value = mock_response

            result = model_calls.embed("test-model", "test text", caller="test", num_ctx=4096)

            # Verify the request was made
            assert mock_post.called
            # Get the actual request body that was sent
            call_args = mock_post.call_args
            request_body = call_args.kwargs["json"]

            # Verify options are present with num_ctx and truncate
            assert "options" in request_body
            assert request_body["options"]["num_ctx"] == 4096
            assert request_body["options"]["truncate"] is False
            assert result["embedding"] == [0.1, 0.2, 0.3]

    def test_embed_request_format(self):
        """embed() should send correct request format to /api/embed endpoint."""
        fake_response = {
            "model": "nomic-embed-text",
            "embeddings": [[0.1] * 768],  # 768-dim vector
            "prompt_eval_count": 50,
        }
        with mock.patch("model_calls.requests.post") as mock_post:
            mock_response = mock.MagicMock()
            mock_response.json.return_value = fake_response
            mock_post.return_value = mock_response

            result = model_calls.embed(
                "nomic-embed-text", "search document: test",
                caller="test-caller", num_ctx=8192
            )

            # Verify endpoint
            assert mock_post.call_args[0][0] == "http://localhost:11434/api/embed"

            # Verify request body structure
            request_body = mock_post.call_args.kwargs["json"]
            assert request_body["model"] == "nomic-embed-text"
            assert request_body["input"] == "search document: test"
            assert request_body["options"]["num_ctx"] == 8192
            assert request_body["options"]["truncate"] is False


class TestMainArgParsing:
    """Test: main() handles missing subcommand and argument access correctly."""

    def test_main_no_subcommand_uses_default_days(self):
        """main() should not crash when called with no subcommand, using default days=7."""
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = Path(tmpdir) / "model-calls.jsonl"
            # Create empty log file
            log_path.write_text("")

            # Mock sys.argv to simulate: python model_calls.py
            with mock.patch("sys.argv", ["model_calls.py"]):
                with mock.patch("model_calls._DEFAULT_LOG_PATH", log_path):
                    # Should not raise AttributeError on args.days
                    model_calls.main()

    def test_main_summary_subcommand_with_args(self):
        """main() should handle summary subcommand with --days argument."""
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = Path(tmpdir) / "model-calls.jsonl"
            log_path.write_text("")

            # Mock sys.argv to simulate: python model_calls.py summary --days 14
            with mock.patch("sys.argv", ["model_calls.py", "summary", "--days", "14"]):
                with mock.patch("model_calls._DEFAULT_LOG_PATH", log_path):
                    # Should not raise
                    model_calls.main()

    def test_main_with_json_output_flag(self):
        """main() with --json flag should output valid JSON."""
        import io
        fake_response = {
            "model": "test-model",
            "created_at": "2026-01-01T00:00:00Z",
            "message": {"role": "assistant", "content": "response"},
            "done": True,
            "prompt_eval_count": 10,
            "eval_count": 5,
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = Path(tmpdir) / "model-calls.jsonl"
            # Add a log entry
            log_entry = {
                "timestamp": "2026-01-01T00:00:00+00:00",
                "machine": "test-machine",
                "caller": "test-caller",
                "model": "test-model",
                "prompt_tokens": 10,
                "eval_count": 5,
                "possibly_truncated": False,
                "status": "success",
            }
            log_path.write_text(json.dumps(log_entry))

            with mock.patch("sys.argv", ["model_calls.py", "summary", "--json"]):
                with mock.patch("model_calls._DEFAULT_LOG_PATH", log_path):
                    with mock.patch("sys.stdout", new_callable=io.StringIO) as mock_stdout:
                        model_calls.main()
                        output = mock_stdout.getvalue()
                        # Should be valid JSON
                        parsed = json.loads(output)
                        assert isinstance(parsed, list)
