"""Tests for the Semantic Scholar API client. Run via:
    ~/.agents/venv/bin/python -m pytest lib/tests/test_s2_client.py -v
"""
import os
import sys
from pathlib import Path

import pytest
import requests

# Add lib to path
LIB = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(LIB))

from s2_client import get_with_retry, s2_id


# ── s2_id (DOI vs arXiv ID namespace detection) ────────────────────────────

def test_s2_id_prefixes_bare_doi():
    assert s2_id("10.1234/example") == "DOI:10.1234/example"


def test_s2_id_prefixes_bare_arxiv_id():
    assert s2_id("2503.03704") == "ARXIV:2503.03704"


def test_s2_id_prefixes_bare_arxiv_id_with_version_suffix():
    assert s2_id("2503.03704v2") == "ARXIV:2503.03704v2"


def test_s2_id_passes_through_already_prefixed_identifiers():
    assert s2_id("DOI:10.1234/example") == "DOI:10.1234/example"
    assert s2_id("ARXIV:2503.03704") == "ARXIV:2503.03704"
    assert s2_id("CorpusId:12345") == "CorpusId:12345"


# ── get_with_retry (429 rate-limit handling) ────────────────────────────────

class _FakeResponse:
    def __init__(self, status_code):
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code not in (200, 201, 204):
            raise requests.exceptions.HTTPError(response=self)

    def json(self):
        return {"ok": True}


def test_get_with_retry_succeeds_on_200(monkeypatch):
    def fake_get(url, params=None, timeout=None, headers=None):
        return _FakeResponse(200)

    monkeypatch.setattr("requests.get", fake_get)

    resp = get_with_retry("http://example.com", params={}, timeout=15)

    assert resp.status_code == 200


def test_get_with_retry_retries_on_429_then_succeeds(monkeypatch):
    calls = {"count": 0}

    def fake_get(url, params=None, timeout=None, headers=None):
        calls["count"] += 1
        return _FakeResponse(429) if calls["count"] == 1 else _FakeResponse(200)

    monkeypatch.setattr("requests.get", fake_get)
    monkeypatch.setattr("time.sleep", lambda seconds: None)

    resp = get_with_retry("http://example.com", params={}, timeout=15, max_retries=3)

    assert resp.status_code == 200
    assert calls["count"] == 2


def test_get_with_retry_retries_multiple_429s(monkeypatch):
    calls = {"count": 0}

    def fake_get(url, params=None, timeout=None, headers=None):
        calls["count"] += 1
        return _FakeResponse(429) if calls["count"] < 3 else _FakeResponse(200)

    monkeypatch.setattr("requests.get", fake_get)
    monkeypatch.setattr("time.sleep", lambda seconds: None)

    resp = get_with_retry("http://example.com", params={}, timeout=15, max_retries=5)

    assert resp.status_code == 200
    assert calls["count"] == 3


def test_get_with_retry_gives_up_after_max_retries(monkeypatch):
    def fake_get(url, params=None, timeout=None, headers=None):
        return _FakeResponse(429)

    monkeypatch.setattr("requests.get", fake_get)
    monkeypatch.setattr("time.sleep", lambda seconds: None)

    with pytest.raises(requests.exceptions.HTTPError):
        get_with_retry("http://example.com", params={}, timeout=15, max_retries=2)


def test_get_with_retry_raises_non_429_errors_immediately(monkeypatch):
    def fake_get(url, params=None, timeout=None, headers=None):
        return _FakeResponse(500)

    monkeypatch.setattr("requests.get", fake_get)

    with pytest.raises(requests.exceptions.HTTPError):
        get_with_retry("http://example.com", params={}, timeout=15, max_retries=5)


def test_get_with_retry_honors_s2_api_key_from_env(monkeypatch):
    captured_headers = []

    def fake_get(url, params=None, timeout=None, headers=None):
        captured_headers.append(headers)
        return _FakeResponse(200)

    monkeypatch.setattr("requests.get", fake_get)
    monkeypatch.setenv("S2_API_KEY", "test-key-12345")

    get_with_retry("http://example.com", params={}, timeout=15)

    assert len(captured_headers) == 1
    assert captured_headers[0]["x-api-key"] == "test-key-12345"


def test_get_with_retry_preserves_caller_headers_and_adds_api_key(monkeypatch):
    captured_headers = []

    def fake_get(url, params=None, timeout=None, headers=None):
        captured_headers.append(headers)
        return _FakeResponse(200)

    monkeypatch.setattr("requests.get", fake_get)
    monkeypatch.setenv("S2_API_KEY", "test-key-12345")

    custom_headers = {"User-Agent": "my-app"}
    get_with_retry("http://example.com", params={}, timeout=15, headers=custom_headers)

    assert len(captured_headers) == 1
    assert captured_headers[0]["User-Agent"] == "my-app"
    assert captured_headers[0]["x-api-key"] == "test-key-12345"
    # Verify caller's dict was not mutated
    assert "x-api-key" not in custom_headers


def test_get_with_retry_does_not_set_api_key_if_not_in_env(monkeypatch):
    captured_headers = []

    def fake_get(url, params=None, timeout=None, headers=None):
        captured_headers.append(headers)
        return _FakeResponse(200)

    monkeypatch.setattr("requests.get", fake_get)
    monkeypatch.delenv("S2_API_KEY", raising=False)

    get_with_retry("http://example.com", params={}, timeout=15)

    assert len(captured_headers) == 1
    assert "x-api-key" not in captured_headers[0]


def test_get_with_retry_exponential_backoff_increases(monkeypatch):
    sleep_calls = []

    def fake_sleep(seconds):
        # Record the backoff value (without jitter for testing)
        # The actual backoff is: min(2 ** attempt, 60) + jitter
        sleep_calls.append(seconds)

    def fake_get(url, params=None, timeout=None, headers=None):
        return _FakeResponse(429)

    monkeypatch.setattr("requests.get", fake_get)
    monkeypatch.setattr("time.sleep", fake_sleep)

    try:
        get_with_retry("http://example.com", params={}, timeout=15, max_retries=4)
    except requests.exceptions.HTTPError:
        pass

    # Should have slept 3 times (retries 1, 2, 3; no sleep after final attempt)
    # Base backoffs should be 1, 2, 4 (plus jitter)
    assert len(sleep_calls) == 3
    assert all(1 <= s < 2 for s in sleep_calls[0:1])  # 1s + jitter
    assert all(2 <= s < 3 for s in sleep_calls[1:2])  # 2s + jitter
    assert all(4 <= s < 5 for s in sleep_calls[2:3])  # 4s + jitter
