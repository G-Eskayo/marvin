"""Tests for research-colony scripts. Run via:
    ~/.agents/venv/bin/python -m pytest skills/research-colony/scripts/tests/test_colony.py -v
"""
from __future__ import annotations
import json
import sys
import tempfile
from datetime import date
from pathlib import Path

import pytest

# resolve scripts/ on path
SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))

from correlate import roadmap_match
from research_digest import load_today_cache


# ── correlate.roadmap_match ──────────────────────────────────────────────────

def test_roadmap_match_single_keyword():
    """roadmap_match returns the section label for a matched keyword."""
    result = roadmap_match("quantization is important")
    assert result == "A.quantization"


def test_roadmap_match_multiple_keywords():
    """roadmap_match returns all matched sections sorted."""
    result = roadmap_match("using rag and vector db for retrieval")
    sections = result.split(", ")
    assert "A.rag" in sections
    assert "C.vector-db" in sections
    # Verify sorted order
    assert result == ", ".join(sorted(sections))


def test_roadmap_match_case_insensitive():
    """roadmap_match is case-insensitive."""
    result_lower = roadmap_match("quantization")
    result_upper = roadmap_match("QUANTIZATION")
    result_mixed = roadmap_match("QuAnTiZaTioN")
    assert result_lower == result_upper == result_mixed == "A.quantization"


def test_roadmap_match_no_match():
    """roadmap_match returns empty string when no keywords match."""
    result = roadmap_match("some random text about cats and dogs")
    assert result == ""


def test_roadmap_match_partial_keyword_match():
    """roadmap_match matches substring keywords (e.g., 'fine-tun' matches 'fine-tuning')."""
    result = roadmap_match("fine-tuning is a technique")
    assert "G.fine-tuning" in result


def test_roadmap_match_exact_vs_substring():
    """roadmap_match works with both exact and substring matches."""
    # "code review" is an exact keyword
    result1 = roadmap_match("code review automation")
    assert "B.code-review" in result1
    # " mcp " (with spaces) is a keyword to avoid false matches
    result2 = roadmap_match("model context protocol (mcp) integration")
    assert "B.mcp" in result2


def test_roadmap_match_sorted_order():
    """roadmap_match returns multiple matches in sorted order."""
    # Intentionally use keywords that won't naturally sort
    result = roadmap_match("tool use with rag and quantization")
    sections = result.split(", ")
    # Check they are sorted
    assert sections == sorted(sections)


# ── research_digest.load_today_cache ─────────────────────────────────────────

def test_load_today_cache_valid_json():
    """load_today_cache returns parsed JSON from today's cache file."""
    with tempfile.TemporaryDirectory() as tmpdir:
        cache_dir = Path(tmpdir)
        today = date.today().isoformat()
        cache_file = cache_dir / f"{today}.json"

        test_data = [
            {"title": "Test 1", "url": "http://example.com"},
            {"title": "Test 2", "url": "http://example.org"},
        ]
        cache_file.write_text(json.dumps(test_data))

        # Monkey-patch CACHE_DIR in research_digest module
        import research_digest
        original_cache_dir = research_digest.CACHE_DIR
        try:
            research_digest.CACHE_DIR = cache_dir
            result = load_today_cache()
            assert result == test_data
            assert len(result) == 2
        finally:
            research_digest.CACHE_DIR = original_cache_dir


def test_load_today_cache_missing_file():
    """load_today_cache returns empty list when cache file doesn't exist."""
    with tempfile.TemporaryDirectory() as tmpdir:
        cache_dir = Path(tmpdir)

        import research_digest
        original_cache_dir = research_digest.CACHE_DIR
        try:
            research_digest.CACHE_DIR = cache_dir
            result = load_today_cache()
            assert result == []
        finally:
            research_digest.CACHE_DIR = original_cache_dir


def test_load_today_cache_corrupted_json():
    """load_today_cache returns empty list on JSON parse error."""
    with tempfile.TemporaryDirectory() as tmpdir:
        cache_dir = Path(tmpdir)
        today = date.today().isoformat()
        cache_file = cache_dir / f"{today}.json"

        # Write invalid JSON
        cache_file.write_text("{ this is not valid json }")

        import research_digest
        original_cache_dir = research_digest.CACHE_DIR
        try:
            research_digest.CACHE_DIR = cache_dir
            result = load_today_cache()
            assert result == []
        finally:
            research_digest.CACHE_DIR = original_cache_dir
