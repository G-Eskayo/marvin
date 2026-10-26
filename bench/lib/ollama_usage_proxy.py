#!/usr/bin/env python3
"""HTTP proxy in front of Ollama that logs per-call token counts to a JSONL file.

Usage:
    proxy = OllamaUsageProxy("http://localhost:11434", "/tmp/usage.jsonl")
    proxy.start()
    # make requests to http://localhost:8765 instead of localhost:11434
    proxy.stop()

The proxy intercepts /api/chat requests, forwards them to the real Ollama server,
extracts prompt_eval_count and eval_count from responses, and logs them to JSONL.
Thread-safe: multiple concurrent requests are properly counted and synchronized.
"""
from __future__ import annotations
import json
import logging
import os
import threading
import time
import traceback
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

_LOG = logging.getLogger(__name__)


class OllamaUsageProxy:
    """HTTP proxy for Ollama that logs token usage."""

    def __init__(self, upstream: str, logfile: str | Path, port: int = 8765):
        """
        upstream: URL of real Ollama server (e.g. "http://localhost:11434")
        logfile: path to JSONL file where usage will be logged
        port: port to listen on for proxied requests
        """
        self.upstream = upstream.rstrip("/")
        self.logfile = Path(logfile)
        self.port = port
        self.server = None
        self.thread = None
        self._usage_lock = threading.Lock()
        self._start_time = None

    def _log_usage(self, call_data: dict):
        """Thread-safe append to usage log."""
        with self._usage_lock:
            with open(self.logfile, "a") as f:
                f.write(json.dumps(call_data) + "\n")

    def start(self):
        """Start the proxy server in a background thread."""
        if self.server is not None:
            raise RuntimeError("proxy already running")

        self._logfile_check()
        self._start_time = time.time()

        # Create a handler class bound to this instance
        proxy = self
        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                handler_post(self, proxy)

            def do_GET(self):
                handler_get(self, proxy)

            def log_message(self, format, *args):
                # Suppress default HTTP logs
                pass

        self.server = HTTPServer(("localhost", self.port), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        _LOG.info(f"OllamaUsageProxy listening on http://localhost:{self.port}")

    def stop(self):
        """Stop the proxy server."""
        if self.server:
            self.server.shutdown()
            self.server = None
        if self.thread:
            self.thread.join(timeout=2)
            self.thread = None

    def _logfile_check(self):
        """Ensure logfile directory exists."""
        self.logfile.parent.mkdir(parents=True, exist_ok=True)

    def is_running(self) -> bool:
        return self.server is not None


def handler_post(handler_self: BaseHTTPRequestHandler, proxy: OllamaUsageProxy):
    """Handle POST requests (e.g., /api/chat)."""
    try:
        content_length = int(handler_self.headers.get("Content-Length", 0))
        if content_length > 100_000_000:
            handler_self.send_error(413, "Payload too large")
            return

        body = handler_self.rfile.read(content_length)
        path = handler_self.path
        url = f"{proxy.upstream}{path}"

        # Forward request to upstream
        req = urllib.request.Request(
            url,
            data=body,
            headers={k: v for k, v in handler_self.headers.items()
                     if k.lower() not in ("host", "content-length")},
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=600) as resp:
                response_body = resp.read()
                response_code = resp.status
                response_headers = dict(resp.headers)
        except urllib.error.HTTPError as e:
            handler_self.send_error(e.code, str(e))
            return
        except Exception as e:
            _LOG.warning(f"Upstream error: {e}")
            proxy._log_usage({
                "timestamp": time.time(),
                "path": path,
                "prompt_tokens": 0,
                "gen_tokens": 0,
                "error": str(e),
                "type": "upstream_error",
            })
            handler_self.send_error(502, f"Upstream error: {e}")
            return

        # Extract token counts if this is /api/chat
        if path == "/api/chat":
            try:
                response_json = json.loads(response_body)
                prompt_tokens = response_json.get("prompt_eval_count", 0)
                gen_tokens = response_json.get("eval_count", 0)
                proxy._log_usage({
                    "timestamp": time.time(),
                    "path": path,
                    "prompt_tokens": prompt_tokens,
                    "gen_tokens": gen_tokens,
                })
            except Exception as e:
                _LOG.warning(f"Failed to parse response or log usage: {e}")
                proxy._log_usage({
                    "timestamp": time.time(),
                    "path": path,
                    "prompt_tokens": 0,
                    "gen_tokens": 0,
                    "error": f"parse_error: {e}",
                })

        # Send response back to client
        handler_self.send_response(response_code)
        for k, v in response_headers.items():
            if k.lower() not in ("content-length",):
                handler_self.send_header(k, v)
        handler_self.send_header("Content-Length", len(response_body))
        handler_self.end_headers()
        handler_self.wfile.write(response_body)

    except Exception as e:
        _LOG.error(f"Handler error: {e}\n{traceback.format_exc()}")
        try:
            handler_self.send_error(500, f"Internal error: {e}")
        except Exception:
            pass


def handler_get(handler_self: BaseHTTPRequestHandler, proxy: OllamaUsageProxy):
    """Handle GET requests (e.g., /api/tags)."""
    try:
        path = handler_self.path
        url = f"{proxy.upstream}{path}"

        req = urllib.request.Request(url, method="GET")
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                response_body = resp.read()
                response_code = resp.status
                response_headers = dict(resp.headers)
        except Exception as e:
            _LOG.warning(f"Upstream GET error: {e}")
            handler_self.send_error(502, f"Upstream error: {e}")
            return

        handler_self.send_response(response_code)
        for k, v in response_headers.items():
            if k.lower() not in ("content-length",):
                handler_self.send_header(k, v)
        handler_self.send_header("Content-Length", len(response_body))
        handler_self.end_headers()
        handler_self.wfile.write(response_body)

    except Exception as e:
        _LOG.error(f"GET handler error: {e}")
        try:
            handler_self.send_error(500, f"Internal error: {e}")
        except Exception:
            pass
