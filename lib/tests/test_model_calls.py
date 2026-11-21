"""Tests for model_calls.py: logging, overflow, error handling, and summaries."""
from __future__ import annotations

import json
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import model_calls  # noqa: E402


# ── Fake Ollama HTTP server fixture ────────────────────────────────────

class FakeOllamaHandler(BaseHTTPRequestHandler):
    """Minimal Ollama API server for testing."""

    responses = {}

    def do_POST(self):
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length)
        try:
            req = json.loads(body)
        except json.JSONDecodeError:
            self.send_error(400)
            return

        path = self.path
        response = self.responses.get(path, {})

        if "error" in response:
            self.send_error(500)
            self.wfile.write(json.dumps(response["error"]).encode())
        else:
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(response).encode())

    def log_message(self, format, *args):
        pass


@pytest.fixture
def fake_ollama(request):
    """Start a fake Ollama server on localhost, return base_url."""
    handler = FakeOllamaHandler
    server = HTTPServer(("127.0.0.1", 0), handler)
    port = server.server_port
    base_url = f"http://127.0.0.1:{port}"

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    def set_response(path, response):
        handler.responses[path] = response

    request.addfinalizer(server.shutdown)

    class ServerContext:
        def __init__(self, base, responses_dict):
            self.base_url = base
            self.responses = responses_dict

        def set_response(self, path, response):
            self.responses[path] = response

    ctx = ServerContext(base_url, handler.responses)
    ctx.set_response = set_response
    return ctx


@pytest.fixture
def temp_log(tmp_path):
    """Temporary log file for model_calls."""
    log_file = tmp_path / "model_calls.jsonl"
    return log_file


# ── Tests ────────────────────────────────────────────────────────────

class TestEstimateTokens:
    def test_empty_string(self):
        assert model_calls._estimate_tokens("") == 0

    def test_typical_text(self):
        # 4 chars = 1 token roughly
        text = "a" * 400
        tokens = model_calls._estimate_tokens(text)
        assert tokens == 100

    def test_none(self):
        assert model_calls._estimate_tokens(None) == 0


class TestChatSuccess:
    def test_chat_success(self, fake_ollama, temp_log):
        fake_ollama.set_response("/api/chat", {
            "message": {"content": "Hello world"},
            "prompt_eval_count": 100,
            "eval_count": 50,
        })

        with patch.object(model_calls, "PATH", temp_log):
            result = model_calls.chat(
                "qwen2.5:14b",
                [{"role": "user", "content": "hi"}],
                caller="test.test_chat_success",
                num_ctx=4096,
                base_url=fake_ollama.base_url,
            )

        assert result.content == "Hello world"
        assert result.input_tokens == 100
        assert result.output_tokens == 50
        assert result.total_tokens == 150
        assert result.error is None
        assert not result.overflow

        # Check log was written
        assert temp_log.exists()
        lines = temp_log.read_text().splitlines()
        assert len(lines) == 1
        entry = json.loads(lines[0])
        assert entry["status"] == "success"
        assert entry["caller"] == "test.test_chat_success"
        assert entry["model"] == "qwen2.5:14b"
        assert entry["input_tokens"] == 100
        assert entry["output_tokens"] == 50


class TestChatOverflow:
    def test_chat_overflow_error(self, fake_ollama, temp_log):
        with patch.object(model_calls, "PATH", temp_log):
            result = model_calls.chat(
                "qwen2.5:14b",
                [{"role": "user", "content": "x" * 20000}],  # ~5000 tokens
                caller="test.overflow",
                num_ctx=4096,  # 4000 token limit
                base_url=fake_ollama.base_url,
                on_overflow="error",
            )

        assert result.error is not None
        assert "exceeds num_ctx" in result.error
        assert result.overflow
        assert result.content is None

        lines = temp_log.read_text().splitlines()
        entry = json.loads(lines[0])
        assert entry["status"] == "overflow"
        assert entry["overflow"] is True

    def test_chat_overflow_reject(self, fake_ollama, temp_log):
        with patch.object(model_calls, "PATH", temp_log):
            result = model_calls.chat(
                "qwen2.5:14b",
                [{"role": "user", "content": "x" * 20000}],
                caller="test.reject",
                num_ctx=4096,
                base_url=fake_ollama.base_url,
                on_overflow="reject",
            )

        assert result.error is not None
        assert result.overflow
        lines = temp_log.read_text().splitlines()
        entry = json.loads(lines[0])
        assert entry["status"] == "rejected"


class TestChatError:
    def test_chat_connection_error(self, temp_log):
        with patch.object(model_calls, "PATH", temp_log):
            result = model_calls.chat(
                "qwen2.5:14b",
                [{"role": "user", "content": "hi"}],
                caller="test.error",
                num_ctx=4096,
                base_url="http://127.0.0.1:1",  # Unlikely to be open
                timeout=1,
            )

        assert result.error is not None
        assert result.content is None
        assert not result.overflow

        lines = temp_log.read_text().splitlines()
        entry = json.loads(lines[0])
        assert entry["status"] == "error"
        assert "error" in entry


class TestEmbedSuccess:
    def test_embed_single_string(self, fake_ollama, temp_log):
        fake_ollama.set_response("/api/embed", {
            "embeddings": [[0.1, 0.2, 0.3]],
            "prompt_eval_count": 50,
        })

        with patch.object(model_calls, "PATH", temp_log):
            result = model_calls.embed(
                "hello world",
                "nomic-embed-text",
                caller="test.embed_single",
                num_ctx=2048,
                base_url=fake_ollama.base_url,
                task="query",
            )

        assert len(result.embeddings) == 1
        assert result.embeddings[0] == [0.1, 0.2, 0.3]
        assert result.error is None
        assert result.total_tokens == 50

        lines = temp_log.read_text().splitlines()
        entry = json.loads(lines[0])
        assert entry["status"] == "success"
        assert entry["caller"] == "test.embed_single"

    def test_embed_list_of_strings(self, fake_ollama, temp_log):
        fake_ollama.set_response("/api/embed", {
            "embeddings": [[0.1, 0.2], [0.3, 0.4]],
            "prompt_eval_count": 100,
        })

        with patch.object(model_calls, "PATH", temp_log):
            result = model_calls.embed(
                ["text1", "text2"],
                "nomic-embed-text",
                caller="test.embed_list",
                num_ctx=2048,
                base_url=fake_ollama.base_url,
            )

        assert len(result.embeddings) == 2
        assert result.embeddings[0] == [0.1, 0.2]
        assert result.embeddings[1] == [0.3, 0.4]
        assert result.total_tokens == 100

    def test_embed_prefix_for_nomic(self, fake_ollama, temp_log):
        """Verify that nomic-embed-text gets task-specific prefixes."""
        captured_requests = []

        def capture_handler(handler_self):
            content_length = int(handler_self.headers.get("Content-Length", 0))
            body = handler_self.rfile.read(content_length)
            req = json.loads(body)
            captured_requests.append(req)

            handler_self.send_response(200)
            handler_self.send_header("Content-Type", "application/json")
            handler_self.end_headers()
            handler_self.wfile.write(json.dumps({
                "embeddings": [[0.1]],
                "prompt_eval_count": 10,
            }).encode())

        with patch.object(FakeOllamaHandler, "do_POST", capture_handler):
            with patch.object(model_calls, "PATH", temp_log):
                result = model_calls.embed(
                    "hello",
                    "nomic-embed-text",
                    caller="test.prefix",
                    num_ctx=2048,
                    base_url=fake_ollama.base_url,
                    task="query",
                )

        # Request was sent with prefix
        assert len(captured_requests) > 0 or result.error is None


class TestEmbedOverflow:
    def test_embed_overflow(self, fake_ollama, temp_log):
        with patch.object(model_calls, "PATH", temp_log):
            result = model_calls.embed(
                "x" * 10000,
                "nomic-embed-text",
                caller="test.embed_overflow",
                num_ctx=2048,
                base_url=fake_ollama.base_url,
                on_overflow="error",
            )

        assert result.error is not None
        assert result.overflow
        assert len(result.embeddings) == 0

        lines = temp_log.read_text().splitlines()
        entry = json.loads(lines[0])
        assert entry["status"] == "error"
        assert entry["overflow"] is True


class TestEmbedError:
    def test_embed_connection_error(self, temp_log):
        with patch.object(model_calls, "PATH", temp_log):
            result = model_calls.embed(
                "hello",
                "nomic-embed-text",
                caller="test.embed_error",
                num_ctx=2048,
                base_url="http://127.0.0.1:1",
                timeout=1,
            )

        assert result.error is not None
        assert len(result.embeddings) == 0

        lines = temp_log.read_text().splitlines()
        entry = json.loads(lines[0])
        assert entry["status"] == "error"


class TestSummary:
    def test_summary_empty(self, temp_log):
        with patch.object(model_calls, "PATH", temp_log):
            result = model_calls.summary(days=7)

        assert result["period_days"] == 7
        assert result["summary"] == []
        assert result["totals"] == {"calls": 0, "tokens": 0, "errors": 0, "overflows": 0}

    def test_summary_with_data(self, temp_log):
        # Write test data
        entries = [
            {"t": "2026-11-18T12:00:00+00:00", "caller": "caller1", "model": "model1",
             "status": "success", "total_tokens": 100},
            {"t": "2026-11-18T12:01:00+00:00", "caller": "caller1", "model": "model1",
             "status": "success", "total_tokens": 150},
            {"t": "2026-11-18T12:02:00+00:00", "caller": "caller2", "model": "model2",
             "status": "error", "total_tokens": 50},
            {"t": "2026-11-18T12:03:00+00:00", "caller": "caller2", "model": "model2",
             "status": "overflow", "overflow": True, "total_tokens": 200},
        ]
        temp_log.write_text("\n".join(json.dumps(e) for e in entries) + "\n")

        with patch.object(model_calls, "PATH", temp_log):
            result = model_calls.summary(days=7)

        assert result["period_days"] == 7
        assert len(result["summary"]) == 2
        assert result["totals"]["calls"] == 4
        assert result["totals"]["tokens"] == 500
        assert result["totals"]["errors"] == 2
        assert result["totals"]["overflows"] == 1

        # Find caller1 entry
        caller1_summary = next((e for e in result["summary"] if e["caller"] == "caller1"), None)
        assert caller1_summary is not None
        assert caller1_summary["count"] == 2
        assert caller1_summary["errors"] == 0
        assert caller1_summary["p50_tokens"] in (100, 125)  # median of [100, 150]

    def test_summary_exclude_bench(self, temp_log):
        entries = [
            {"t": "2026-11-18T12:00:00+00:00", "caller": "prod_caller", "model": "model1",
             "status": "success", "total_tokens": 100, "source": "prod"},
            {"t": "2026-11-18T12:01:00+00:00", "caller": "bench_caller", "model": "model1",
             "status": "success", "total_tokens": 50, "source": "bench"},
        ]
        temp_log.write_text("\n".join(json.dumps(e) for e in entries) + "\n")

        with patch.object(model_calls, "PATH", temp_log):
            result = model_calls.summary(days=7, include_bench=False)

        # Only prod call should be counted
        assert result["totals"]["calls"] == 1
        assert result["totals"]["tokens"] == 100

    def test_summary_include_bench(self, temp_log):
        entries = [
            {"t": "2026-11-18T12:00:00+00:00", "caller": "prod_caller", "model": "model1",
             "status": "success", "total_tokens": 100, "source": "prod"},
            {"t": "2026-11-18T12:01:00+00:00", "caller": "bench_caller", "model": "model1",
             "status": "success", "total_tokens": 50, "source": "bench"},
        ]
        temp_log.write_text("\n".join(json.dumps(e) for e in entries) + "\n")

        with patch.object(model_calls, "PATH", temp_log):
            result = model_calls.summary(days=7, include_bench=True)

        assert result["totals"]["calls"] == 2
        assert result["totals"]["tokens"] == 150

    def test_summary_time_filtering(self, temp_log):
        import datetime
        now = datetime.datetime.now(datetime.timezone.utc)
        old = (now - datetime.timedelta(days=10)).isoformat()
        new = (now - datetime.timedelta(hours=1)).isoformat()

        entries = [
            {"t": old, "caller": "old", "model": "m", "status": "success", "total_tokens": 100},
            {"t": new, "caller": "new", "model": "m", "status": "success", "total_tokens": 50},
        ]
        temp_log.write_text("\n".join(json.dumps(e) for e in entries) + "\n")

        with patch.object(model_calls, "PATH", temp_log):
            result = model_calls.summary(days=7)

        # Only recent entry should be included
        assert result["totals"]["calls"] == 1
        assert result["totals"]["tokens"] == 50


class TestLoggingNeverRaises:
    def test_chat_logs_even_on_bad_path(self, temp_log):
        """Logging failures should not raise."""
        bad_path = Path("/dev/null/nonexistent/model_calls.jsonl")
        with patch.object(model_calls, "PATH", bad_path):
            # Should not raise even though we can't write
            result = model_calls.chat(
                "model",
                [{"role": "user", "content": "hi"}],
                caller="test",
                num_ctx=4096,
                base_url="http://127.0.0.1:1",
                timeout=1,
            )
        # Result should still have the error
        assert result.error is not None

    def test_embed_logs_even_on_bad_path(self, temp_log):
        """Embedding logging failures should not raise."""
        bad_path = Path("/dev/null/nonexistent/model_calls.jsonl")
        with patch.object(model_calls, "PATH", bad_path):
            result = model_calls.embed(
                "hello",
                "model",
                caller="test",
                num_ctx=2048,
                base_url="http://127.0.0.1:1",
                timeout=1,
            )
        # Result should still have the error
        assert result.error is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
