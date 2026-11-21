#!/usr/bin/env python3
"""Tests for source_monitor.py — arXiv HTTPS connection and response parsing."""
from __future__ import annotations
from pathlib import Path
import sys
import pytest
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))

import source_monitor


class TestFetchArxiv:
    """Test arXiv fetch function."""

    def test_fetch_arxiv_uses_https_not_http(self):
        """Verify that fetch_arxiv constructs an HTTPS URL, not HTTP."""
        with patch('source_monitor.urlopen') as mock_urlopen:
            mock_response = MagicMock()
            mock_response.read.return_value = b'''<?xml version="1.0"?>
            <feed xmlns="http://www.w3.org/2005/Atom">
            </feed>'''
            mock_urlopen.return_value.__enter__.return_value = mock_response

            source_monitor.fetch_arxiv()

            # Verify urlopen was called
            assert mock_urlopen.called
            # Get the URL that was passed to urlopen
            called_url = mock_urlopen.call_args[0][0]
            # Check that it starts with https://, not http://
            assert called_url.startswith('https://export.arxiv.org/api/query')
            assert not called_url.startswith('http://export.arxiv.org')

    def test_fetch_arxiv_parses_valid_xml_response(self):
        """Test that fetch_arxiv correctly parses a valid XML response from arXiv."""
        xml_response = b'''<?xml version="1.0"?>
        <feed xmlns="http://www.w3.org/2005/Atom">
            <entry>
                <title>Test Paper Title</title>
                <summary>Test paper summary</summary>
                <id>http://arxiv.org/abs/2301.00001v1</id>
                <published>2023-01-15T12:34:56Z</published>
            </entry>
        </feed>'''

        with patch('source_monitor.urlopen') as mock_urlopen:
            mock_response = MagicMock()
            mock_response.read.return_value = xml_response
            mock_urlopen.return_value.__enter__.return_value = mock_response

            result = source_monitor.fetch_arxiv()

            assert len(result) == 1
            assert result[0]['title'] == 'Test Paper Title'
            assert result[0]['summary'] == 'Test paper summary'
            assert result[0]['source'] == 'arxiv'
            assert result[0]['url'] == 'http://arxiv.org/abs/2301.00001v1'
            assert result[0]['date'] == '2023-01-15'

    def test_fetch_arxiv_handles_network_timeout(self):
        """Test that fetch_arxiv gracefully handles network timeouts."""
        with patch('source_monitor.urlopen') as mock_urlopen:
            mock_urlopen.side_effect = TimeoutError('Connection timed out')

            result = source_monitor.fetch_arxiv()

            # Should return empty list on error
            assert result == []

    def test_fetch_arxiv_handles_connection_error(self):
        """Test that fetch_arxiv gracefully handles connection errors."""
        with patch('source_monitor.urlopen') as mock_urlopen:
            mock_urlopen.side_effect = ConnectionError('Failed to connect')

            result = source_monitor.fetch_arxiv()

            # Should return empty list on error
            assert result == []

    def test_fetch_arxiv_handles_malformed_xml(self):
        """Test that fetch_arxiv gracefully handles malformed XML responses."""
        malformed_xml = b'This is not valid XML at all'

        with patch('source_monitor.urlopen') as mock_urlopen:
            mock_response = MagicMock()
            mock_response.read.return_value = malformed_xml
            mock_urlopen.return_value.__enter__.return_value = mock_response

            result = source_monitor.fetch_arxiv()

            # Should return empty list on parsing error
            assert result == []


class TestFetchNewsletters:
    """Newsletters Gil signed up for so the colony could read them (2026-11-16) arrive as JSON files in a drop folder,
    written by whatever reads the mail (the Mail export today, MARVIN's own mailbox later)."""

    def _write(self, d, name, **item):
        import json
        base = {"title": "Top AI Demos #53", "summary": "An AI teammate that ships code.", "url": "message:%3Cabc%3E",
                "source": "newsletter:AI Tinkerers", "date": "2026-11-15", "links": ["https://example.com/demo"]}
        base.update(item)
        (d / name).write_text(json.dumps(base))

    def test_reads_drop_folder_items_into_the_colony_shape(self, tmp_path, monkeypatch):
        monkeypatch.setattr(source_monitor, "NEWSLETTER_DIR", tmp_path)
        self._write(tmp_path, "a.json")
        items = source_monitor.fetch_newsletters(today="2026-11-17")
        assert len(items) == 1
        it = items[0]
        assert it["title"] == "Top AI Demos #53" and it["source"] == "newsletter:AI Tinkerers"
        assert it["date"] == "2026-11-15" and "newsletter" in it["tags"].split(",")
        assert "https://example.com/demo" in it["summary"]      # links survive, so the digest can cite them

    def test_old_items_are_left_out(self, tmp_path, monkeypatch):
        monkeypatch.setattr(source_monitor, "NEWSLETTER_DIR", tmp_path)
        self._write(tmp_path, "old.json", date="2026-10-01", url="message:%3Cold%3E")
        self._write(tmp_path, "new.json", date="2026-11-16", url="message:%3Cnew%3E")
        assert [i["url"] for i in source_monitor.fetch_newsletters(today="2026-11-17")] == ["message:%3Cnew%3E"]

    def test_broken_or_incomplete_files_are_skipped_not_fatal(self, tmp_path, monkeypatch):
        monkeypatch.setattr(source_monitor, "NEWSLETTER_DIR", tmp_path)
        (tmp_path / "junk.json").write_text("{not json")
        self._write(tmp_path, "notitle.json", title="", url="message:%3Cx%3E")
        self._write(tmp_path, "ok.json", url="message:%3Cok%3E")
        (tmp_path / "readme.txt").write_text("ignored")
        assert [i["url"] for i in source_monitor.fetch_newsletters(today="2026-11-17")] == ["message:%3Cok%3E"]

    def test_a_missing_folder_means_no_items(self, tmp_path, monkeypatch):
        monkeypatch.setattr(source_monitor, "NEWSLETTER_DIR", tmp_path / "nope")
        assert source_monitor.fetch_newsletters(today="2026-11-17") == []

    def test_long_newsletters_are_trimmed(self, tmp_path, monkeypatch):
        monkeypatch.setattr(source_monitor, "NEWSLETTER_DIR", tmp_path)
        self._write(tmp_path, "long.json", summary="x" * 50_000)
        assert len(source_monitor.fetch_newsletters(today="2026-11-17")[0]["summary"]) <= source_monitor.NEWSLETTER_MAX_CHARS

    def test_main_includes_newsletters(self, monkeypatch):
        seen = {}
        monkeypatch.setattr(source_monitor, "fetch_arxiv", lambda: [])
        monkeypatch.setattr(source_monitor, "fetch_github", lambda: [])
        monkeypatch.setattr(source_monitor, "fetch_hackernews", lambda: [])
        monkeypatch.setattr(source_monitor, "fetch_newsletters", lambda: [{"title": "t", "summary": "s", "url": "u",
                            "source": "newsletter:x", "date": "2026-11-17", "tags": "newsletter"}])
        monkeypatch.setattr(source_monitor, "save_raw_cache", lambda items: seen.setdefault("items", items))
        monkeypatch.setattr(source_monitor, "store_items", lambda items: len(items))
        source_monitor.main()
        assert [i["source"] for i in seen["items"]] == ["newsletter:x"]
