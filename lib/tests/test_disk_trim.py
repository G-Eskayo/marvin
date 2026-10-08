"""Tests for disk_trim.py. Run via:
    ~/.agents/venv/bin/python -m pytest lib/tests/test_disk_trim.py -v
"""
from __future__ import annotations
import sys
from pathlib import Path

import pytest

LIB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LIB))

import disk_trim as dt  # noqa: E402
import cleanup_sweep as cs  # noqa: E402


@pytest.fixture
def fixture_tree(tmp_path):
    """Create a test directory tree with:
    - A dirty worktree (uncommitted changes)
    - A model directory (.ollama)
    - User files (Documents)
    - ms-playwright cache (MUST NEVER be trimmed)
    - Allowlisted caches (npm, pnpm, pip, brew)
    """
    # Create allowlisted caches
    (tmp_path / ".npm" / "_cacache").mkdir(parents=True)
    (tmp_path / ".npm" / "_cacache" / "file1").write_text("cache1")

    (tmp_path / ".pnpm-store").mkdir(parents=True)
    (tmp_path / ".pnpm-store" / "file2").write_text("cache2")

    (tmp_path / ".cache" / "pip").mkdir(parents=True)
    (tmp_path / ".cache" / "pip" / "file3").write_text("cache3")

    (tmp_path / "Library" / "Caches" / "Homebrew").mkdir(parents=True)
    (tmp_path / "Library" / "Caches" / "Homebrew" / "file4").write_text("cache4")

    # Create ms-playwright cache (MUST NOT BE TRIMMED)
    (tmp_path / "Library" / "Caches" / "ms-playwright").mkdir(parents=True)
    (tmp_path / "Library" / "Caches" / "ms-playwright" / "chromium").mkdir(parents=True)
    (tmp_path / "Library" / "Caches" / "ms-playwright" / "chromium" / "important.bin").write_text("playwright!")

    # Create model dirs
    (tmp_path / ".ollama" / "models").mkdir(parents=True)
    (tmp_path / ".ollama" / "models" / "model.bin").write_text("model")

    # Create user files
    (tmp_path / "Documents").mkdir(parents=True)
    (tmp_path / "Documents" / "my_file.txt").write_text("important")

    # Create a dirty worktree (with .git)
    worktree_path = tmp_path / ".agents-pipeline-worktrees" / "dirty-wt"
    worktree_git = worktree_path / ".git"
    worktree_git.mkdir(parents=True)
    (worktree_path / "uncommitted.txt").write_text("unsaved work")

    return tmp_path


def test_never_trim_ms_playwright(fixture_tree, monkeypatch):
    """The acceptance criterion: ms-playwright must never be trimmed."""
    monkeypatch.setattr(dt, "get_disk_free_pct", lambda: 8)  # below yellow threshold
    monkeypatch.setattr(dt, "HOME", fixture_tree)

    # Mock list_worktrees to exclude the dirty one
    def mock_list_worktrees():
        return []

    monkeypatch.setattr(cs, "_default_list_worktrees", mock_list_worktrees)

    removed = dt.trim(dry_run=False)

    ms_playwright = fixture_tree / "Library" / "Caches" / "ms-playwright"
    assert ms_playwright.exists(), "ms-playwright must never be removed"
    assert (ms_playwright / "chromium" / "important.bin").exists(), "ms-playwright contents must be preserved"


def test_trim_respects_never_trim_allowlist(fixture_tree, monkeypatch):
    """All NEVER_TRIM paths are preserved even when disk is critical."""
    monkeypatch.setattr(dt, "get_disk_free_pct", lambda: 5)  # critically low
    monkeypatch.setattr(dt, "HOME", fixture_tree)

    def mock_list_worktrees():
        return []

    monkeypatch.setattr(cs, "_default_list_worktrees", mock_list_worktrees)

    removed = dt.trim(dry_run=False)

    # Verify NEVER_TRIM paths still exist
    assert (fixture_tree / ".ollama").exists(), "model dirs in NEVER_TRIM"
    assert (fixture_tree / "Library" / "Caches" / "ms-playwright").exists()


def test_trim_removes_allowlisted_caches(fixture_tree, monkeypatch):
    """When disk is low, allowlisted caches get removed."""
    monkeypatch.setattr(dt, "get_disk_free_pct", lambda: 8)  # below yellow
    monkeypatch.setattr(dt, "HOME", fixture_tree)

    def mock_list_worktrees():
        return []

    monkeypatch.setattr(cs, "_default_list_worktrees", mock_list_worktrees)

    removed = dt.trim(dry_run=False)

    # At least one allowlisted cache should be gone
    npm_cache = fixture_tree / ".npm" / "_cacache"
    pip_cache = fixture_tree / ".cache" / "pip"

    # One or both should be removed
    removed_something = not npm_cache.exists() or not pip_cache.exists()
    assert removed_something, "trim should remove some allowlisted caches when disk is low"


def test_trim_is_noop_when_disk_healthy(fixture_tree, monkeypatch):
    """Trim does nothing when free% >= yellow threshold."""
    monkeypatch.setattr(dt, "get_disk_free_pct", lambda: 25)  # above yellow
    monkeypatch.setattr(dt, "HOME", fixture_tree)
    monkeypatch.setattr(dt, "DISK_YELLOW_BELOW_PCT", 20)

    initial_npm = (fixture_tree / ".npm" / "_cacache" / "file1").exists()

    removed = dt.trim(dry_run=False)

    assert (fixture_tree / ".npm" / "_cacache" / "file1").exists() == initial_npm
    assert not removed, "Trim should be a no-op with healthy disk"


def test_trim_dry_run_changes_nothing(fixture_tree, monkeypatch):
    """Dry run reports what would be removed but doesn't remove it."""
    monkeypatch.setattr(dt, "get_disk_free_pct", lambda: 8)
    monkeypatch.setattr(dt, "HOME", fixture_tree)

    def mock_list_worktrees():
        return []

    monkeypatch.setattr(cs, "_default_list_worktrees", mock_list_worktrees)

    npm_before = (fixture_tree / ".npm" / "_cacache").exists()

    removed = dt.trim(dry_run=True)

    npm_after = (fixture_tree / ".npm" / "_cacache").exists()
    assert npm_before == npm_after, "Dry run must not change anything"
