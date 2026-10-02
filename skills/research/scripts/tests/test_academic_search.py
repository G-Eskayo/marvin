"""Tests for academic_search module. Run via:
    ~/.agents/venv/bin/python -m pytest skills/research/scripts/tests/test_academic_search.py -v
"""
import json
import sys
from pathlib import Path
from unittest.mock import patch
import importlib

import pytest

# Add lib and scripts to path (order matters: lib first for s2_client)
LIB = Path.home() / ".agents" / "lib"
sys.path.insert(0, str(LIB))

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))

from academic_search import search_semantic_scholar, search_arxiv, main

# Import s2_client after path is set up
import s2_client


# ── search_semantic_scholar ──────────────────────────────────────────────────

def test_search_semantic_scholar_returns_papers(monkeypatch):
    s2_response = {
        "data": [
            {
                "paperId": "123abc",
                "title": "A Foundational Paper",
                "authors": [{"name": "Alice"}],
                "year": 2024,
                "abstract": "This paper explores...",
                "citationCount": 42,
                "url": "https://semanticscholar.org/paper/123abc",
            }
        ]
    }

    class FakeResponse:
        status_code = 200

        def json(self):
            return s2_response

        def raise_for_status(self):
            pass

    def fake_get_with_retry(url, params, timeout, max_retries=8, headers=None):
        return FakeResponse()

    monkeypatch.setattr(s2_client, "get_with_retry", fake_get_with_retry)

    results = search_semantic_scholar("machine learning", limit=10)

    assert len(results) == 1
    assert results[0]["title"] == "A Foundational Paper"
    assert results[0]["authors"][0]["name"] == "Alice"


def test_search_semantic_scholar_routes_through_get_with_retry(monkeypatch):
    called = []

    def fake_get_with_retry(url, params, timeout, max_retries=8, headers=None):
        called.append((url, params, timeout))

        class FakeResponse:
            status_code = 200

            def json(self):
                return {"data": []}

            def raise_for_status(self):
                pass

        return FakeResponse()

    monkeypatch.setattr(s2_client, "get_with_retry", fake_get_with_retry)

    search_semantic_scholar("test query")

    assert len(called) == 1
    url, params, timeout = called[0]
    assert "/graph/v1/paper/search" in url
    assert params["query"] == "test query"
    assert timeout == 15


def test_search_semantic_scholar_returns_empty_on_error(monkeypatch, capsys):
    def fake_get_with_retry(url, params, timeout, max_retries=8, headers=None):
        raise Exception("Network error")

    monkeypatch.setattr(s2_client, "get_with_retry", fake_get_with_retry)

    results = search_semantic_scholar("test")

    assert results == []
    captured = capsys.readouterr()
    assert "Semantic Scholar search failed" in captured.err


def test_search_semantic_scholar_extracts_correct_fields(monkeypatch):
    s2_response = {
        "data": [
            {
                "paperId": "456def",
                "title": "Another Paper",
                "authors": [{"name": "Bob"}, {"name": "Charlie"}],
                "year": 2023,
                "abstract": "This paper is about...",
                "citationCount": 100,
                "externalIds": {"DOI": "10.1234/example", "ArXiv": "2301.00001"},
                "openAccessPdf": {"url": "https://example.com/paper.pdf"},
                "url": "https://semanticscholar.org/paper/456def",
            }
        ]
    }

    class FakeResponse:
        status_code = 200

        def json(self):
            return s2_response

        def raise_for_status(self):
            pass

    import s2_client
    monkeypatch.setattr(
        s2_client, "get_with_retry",
        lambda url, params, timeout, max_retries=8, headers=None: FakeResponse(),
    )

    results = search_semantic_scholar("test")

    assert len(results) == 1
    paper = results[0]
    assert paper["title"] == "Another Paper"
    assert len(paper["authors"]) == 2
    assert paper["year"] == 2023


# ── search_arxiv ────────────────────────────────────────────────────────────

def test_search_arxiv_returns_papers(monkeypatch):
    arxiv_atom = """<?xml version="1.0" encoding="UTF-8"?>
    <feed xmlns="http://www.w3.org/2005/Atom">
      <entry>
        <id>http://arxiv.org/abs/2301.00001v1</id>
        <title>A Test arXiv Paper</title>
        <author><name>Alice Author</name></author>
        <published>2023-01-01T00:00:00Z</published>
        <summary>This paper discusses something important.</summary>
      </entry>
    </feed>"""

    class FakeResponse:
        status_code = 200
        text = arxiv_atom
        encoding = "utf-8"

        def raise_for_status(self):
            pass

    def fake_get_with_retry(url, params, timeout, max_retries=8, headers=None):
        return FakeResponse()

    monkeypatch.setattr(s2_client, "get_with_retry", fake_get_with_retry)

    results = search_arxiv("quantum computing")

    assert len(results) == 1
    paper = results[0]
    assert paper["title"] == "A Test arXiv Paper"
    assert paper["arxiv_id"] == "2301.00001v1"
    assert paper["authors"][0]["name"] == "Alice Author"
    assert paper["year"] == 2023


def test_search_arxiv_routes_through_get_with_retry(monkeypatch):
    called = []

    arxiv_atom = """<?xml version="1.0" encoding="UTF-8"?>
    <feed xmlns="http://www.w3.org/2005/Atom">
    </feed>"""

    class FakeResponse:
        status_code = 200
        text = arxiv_atom
        encoding = "utf-8"

        def raise_for_status(self):
            pass

    def fake_get_with_retry(url, params, timeout, max_retries=8, headers=None):
        called.append((url, params, timeout))
        return FakeResponse()

    monkeypatch.setattr(s2_client, "get_with_retry", fake_get_with_retry)

    search_arxiv("test query", max_results=20)

    assert len(called) == 1
    url, params, timeout = called[0]
    assert "export.arxiv.org" in url
    assert "all:test query" in params["search_query"]
    assert params["max_results"] == 20
    assert timeout == 15


def test_search_arxiv_returns_empty_on_error(monkeypatch, capsys):
    def fake_get_with_retry(url, params, timeout, max_retries=8, headers=None):
        raise Exception("Network error")

    monkeypatch.setattr(s2_client, "get_with_retry", fake_get_with_retry)

    results = search_arxiv("test")

    assert results == []
    captured = capsys.readouterr()
    assert "arXiv search failed" in captured.err


def test_search_arxiv_handles_multiple_authors(monkeypatch):
    arxiv_atom = """<?xml version="1.0" encoding="UTF-8"?>
    <feed xmlns="http://www.w3.org/2005/Atom">
      <entry>
        <id>http://arxiv.org/abs/2305.00001v1</id>
        <title>Multi-Author Paper</title>
        <author><name>Alice</name></author>
        <author><name>Bob</name></author>
        <author><name>Charlie</name></author>
        <published>2023-05-01T00:00:00Z</published>
        <summary>A collaborative effort.</summary>
      </entry>
    </feed>"""

    class FakeResponse:
        status_code = 200
        text = arxiv_atom
        encoding = "utf-8"

        def raise_for_status(self):
            pass

    import s2_client
    monkeypatch.setattr(
        s2_client, "get_with_retry",
        lambda url, params, timeout, max_retries=8, headers=None: FakeResponse(),
    )

    results = search_arxiv("test")

    assert len(results) == 1
    assert len(results[0]["authors"]) == 3
    assert results[0]["authors"][0]["name"] == "Alice"
    assert results[0]["authors"][1]["name"] == "Bob"
    assert results[0]["authors"][2]["name"] == "Charlie"


def test_search_arxiv_handles_missing_year(monkeypatch):
    arxiv_atom = """<?xml version="1.0" encoding="UTF-8"?>
    <feed xmlns="http://www.w3.org/2005/Atom">
      <entry>
        <id>http://arxiv.org/abs/2301.00001v1</id>
        <title>No Date Paper</title>
        <author><name>Alice</name></author>
        <summary>This has no date.</summary>
      </entry>
    </feed>"""

    class FakeResponse:
        status_code = 200
        text = arxiv_atom
        encoding = "utf-8"

        def raise_for_status(self):
            pass

    import s2_client
    monkeypatch.setattr(
        s2_client, "get_with_retry",
        lambda url, params, timeout, max_retries=8, headers=None: FakeResponse(),
    )

    results = search_arxiv("test")

    assert len(results) == 1
    assert results[0]["year"] is None


# ── Integration tests ────────────────────────────────────────────────────────

def test_main_json_output_semantic_scholar_only(monkeypatch, capsys):
    s2_response = {"data": [{"title": "S2 Paper", "authors": []}]}

    class FakeSS:
        status_code = 200

        def json(self):
            return s2_response

        def raise_for_status(self):
            pass

    def fake_get_with_retry(url, params, timeout, max_retries=8, headers=None):
        if "export.arxiv.org" in url:
            raise Exception("arXiv down")
        return FakeSS()

    monkeypatch.setattr(s2_client, "get_with_retry", fake_get_with_retry)

    with patch.object(sys, "argv", ["academic_search.py", "--query", "test", "--source", "semantic-scholar", "--format", "json"]):
        main()

    captured = capsys.readouterr()
    output = json.loads(captured.out)
    assert "semantic_scholar" in output
    assert len(output["semantic_scholar"]) == 1
    assert output["semantic_scholar"][0]["title"] == "S2 Paper"


def test_main_json_output_both_sources(monkeypatch, capsys):
    s2_response = {"data": [{"title": "S2 Paper", "authors": []}]}
    arxiv_atom = """<?xml version="1.0" encoding="UTF-8"?>
    <feed xmlns="http://www.w3.org/2005/Atom">
      <entry>
        <id>http://arxiv.org/abs/2301.00001v1</id>
        <title>arXiv Paper</title>
        <author><name>Alice</name></author>
        <published>2023-01-01T00:00:00Z</published>
        <summary>Test.</summary>
      </entry>
    </feed>"""

    class FakeResponse:
        status_code = 200

        def __init__(self, is_arxiv):
            self.is_arxiv = is_arxiv

        def json(self):
            return s2_response

        @property
        def text(self):
            return arxiv_atom

        encoding = "utf-8"

        def raise_for_status(self):
            pass

    def fake_get_with_retry(url, params, timeout, max_retries=8, headers=None):
        is_arxiv = "export.arxiv.org" in url
        return FakeResponse(is_arxiv)

    monkeypatch.setattr(s2_client, "get_with_retry", fake_get_with_retry)

    with patch.object(sys, "argv", ["academic_search.py", "--query", "test", "--format", "json"]):
        main()

    captured = capsys.readouterr()
    output = json.loads(captured.out)
    assert "semantic_scholar" in output
    assert "arxiv" in output
    assert len(output["semantic_scholar"]) == 1
    assert len(output["arxiv"]) == 1


def test_main_graceful_degradation_when_one_source_fails(monkeypatch, capsys):
    s2_response = {"data": [{"title": "S2 Paper", "authors": []}]}

    class FakeResponse:
        status_code = 200

        def json(self):
            return s2_response

        def raise_for_status(self):
            pass

    def fake_get_with_retry(url, params, timeout, max_retries=8, headers=None):
        if "export.arxiv.org" in url:
            raise Exception("arXiv network error")
        return FakeResponse()

    monkeypatch.setattr(s2_client, "get_with_retry", fake_get_with_retry)

    with patch.object(sys, "argv", ["academic_search.py", "--query", "test", "--format", "json"]):
        main()

    captured = capsys.readouterr()
    # Should still have valid JSON with semantic_scholar data and empty arxiv
    output = json.loads(captured.out)
    assert "semantic_scholar" in output
    assert "arxiv" in output
    assert len(output["semantic_scholar"]) == 1
    assert not output["arxiv"]
    # Error should be on stderr
    assert "arXiv search failed" in captured.err
