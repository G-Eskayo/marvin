"""Tests for paper-dive's fetch_related module. Run via:
    ~/.agents/venv/bin/python -m pytest skills/paper-dive/scripts/tests/test_fetch_related.py -v
"""
from __future__ import annotations
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))

import pytest

from fetch_related import (
    s2_paper_by_doi,
    s2_search,
    s2_recommendations,
    failures,
)


class _FakeResponse:
    """Fake HTTP response object for mocking requests."""
    def __init__(self, payload: dict, status_code: int = 200):
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise Exception(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


# ── s2_paper_by_doi ─────────────────────────────────────────────────────────

def test_s2_paper_by_doi_success(monkeypatch):
    """s2_paper_by_doi returns paper dict on successful lookup."""
    s2_payload = {
        "paperId": "12345",
        "title": "Test Paper",
        "authors": [{"name": "Author One"}],
        "year": 2024,
        "abstract": "A test abstract",
    }

    def fake_get_with_retry(url, params, timeout):
        return _FakeResponse(s2_payload)

    monkeypatch.setattr("fetch_related.get_with_retry", fake_get_with_retry)
    failures.clear()

    result = s2_paper_by_doi("10.1234/example")

    assert result == s2_payload
    assert failures == []


def test_s2_paper_by_doi_request_exception(monkeypatch):
    """s2_paper_by_doi catches RequestException and records failure."""
    def fake_get_with_retry(url, params, timeout):
        import requests
        raise requests.RequestException("Network error")

    monkeypatch.setattr("fetch_related.get_with_retry", fake_get_with_retry)
    failures.clear()

    result = s2_paper_by_doi("10.1234/example")

    assert result is None
    assert len(failures) == 1
    assert failures[0][0] == "DOI lookup"
    assert "Network error" in failures[0][1]


def test_s2_paper_by_doi_json_decode_error(monkeypatch):
    """s2_paper_by_doi catches JSON decode errors and records failure."""
    def fake_get_with_retry(url, params, timeout):
        resp = _FakeResponse({})
        resp.json = lambda: (_ for _ in ()).throw(ValueError("Invalid JSON"))
        return resp

    monkeypatch.setattr("fetch_related.get_with_retry", fake_get_with_retry)
    failures.clear()

    result = s2_paper_by_doi("10.1234/example")

    assert result is None
    assert len(failures) == 1
    assert failures[0][0] == "DOI lookup"
    assert "JSON decode error" in failures[0][1]


def test_s2_paper_by_doi_http_error(monkeypatch):
    """s2_paper_by_doi catches HTTP errors from get_with_retry."""
    def fake_get_with_retry(url, params, timeout):
        import requests
        raise requests.RequestException("HTTP 404")

    monkeypatch.setattr("fetch_related.get_with_retry", fake_get_with_retry)
    failures.clear()

    result = s2_paper_by_doi("10.1234/example")

    assert result is None
    assert len(failures) == 1
    assert failures[0][0] == "DOI lookup"
    assert "HTTP 404" in failures[0][1]


# ── s2_search ────────────────────────────────────────────────────────────────

def test_s2_search_success(monkeypatch):
    """s2_search returns search results on successful query."""
    s2_payload = {
        "data": [
            {"title": "Paper A", "externalIds": {"DOI": "10.1/a"}},
            {"title": "Paper B", "externalIds": {"DOI": "10.1/b"}},
        ]
    }

    def fake_get_with_retry(url, params, timeout):
        return _FakeResponse(s2_payload)

    monkeypatch.setattr("fetch_related.get_with_retry", fake_get_with_retry)
    failures.clear()

    result = s2_search("attention mechanism", limit=10)

    assert len(result) == 2
    assert result[0]["title"] == "Paper A"
    assert failures == []


def test_s2_search_empty_results(monkeypatch):
    """s2_search returns empty list when no results found."""
    def fake_get_with_retry(url, params, timeout):
        return _FakeResponse({"data": []})

    monkeypatch.setattr("fetch_related.get_with_retry", fake_get_with_retry)
    failures.clear()

    result = s2_search("nonexistent query")

    assert result == []
    assert failures == []


def test_s2_search_request_exception(monkeypatch):
    """s2_search catches RequestException and records failure."""
    def fake_get_with_retry(url, params, timeout):
        import requests
        raise requests.RequestException("Connection timeout")

    monkeypatch.setattr("fetch_related.get_with_retry", fake_get_with_retry)
    failures.clear()

    result = s2_search("test query")

    assert result == []
    assert len(failures) == 1
    assert failures[0][0] == "search"
    assert "Connection timeout" in failures[0][1]


def test_s2_search_json_decode_error(monkeypatch):
    """s2_search catches JSON decode errors and records failure."""
    def fake_get_with_retry(url, params, timeout):
        resp = _FakeResponse({})
        resp.json = lambda: (_ for _ in ()).throw(KeyError("data"))
        return resp

    monkeypatch.setattr("fetch_related.get_with_retry", fake_get_with_retry)
    failures.clear()

    result = s2_search("test query")

    assert result == []
    assert len(failures) == 1
    assert failures[0][0] == "search"
    assert "JSON decode error" in failures[0][1]


def test_s2_search_handles_missing_data_key(monkeypatch):
    """s2_search gracefully handles response without 'data' key."""
    def fake_get_with_retry(url, params, timeout):
        return _FakeResponse({})

    monkeypatch.setattr("fetch_related.get_with_retry", fake_get_with_retry)
    failures.clear()

    result = s2_search("test query")

    assert result == []
    assert failures == []


# ── s2_recommendations ───────────────────────────────────────────────────────

def test_s2_recommendations_success(monkeypatch):
    """s2_recommendations returns recommendations on successful POST."""
    s2_payload = {
        "recommendedPapers": [
            {"title": "Related Paper 1", "externalIds": {"DOI": "10.1/r1"}},
            {"title": "Related Paper 2", "externalIds": {"DOI": "10.1/r2"}},
        ]
    }

    def fake_post(url, json=None, params=None, timeout=None):
        return _FakeResponse(s2_payload)

    import requests
    monkeypatch.setattr("requests.post", fake_post)
    failures.clear()

    result = s2_recommendations("corpus-12345", limit=10)

    assert len(result) == 2
    assert result[0]["title"] == "Related Paper 1"
    assert failures == []


def test_s2_recommendations_empty(monkeypatch):
    """s2_recommendations returns empty list when no recommendations."""
    def fake_post(url, json=None, params=None, timeout=None):
        return _FakeResponse({"recommendedPapers": []})

    import requests
    monkeypatch.setattr("requests.post", fake_post)
    failures.clear()

    result = s2_recommendations("corpus-12345")

    assert result == []
    assert failures == []


def test_s2_recommendations_http_error(monkeypatch):
    """s2_recommendations records failure on non-200 status."""
    def fake_post(url, json=None, params=None, timeout=None):
        return _FakeResponse({}, status_code=429)

    import requests
    monkeypatch.setattr("requests.post", fake_post)
    failures.clear()

    result = s2_recommendations("corpus-12345")

    assert result == []
    assert len(failures) == 1
    assert failures[0][0] == "recommendations"
    assert "HTTP 429" in failures[0][1]


def test_s2_recommendations_request_exception(monkeypatch):
    """s2_recommendations catches RequestException and records failure."""
    def fake_post(url, json=None, params=None, timeout=None):
        import requests
        raise requests.RequestException("POST failed")

    import requests
    monkeypatch.setattr("requests.post", fake_post)
    failures.clear()

    result = s2_recommendations("corpus-12345")

    assert result == []
    assert len(failures) == 1
    assert failures[0][0] == "recommendations"
    assert "POST failed" in failures[0][1]


def test_s2_recommendations_json_decode_error(monkeypatch):
    """s2_recommendations catches JSON decode errors and records failure."""
    def fake_post(url, json=None, params=None, timeout=None):
        resp = _FakeResponse({})
        resp.json = lambda: (_ for _ in ()).throw(TypeError("JSON type error"))
        return resp

    import requests
    monkeypatch.setattr("requests.post", fake_post)
    failures.clear()

    result = s2_recommendations("corpus-12345")

    assert result == []
    assert len(failures) == 1
    assert failures[0][0] == "recommendations"
    assert "JSON decode error" in failures[0][1]


def test_s2_recommendations_handles_missing_recommendedPapers_key(monkeypatch):
    """s2_recommendations gracefully handles response without 'recommendedPapers' key."""
    def fake_post(url, json=None, params=None, timeout=None):
        return _FakeResponse({})

    import requests
    monkeypatch.setattr("requests.post", fake_post)
    failures.clear()

    result = s2_recommendations("corpus-12345")

    assert result == []
    assert failures == []


# ── Module-level failures list ───────────────────────────────────────────────

def test_failures_list_accumulates_across_calls(monkeypatch):
    """Failures accumulate across multiple function calls via actual error paths."""
    failures.clear()

    # First failure: DOI lookup fails
    def fake_get_doi(url, params, timeout):
        import requests
        raise requests.RequestException("Network error")

    monkeypatch.setattr("fetch_related.get_with_retry", fake_get_doi)
    result = s2_paper_by_doi("10.1234/example")
    assert result is None
    assert len(failures) == 1
    assert failures[0] == ("DOI lookup", "Network error")

    # Second failure: search fails
    def fake_get_search(url, params, timeout):
        import requests
        raise requests.RequestException("Search timeout")

    monkeypatch.setattr("fetch_related.get_with_retry", fake_get_search)
    result = s2_search("test query")
    assert result == []
    assert len(failures) == 2
    assert failures[1] == ("search", "Search timeout")

    # Third failure: recommendations fails
    def fake_post(url, json=None, params=None, timeout=None):
        import requests
        raise requests.RequestException("POST failed")

    monkeypatch.setattr("requests.post", fake_post)
    result = s2_recommendations("paper-id")
    assert result == []
    assert len(failures) == 3
    assert failures[2] == ("recommendations", "POST failed")


def test_failures_list_can_be_cleared(monkeypatch):
    """Failures list can be cleared and fresh failures accumulate correctly."""
    # Ensure clean state
    failures.clear()

    # Generate initial failures
    def fake_get_error(url, params, timeout):
        import requests
        raise requests.RequestException("First batch error")

    monkeypatch.setattr("fetch_related.get_with_retry", fake_get_error)
    s2_paper_by_doi("10.1234/test1")
    s2_search("test1")
    assert len(failures) == 2

    # Clear and verify
    failures.clear()
    assert len(failures) == 0

    # Add new failures after clearing
    s2_paper_by_doi("10.1234/test2")
    assert len(failures) == 1
    assert failures[0] == ("DOI lookup", "First batch error")


# ── Warning message logic ────────────────────────────────────────────────────

def test_warning_message_arxiv_only_when_no_s2_results(monkeypatch, capsys):
    """Warning says 'arXiv-only' when only arXiv papers are in ranked results."""
    from fetch_related import main
    import sys

    def fake_get_with_retry(url, params=None, timeout=None):
        # Both DOI lookup and search fail
        import requests
        raise requests.RequestException("S2 API down")

    def fake_post(url, json=None, params=None, timeout=None):
        # Recommendations fail
        import requests
        raise requests.RequestException("S2 API down")

    def fake_arxiv_get(url, params=None, timeout=None):
        # arXiv returns results with proper Atom namespace and feed structure
        resp = _FakeResponse({})
        resp.text = '''<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <title>arXiv Paper</title>
    <summary>Summary of the paper</summary>
    <id>http://arxiv.org/abs/2024.00001v1</id>
    <published>2024-01-01T00:00:00Z</published>
  </entry>
</feed>'''
        return resp

    monkeypatch.setattr("fetch_related.get_with_retry", fake_get_with_retry)
    monkeypatch.setattr("requests.post", fake_post)
    import requests
    monkeypatch.setattr("requests.get", fake_arxiv_get)

    # Run main with title (no DOI to avoid DOI lookup)
    sys.argv = ["fetch_related.py", "--title", "test paper"]
    main()

    captured = capsys.readouterr()
    assert "arXiv-only" in captured.out
    assert "Issues with Semantic Scholar" not in captured.out


def test_arxiv_search_parses_proper_xml_format(monkeypatch):
    """arXiv search correctly parses well-formed Atom XML with proper namespace."""
    from fetch_related import arxiv_search

    def fake_arxiv_get(url, params=None, timeout=None):
        resp = _FakeResponse({})
        resp.text = '''<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <title>Attention Is All You Need</title>
    <summary>We propose a new architecture called Transformer</summary>
    <id>http://arxiv.org/abs/1706.03762v5</id>
    <published>2017-06-12T17:58:41Z</published>
  </entry>
  <entry>
    <title>BERT: Pre-training of Deep Bidirectional Transformers</title>
    <summary>We introduce BERT, a new language representation model</summary>
    <id>http://arxiv.org/abs/1810.04805v2</id>
    <published>2018-10-11T17:46:01Z</published>
  </entry>
</feed>'''
        return resp

    import requests
    monkeypatch.setattr("requests.get", fake_arxiv_get)

    results = arxiv_search("transformer", max_results=5)

    assert len(results) == 2
    assert results[0]["title"] == "Attention Is All You Need"
    assert results[0]["source"] == "arXiv"
    assert "1706.03762" in results[0]["url"]
    assert results[1]["title"] == "BERT: Pre-training of Deep Bidirectional Transformers"
    assert results[1]["year"] == "2018"


def test_warning_message_partial_failure_with_s2_results(monkeypatch, capsys):
    """Warning indicates partial failure when S2 results exist despite some failures."""
    from fetch_related import main
    import sys

    # Clean state
    failures.clear()

    def fake_get_with_retry(url, params=None, timeout=None):
        # DOI lookup fails, search succeeds
        if "/search" in url:
            return _FakeResponse({
                "data": [
                    {"title": "S2 Paper", "paperId": "123", "externalIds": {"DOI": "10.1/test"}}
                ]
            })
        else:
            # DOI lookup or other endpoint fails
            import requests
            raise requests.RequestException("Network error")

    def fake_post(url, json=None, params=None, timeout=None):
        # Recommendations fail
        import requests
        raise requests.RequestException("Service unavailable")

    def fake_arxiv_get(url, params=None, timeout=None):
        # arXiv returns no results
        resp = _FakeResponse({})
        resp.text = ''
        return resp

    monkeypatch.setattr("fetch_related.get_with_retry", fake_get_with_retry)
    monkeypatch.setattr("requests.post", fake_post)
    import requests
    monkeypatch.setattr("requests.get", fake_arxiv_get)

    # Run main with title and DOI
    sys.argv = ["fetch_related.py", "--doi", "10.1234/example", "--title", "test"]
    main()

    captured = capsys.readouterr()
    assert "Issues with Semantic Scholar" in captured.out
    assert "some services unavailable" in captured.out
    assert "arXiv-only" not in captured.out
