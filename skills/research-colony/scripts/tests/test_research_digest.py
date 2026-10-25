"""Tests for research_digest.py's generation and TOCTOU safety. Run via:
    ~/.agents/venv/bin/python -m pytest skills/research-colony/scripts/tests/test_research_digest.py -v
"""
from __future__ import annotations
import sys
from pathlib import Path
from datetime import date
from unittest.mock import patch, MagicMock

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))

import research_digest as rd  # noqa: E402


def test_generate_toctou_produced_recheck(tmp_path, monkeypatch):
    """TOCTOU test: produced() is called before write, and again right before the final write.
    If produced() returns True on the second check, generate() should not overwrite the file."""
    monkeypatch.setattr(rd, "DIGEST_DIR", tmp_path)
    today = date.today().isoformat()
    out_file = tmp_path / f"{today}.md"

    # Simulate: first produced() says not yet made, so we proceed
    # But before we write, something else creates it
    # Then the pre-write produced() check should catch it

    call_count = [0]
    original_produced = rd.brief_fallback.produced

    def produced_mock(local_path, *args, **kwargs):
        call_count[0] += 1
        if call_count[0] == 1:
            # First call: file doesn't exist yet, so return False (proceed to build)
            return False
        else:
            # Subsequent calls: file now exists, return True (skip the write)
            return out_file.exists() and out_file.read_text().strip() != ""

    # Setup mocks
    monkeypatch.setattr(rd.brief_fallback, "produced", produced_mock)

    # Mock load functions
    monkeypatch.setattr(rd, "load_today_cache", lambda: [{"title": "Test", "url": "http://test", "source": "test"}])
    monkeypatch.setattr(rd, "load_correlated_from_chroma", lambda: [])

    # Mock the marvin_launcher call
    mock_result = MagicMock()
    mock_result.exit_code = 0
    mock_result.text = "## Test Digest\nContent here"
    mock_result.stderr = ""
    monkeypatch.setattr(rd.marvin_launcher, "launch", lambda *args, **kwargs: mock_result)

    # Mock safety check
    monkeypatch.setattr(rd, "_SAFETY_MONITOR_AVAILABLE", False)

    # First call: file doesn't exist, so generate should proceed
    result1 = rd.generate()
    assert result1 is not None
    assert out_file.exists()
    original_content = out_file.read_text()

    # Reset call count, simulate second run
    call_count[0] = 0

    # Second call: file now exists, produced() mock will return True on second check
    result2 = rd.generate()
    # Since file exists and produced() says True, result should point to existing file, not overwrite
    assert result2 == out_file
    # Content should match what was written before (not overwritten by a fresh call)
    assert out_file.read_text() == original_content


def test_generate_empty_cache_returns_none(tmp_path, monkeypatch):
    """generate() returns None when there are no items in today's cache."""
    monkeypatch.setattr(rd, "DIGEST_DIR", tmp_path)
    monkeypatch.setattr(rd, "load_today_cache", lambda: [])

    result = rd.generate()
    assert result is None


def test_generate_claude_call_failed(tmp_path, monkeypatch, capsys):
    """generate() returns None and prints error when the claude call fails."""
    monkeypatch.setattr(rd, "DIGEST_DIR", tmp_path)
    monkeypatch.setattr(rd, "load_today_cache", lambda: [{"title": "Test", "url": "http://test", "source": "test"}])
    monkeypatch.setattr(rd, "load_correlated_from_chroma", lambda: [])

    # Mock a failed launch
    def mock_launch(*args, **kwargs):
        raise Exception("Connection timeout")

    monkeypatch.setattr(rd.marvin_launcher, "launch", mock_launch)

    result = rd.generate()
    assert result is None
    captured = capsys.readouterr()
    assert "claude call failed" in captured.err.lower()


def test_generate_safety_monitor_quarantine(tmp_path, monkeypatch):
    """generate() quarantines the digest if safety-monitor flags it."""
    monkeypatch.setattr(rd, "DIGEST_DIR", tmp_path)
    monkeypatch.setattr(rd, "load_today_cache", lambda: [{"title": "Test", "url": "http://test", "source": "test"}])
    monkeypatch.setattr(rd, "load_correlated_from_chroma", lambda: [])

    # Mock successful claude call
    mock_result = MagicMock()
    mock_result.exit_code = 0
    mock_result.text = "## Risky Digest\nDangerous content"
    mock_result.stderr = ""
    monkeypatch.setattr(rd.marvin_launcher, "launch", lambda *args, **kwargs: mock_result)

    # Mock safety-monitor as available and flagging the digest
    monkeypatch.setattr(rd, "_SAFETY_MONITOR_AVAILABLE", True)

    def mock_quarantine(body, **kwargs):
        return False  # Returns False = flagged/quarantined

    monkeypatch.setattr(rd, "pass_or_quarantine", mock_quarantine)
    monkeypatch.setattr(rd, "notify", MagicMock())

    today = date.today().isoformat()
    out_path = rd.DIGEST_DIR / f"{today}.md"

    result = rd.generate()

    # File should exist with quarantine marker
    assert result == out_path
    content = out_path.read_text()
    assert "_Quarantined by safety-monitor" in content
