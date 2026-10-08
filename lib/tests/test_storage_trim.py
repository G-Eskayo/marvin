"""Tests for storage_trim.py. Run via:
    ~/.agents/venv/bin/python -m pytest lib/tests/test_storage_trim.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

LIB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LIB))

import storage_trim as st  # noqa: E402


def test_never_trim_ms_playwright():
    """Test that ms-playwright is in NEVER_TRIM."""
    home = Path.home()
    ms_playwright = home / "Library" / "Caches" / "ms-playwright"
    assert st._should_never_trim(ms_playwright)


def test_trim_candidates_never_includes_never_trim():
    """Test that paths in NEVER_TRIM are never in candidates."""
    candidates = st.trim_candidates()

    for item in candidates:
        path = item["path"]
        assert not st._should_never_trim(path), \
            f"{path} is in NEVER_TRIM and should not be in candidates"


def test_trim_candidates_returns_expected_categories():
    """Test that trim_candidates returns items with expected structure."""
    candidates = st.trim_candidates()

    for item in candidates:
        assert "category" in item
        assert "path" in item
        assert "size_kb" in item
        assert item["size_kb"] >= 0


def test_allowlist_includes_npm():
    """Test that npm cache path is in allowlist."""
    assert any(cat == "npm_cache" for cat, _ in st.ALLOWLIST)


def test_allowlist_includes_xcode_deriveddata():
    """Test that Xcode DerivedData is in allowlist."""
    assert any(cat == "xcode_deriveddata" for cat, _ in st.ALLOWLIST)


def test_allowlist_includes_worktrees_build_output():
    """Test that worktrees build output is in allowlist."""
    assert any(cat == "worktrees_build_output" for cat, _ in st.ALLOWLIST)
