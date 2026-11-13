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
