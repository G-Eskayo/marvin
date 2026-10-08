"""Tests for storage_ledger.py. Run via:
    ~/.agents/venv/bin/python -m pytest lib/tests/test_storage_ledger.py -v
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

LIB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LIB))

import storage_ledger as sl  # noqa: E402


def test_categorize_parses_du_output():
    """Test categorize() against a saved du sample."""
    fixture = (Path(__file__).parent / "fixtures" / "du-sample-mini.txt").read_text()
    result = sl.categorize(fixture)

    assert all(cat in result for cat in sl.CATEGORIES)
    assert result["rebuildable_caches"] > 0, "npm/pip/homebrew caches should be detected"
    assert result["build_output"] > 0, "worktree build output should be detected"
    assert result["worktrees"] > 0, "worktree root should be detected"
    assert result["models"] > 0, "model folders should be detected"


def test_categorize_handles_empty_input():
    """Test categorize() with empty input."""
    result = sl.categorize("")
    assert all(v == 0 for v in result.values())


def test_append_entry_creates_jsonl_file(tmp_path):
    """Test append_entry() writes a valid JSON Lines entry."""
    ledger_path = tmp_path / "storage-ledger-test.jsonl"
    now = datetime(2026, 10, 7, 12, 0, 0, tzinfo=timezone.utc)

    categories = {"rebuildable_caches": 1000, "other": 500}
    sl.append_entry(categories, 1048576, 10485760, path=ledger_path, now=now)

    assert ledger_path.exists()
    lines = ledger_path.read_text().strip().split("\n")
    assert len(lines) == 1

    entry = json.loads(lines[0])
    assert entry["date"] == "2026-10-07"
    assert entry["free_kb"] == 1048576
    assert entry["total_kb"] == 10485760
    assert entry["categories"]["rebuildable_caches"] == 1000


def test_read_ledger_returns_latest_entries(tmp_path):
    """Test read_ledger() returns the last N entries."""
    ledger_path = tmp_path / "storage-ledger-test.jsonl"

    for i in range(20):
        now = datetime(2026, 10, i + 1, 12, 0, 0, tzinfo=timezone.utc)
        sl.append_entry({"other": 100}, 1000000 - i * 10000, 10485760,
                       path=ledger_path, now=now)

    entries = sl.read_ledger("test", days=14, path=ledger_path)
    assert len(entries) == 14
    assert entries[0]["date"] == "2026-10-07"
    assert entries[-1]["date"] == "2026-10-20"


def test_read_ledger_handles_missing_file(tmp_path):
    """Test read_ledger() gracefully handles missing files."""
    entries = sl.read_ledger("nonexistent", days=14, path=tmp_path / "missing.jsonl")
    assert entries == []
