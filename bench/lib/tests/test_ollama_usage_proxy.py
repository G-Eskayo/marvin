#!/usr/bin/env python3
"""Tests for OllamaUsageProxy. Run via:
    ~/.agents/venv/bin/python -m pytest lib/tests/test_ollama_usage_proxy.py -v
"""
from __future__ import annotations
import json
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

LIB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LIB))

import pytest
from ollama_usage_proxy import OllamaUsageProxy


@pytest.fixture
def fake_ollama_server():
    """A minimal fake Ollama server for testing."""
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            path = self.path
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length)

            if path == "/api/chat":
                # Return a fake chat response
                response = {
                    "model": "test",
                    "message": {"content": "Hello"},
                    "prompt_eval_count": 100,
                    "eval_count": 50,
                }
                response_body = json.dumps(response).encode()
            elif path == "/api/broken":
                # Return malformed JSON
                response_body = b"{broken json"
            else:
                response_body = b'{"ok": true}'

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", len(response_body))
            self.end_headers()
            self.wfile.write(response_body)

        def do_GET(self):
            if self.path == "/api/tags":
                response = {"models": [{"name": "test:latest"}]}
                response_body = json.dumps(response).encode()
            else:
                response_body = b'{"ok": true}'

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", len(response_body))
            self.end_headers()
            self.wfile.write(response_body)

        def log_message(self, format, *args):
            pass

    server = HTTPServer(("localhost", 0), Handler)
    port = server.server_port
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://localhost:{port}"
    server.shutdown()


@pytest.fixture
def logfile():
    """Temporary log file."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
        path = f.name
    yield path
    Path(path).unlink(missing_ok=True)


class TestOllamaUsageProxy:
    """Test cases 4-7 from the design doc."""

    def test_case_4_ollama_unreachable(self, logfile):
        """Test case 4: Ollama unreachable when proxy starts.
        (In real test, we mock unreachability in requests rather than at start time.)
        """
        proxy = OllamaUsageProxy("http://localhost:9999", logfile)
        proxy.start()
        try:
            assert proxy.is_running()
            # Try to make a request to a non-existent upstream
            req = urllib.request.Request(
                f"http://localhost:{proxy.port}/api/chat",
                data=json.dumps({"model": "test"}).encode(),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with pytest.raises(urllib.error.URLError):
                urllib.request.urlopen(req, timeout=5)
            # Check that error was logged
            with open(logfile) as f:
                logs = [json.loads(line) for line in f]
            assert any(log.get("error") for log in logs)
        finally:
            proxy.stop()

    def test_case_5_malformed_json(self, fake_ollama_server, logfile):
        """Test case 5: Upstream returns malformed JSON.
        Proxy logs zero usage and is flagged, doesn't crash.
        """
        proxy = OllamaUsageProxy(fake_ollama_server, logfile)
        proxy.start()
        try:
            req = urllib.request.Request(
                f"http://localhost:{proxy.port}/api/broken",
                data=b"{}",
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req) as resp:
                assert resp.status == 200
            # Give time for async logging
            time.sleep(0.1)
            # Check that malformed response was logged
            with open(logfile) as f:
                logs = [json.loads(line) for line in f]
            assert any(
                log.get("path") == "/api/broken" and
                (log.get("error") or log.get("prompt_tokens") == 0)
                for log in logs
            )
        finally:
            proxy.stop()

    def test_case_6_concurrent_calls(self, fake_ollama_server, logfile):
        """Test case 6: Two tool calls land concurrently, both counted correctly.
        Thread-safe, none dropped or double-counted.
        """
        proxy = OllamaUsageProxy(fake_ollama_server, logfile)
        proxy.start()
        try:
            def make_request():
                req = urllib.request.Request(
                    f"http://localhost:{proxy.port}/api/chat",
                    data=json.dumps({"model": "test"}).encode(),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                urllib.request.urlopen(req, timeout=5)

            # Launch two requests concurrently
            threads = [threading.Thread(target=make_request) for _ in range(2)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

            # Give time for async logging
            time.sleep(0.2)

            # Check that both requests were logged
            with open(logfile) as f:
                logs = [json.loads(line) for line in f if line.strip()]
            chat_logs = [log for log in logs if log.get("path") == "/api/chat"]
            assert len(chat_logs) == 2, f"Expected 2 logs, got {len(chat_logs)}"
            # Check token counts are correct (100 prompt, 50 gen per call)
            for log in chat_logs:
                assert log["prompt_tokens"] == 100
                assert log["gen_tokens"] == 50
        finally:
            proxy.stop()

    def test_case_7_usage_log_per_run(self, fake_ollama_server, logfile):
        """Test case 7: Same ticket run twice (retry) — usage log is per-run-scoped,
        never accumulates across runs.
        """
        proxy = OllamaUsageProxy(fake_ollama_server, logfile)
        proxy.start()
        try:
            def make_request():
                req = urllib.request.Request(
                    f"http://localhost:{proxy.port}/api/chat",
                    data=json.dumps({"model": "test"}).encode(),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                urllib.request.urlopen(req, timeout=5)

            # Run 1
            make_request()
            time.sleep(0.1)
            with open(logfile) as f:
                logs_after_run1 = len([l for l in f if l.strip()])

            # Simulate clearing the log (like a retry with a new run-scoped logfile)
            logfile_run2 = logfile + ".run2"
            proxy.logfile = Path(logfile_run2)

            # Run 2
            make_request()
            time.sleep(0.1)

            # Check run 1 logfile still has 1 entry
            with open(logfile) as f:
                logs_run1 = [json.loads(l) for l in f if l.strip()]
            assert len(logs_run1) == 1

            # Check run 2 logfile has 1 entry
            with open(logfile_run2) as f:
                logs_run2 = [json.loads(l) for l in f if l.strip()]
            assert len(logs_run2) == 1

        finally:
            proxy.stop()
            Path(logfile_run2).unlink(missing_ok=True)

    def test_proxy_forwards_get_requests(self, fake_ollama_server, logfile):
        """Test that GET requests (e.g., /api/tags) are forwarded correctly."""
        proxy = OllamaUsageProxy(fake_ollama_server, logfile)
        proxy.start()
        try:
            req = urllib.request.Request(
                f"http://localhost:{proxy.port}/api/tags",
                method="GET",
            )
            with urllib.request.urlopen(req) as resp:
                data = json.loads(resp.read())
            assert "models" in data
        finally:
            proxy.stop()

    def test_proxy_start_stop_idempotent(self, logfile):
        """Test that start/stop can be called safely."""
        proxy = OllamaUsageProxy("http://localhost:11434", logfile)
        proxy.start()
        assert proxy.is_running()
        proxy.stop()
        assert not proxy.is_running()
        # Stop again should not crash
        proxy.stop()
        assert not proxy.is_running()
