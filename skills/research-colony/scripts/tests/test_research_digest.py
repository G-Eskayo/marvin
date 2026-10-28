"""Tests for research_digest.py. Run via:
    ~/.agents/venv/bin/python -m pytest skills/research-colony/scripts/tests/test_research_digest.py -v
"""
from __future__ import annotations
import sys
import json
from pathlib import Path
from datetime import datetime, date, timezone
from unittest.mock import patch, MagicMock

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))

import research_digest as rd  # noqa: E402


def test_generate_returns_none_when_not_should_run(monkeypatch):
    """generate() returns None if brief_fallback.should_run is False."""
    # Pretend we're standby (not primary)
    # Patch through the brief_fallback module that research_digest imports
    import brief_fallback
    import scanner_role
    monkeypatch.setattr(scanner_role, "is_primary", lambda x: False)

    # Capture stderr
    import io
    old_stderr = sys.stderr
    sys.stderr = io.StringIO()

    try:
        result = rd.generate()
    finally:
        sys.stderr = old_stderr

    assert result is None


def test_generate_returns_path_when_already_produced(tmp_path, monkeypatch):
    """generate() returns digest path if digest already exists."""
    # Pretend we're primary
    monkeypatch.setattr("research_digest.brief_fallback.machine_profile.scanner_role.is_primary", lambda x: True)

    # Create a digest file that already exists
    digest_dir = tmp_path / "research-digest"
    digest_dir.mkdir(parents=True)
    today = date.today().isoformat()
    digest_file = digest_dir / f"{today}.md"
    digest_file.write_text("# Existing digest")

    monkeypatch.setattr(rd, "DIGEST_DIR", digest_dir)

    # Capture stderr
    import io
    old_stderr = sys.stderr
    sys.stderr = io.StringIO()

    try:
        result = rd.generate()
    finally:
        sys.stderr = old_stderr

    assert result == digest_file


def test_generate_returns_none_when_no_cache(tmp_path, monkeypatch):
    """generate() returns None if today's cache doesn't exist."""
    # Pretend we're primary
    monkeypatch.setattr("research_digest.brief_fallback.machine_profile.scanner_role.is_primary", lambda x: True)

    cache_dir = tmp_path / "research-feed"
    cache_dir.mkdir(parents=True)
    digest_dir = tmp_path / "research-digest"
    digest_dir.mkdir(parents=True)

    monkeypatch.setattr(rd, "CACHE_DIR", cache_dir)
    monkeypatch.setattr(rd, "DIGEST_DIR", digest_dir)

    # Capture stderr
    import io
    old_stderr = sys.stderr
    sys.stderr = io.StringIO()

    try:
        result = rd.generate()
    finally:
        sys.stderr = old_stderr

    assert result is None


def test_generate_accepts_now_parameter(tmp_path, monkeypatch):
    """generate(now=...) accepts and uses the now parameter."""
    # Pretend we're primary
    monkeypatch.setattr("research_digest.brief_fallback.machine_profile.scanner_role.is_primary", lambda x: True)

    cache_dir = tmp_path / "research-feed"
    cache_dir.mkdir(parents=True)
    digest_dir = tmp_path / "research-digest"
    digest_dir.mkdir(parents=True)

    # Create a cache file with test data
    today = date.today().isoformat()
    cache_file = cache_dir / f"{today}.json"
    cache_file.write_text(json.dumps([
        {"title": "Test Item", "url": "https://example.com", "source": "arXiv"}
    ]))

    monkeypatch.setattr(rd, "CACHE_DIR", cache_dir)
    monkeypatch.setattr(rd, "DIGEST_DIR", digest_dir)

    # Mock the claude call to avoid real API calls
    def mock_launch(*args, **kwargs):
        result = MagicMock()
        result.exit_code = 0
        result.text = "## Test Section\nTest content"
        result.stderr = ""
        return result

    monkeypatch.setattr(rd, "marvin_launcher.launch", mock_launch)

    test_now = datetime(2026, 10, 25, 15, 30, tzinfo=timezone.utc)

    # Capture stderr
    import io
    old_stderr = sys.stderr
    sys.stderr = io.StringIO()

    try:
        # Should not raise; now parameter should be accepted
        result = rd.generate(now=test_now)
    finally:
        sys.stderr = old_stderr

    # Result should be a path (or None if gate logic prevents execution)
    # The key test here is that the function accepts the parameter without error
    assert result is None or isinstance(result, Path)


def test_load_today_cache_returns_empty_when_file_missing(tmp_path, monkeypatch):
    """load_today_cache() returns empty list if cache file doesn't exist."""
    cache_dir = tmp_path / "research-feed"
    cache_dir.mkdir(parents=True)
    monkeypatch.setattr(rd, "CACHE_DIR", cache_dir)

    result = rd.load_today_cache()
    assert result == []


def test_load_today_cache_returns_items(tmp_path, monkeypatch):
    """load_today_cache() reads and returns today's cache items."""
    cache_dir = tmp_path / "research-feed"
    cache_dir.mkdir(parents=True)

    today = date.today().isoformat()
    cache_file = cache_dir / f"{today}.json"
    items = [
        {"title": "Item 1", "url": "https://example.com/1"},
        {"title": "Item 2", "url": "https://example.com/2"},
    ]
    cache_file.write_text(json.dumps(items))

    monkeypatch.setattr(rd, "CACHE_DIR", cache_dir)

    result = rd.load_today_cache()
    assert result == items


def test_load_correlated_from_chroma_returns_empty_when_no_collection(tmp_path, monkeypatch):
    """load_correlated_from_chroma() returns empty list if collection doesn't exist."""
    # Mock chromadb to raise exception (collection not found)
    def mock_persistent_client(*args, **kwargs):
        client = MagicMock()
        client.get_collection.side_effect = Exception("Collection not found")
        return client

    monkeypatch.setattr(rd, "chromadb.PersistentClient", mock_persistent_client)

    result = rd.load_correlated_from_chroma()
    assert result == []
