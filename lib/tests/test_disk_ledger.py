"""Tests for disk_ledger.py. Run via:
    ~/.agents/venv/bin/python -m pytest lib/tests/test_disk_ledger.py -v
"""
from __future__ import annotations
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

LIB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LIB))

import disk_ledger as dl  # noqa: E402


DU_SAMPLE = """\
100	/path/to/npm_cacache
200	/path/to/pnpm
150	/path/to/pip_cache
80	/path/to/brew_cache
"""


@pytest.fixture
def ledger_path(tmp_path):
    return tmp_path / "disk-ledger.jsonl"


@pytest.fixture
def mock_du():
    """Fake du callable that returns KB for known paths."""
    def _mock_du(path):
        known = {
            "/path/to/npm_cacache": 100,
            "/path/to/pnpm": 200,
            "/path/to/pip_cache": 150,
            "/path/to/brew_cache": 80,
        }
        return known.get(str(path), 0)
    return _mock_du


def test_measure_categories_basic(mock_du, monkeypatch):
    """Categorize disk usage from provided paths."""
    monkeypatch.setattr(dl, "_default_du_kb", mock_du)

    result = dl.measure_categories(du=mock_du)

    assert isinstance(result, dict)
    assert all(cat in result for cat in [
        "rebuildable_caches", "build_output", "worktrees", "models",
        "icloud_cache", "docker", "user_files", "other"
    ])
    assert all(isinstance(v, int) and v >= 0 for v in result.values())


def test_append_entry_creates_ledger(ledger_path, tmp_path, monkeypatch):
    """append_entry writes a JSON line with categories and free space."""
    monkeypatch.setattr(dl, "LEDGER_PATH", ledger_path)
    monkeypatch.setattr("machine_profile.registry_id", lambda: "mac-mini")

    categories = {
        "rebuildable_caches": 1000,
        "build_output": 2000,
        "worktrees": 5000,
        "models": 3000,
        "icloud_cache": 500,
        "docker": 1500,
        "user_files": 10000,
        "other": 2000,
    }

    dl.append_entry(categories, free_kb=20000, total_kb=100000, device=None, now=None, path=ledger_path)

    assert ledger_path.exists()
    lines = ledger_path.read_text().strip().split("\n")
    assert len(lines) == 1

    entry = json.loads(lines[0])
    assert entry["free_kb"] == 20000
    assert entry["total_kb"] == 100000
    assert entry["categories"]["worktrees"] == 5000


def test_append_entry_idempotent_same_day(ledger_path, monkeypatch):
    """Same-day runs overwrite, never duplicate."""
    monkeypatch.setattr(dl, "LEDGER_PATH", ledger_path)
    monkeypatch.setattr("machine_profile.registry_id", lambda: "mac-mini")

    now = datetime(2026, 10, 8, 10, 0, 0, tzinfo=timezone.utc)
    categories = {"rebuildable_caches": 1000, "build_output": 2000, "worktrees": 5000,
                  "models": 3000, "icloud_cache": 500, "docker": 1500, "user_files": 10000, "other": 2000}

    dl.append_entry(categories, free_kb=20000, total_kb=100000, device=None, now=now, path=ledger_path)
    dl.append_entry(categories, free_kb=21000, total_kb=100000, device=None, now=now, path=ledger_path)

    lines = ledger_path.read_text().strip().split("\n")
    assert len(lines) == 1, "Same-day entries should overwrite"
    assert json.loads(lines[0])["free_kb"] == 21000


def test_append_entry_different_days_appends(ledger_path, monkeypatch):
    """Different days append, creating multiple lines."""
    monkeypatch.setattr(dl, "LEDGER_PATH", ledger_path)
    monkeypatch.setattr("machine_profile.registry_id", lambda: "mac-mini")

    now1 = datetime(2026, 10, 8, 10, 0, 0, tzinfo=timezone.utc)
    now2 = datetime(2026, 10, 9, 10, 0, 0, tzinfo=timezone.utc)
    categories = {"rebuildable_caches": 1000, "build_output": 2000, "worktrees": 5000,
                  "models": 3000, "icloud_cache": 500, "docker": 1500, "user_files": 10000, "other": 2000}

    dl.append_entry(categories, free_kb=20000, total_kb=100000, device=None, now=now1, path=ledger_path)
    dl.append_entry(categories, free_kb=19000, total_kb=100000, device=None, now=now2, path=ledger_path)

    lines = ledger_path.read_text().strip().split("\n")
    assert len(lines) == 2


def test_run_daily_ledger_returns_summary(tmp_path, monkeypatch):
    """run_daily_ledger returns a summary dict with expected keys."""
    ledger_path = tmp_path / "disk-ledger.jsonl"
    monkeypatch.setattr(dl, "LEDGER_PATH", ledger_path)
    monkeypatch.setattr("machine_profile.registry_id", lambda: "mac-mini")

    result = dl.run_daily_ledger()

    assert isinstance(result, dict)
    assert "timestamp" in result
    assert "categories" in result or "free_kb" in result
    assert ledger_path.exists()
