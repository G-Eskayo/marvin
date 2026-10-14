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


def test_xcode_and_app_data_are_measured(monkeypatch, tmp_path):
    """18 GB of simulators, wallpapers and app data grew on the Mini without showing anywhere (2026-10-14)."""
    monkeypatch.setattr(dl, "HOME", tmp_path)
    lib = tmp_path / "Library"
    sizes = {lib / "Developer": 33_000_000, lib / "Application Support": 15_000_000,
             lib / "Containers": 30_000_000, lib / "Group Containers": 3_000_000}
    result = dl.measure_categories(du=lambda p: sizes.get(Path(p), 0))
    assert result["xcode"] == 33_000_000
    assert result["app_support"] == 48_000_000


def test_messages_and_photos_are_found_where_macos_keeps_them(monkeypatch, tmp_path):
    """The ledger looked for ~/Messages, which doesn't exist: 53 GB of ~/Library/Messages went uncounted."""
    monkeypatch.setattr(dl, "HOME", tmp_path)
    lib = tmp_path / "Library"
    sizes = {lib / "Messages": 53_000_000, lib / "Photos": 28_000_000, tmp_path / "Messages": 999}
    assert dl.measure_categories(du=lambda p: sizes.get(Path(p), 0))["user_files"] == 81_000_000


def test_all_of_library_caches_counts_as_rebuildable_once(monkeypatch, tmp_path):
    """Caches are rebuildable by definition. Counting the folder and its Homebrew/Electron/SwiftPM parts would double."""
    monkeypatch.setattr(dl, "HOME", tmp_path)
    caches = tmp_path / "Library" / "Caches"
    sizes = {caches: 10_000_000, caches / "Homebrew": 1_000, caches / "Electron": 1_000, caches / "SwiftPM": 1_000}
    assert dl.measure_categories(du=lambda p: sizes.get(Path(p), 0))["rebuildable_caches"] == 10_000_000


def test_other_is_whatever_the_named_categories_do_not_explain():
    """"other" was always 0, so space outside the named folders was invisible."""
    cats = {"models": 100, "worktrees": 50, "other": 0}
    assert dl.with_other(cats, used_kb=400)["other"] == 250


def test_other_never_goes_negative_when_categories_overlap_or_round():
    assert dl.with_other({"models": 500, "other": 0}, used_kb=400)["other"] == 0


def test_every_measured_category_is_known_to_the_dashboard():
    """category_details drops any category missing from CATEGORY_INFO, which would hide it again."""
    import disk_categories as dc
    assert set(dl.measure_categories(du=lambda p: 0)) <= set(dc.CATEGORY_INFO)


def test_du_keeps_the_total_when_some_folders_are_unreadable(monkeypatch, tmp_path):
    """du exits 1 when one subfolder is off-limits but still prints the total: ~/Library/Developer read as 0, not 33 GB."""
    class R:
        returncode, stdout, stderr = 1, f"34603008\t{tmp_path}\n", "du: ./x: Operation not permitted\n"
    monkeypatch.setattr(dl.subprocess, "run", lambda *a, **k: R())
    assert dl._default_du_kb(tmp_path) == 34603008


def test_du_gets_long_enough_for_a_big_folder(monkeypatch, tmp_path):
    """5 seconds wasn't enough for a 50 GB folder, and a timeout read as 0. The sweep runs at night: give it minutes."""
    seen = {}
    class R:
        returncode, stdout, stderr = 0, f"1\t{tmp_path}\n", ""
    monkeypatch.setattr(dl.subprocess, "run", lambda *a, **k: seen.update(k) or R())
    dl._default_du_kb(tmp_path)
    assert seen["timeout"] >= 300
