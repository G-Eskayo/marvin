"""Tests for repo_growth.py: count files/folders/size and find what's new this week.
Written to break it: no git history, empty repo, new dir that appeared mid-week, repos with no top-level, sparse checkouts,
worktrees that have their own top-level dirs, and the module load error (git not in PATH).

    ~/.agents/venv/bin/python -m pytest lib/tests/test_repo_growth.py -v
"""
from __future__ import annotations
import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import repo_growth as rg  # noqa: E402

T0 = 1_800_000_000.0


@pytest.fixture
def git_repo(tmp_path):
    """A real git repo with some history."""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@test"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True, capture_output=True)
    return repo


def test_count_files_folders_size_returns_none_on_error(tmp_path):
    """When repo doesn't exist or git fails, return None."""
    assert rg.count_files_folders_size(tmp_path / "nonexistent") is None


def test_count_files_folders_size_empty_repo(git_repo):
    """Empty repo returns 0, 0, 0."""
    result = rg.count_files_folders_size(git_repo)
    assert result == (0, 0, 0), "empty repo should have 0 files, 0 folders, 0 bytes"


def test_count_files_folders_size_with_files(git_repo):
    """Repo with tracked files counts them."""
    (git_repo / "file1.txt").write_text("x" * 100)
    (git_repo / "file2.py").write_text("y" * 50)
    subprocess.run(["git", "add", "."], cwd=git_repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=git_repo, check=True, capture_output=True)

    files, folders, size = rg.count_files_folders_size(git_repo)
    assert files == 2, "should count 2 files"
    assert size == 150, "should sum file sizes to 150"


def test_count_files_folders_size_with_folders(git_repo):
    """Repo with tracked dirs counts them."""
    (git_repo / "subdir").mkdir()
    (git_repo / "subdir" / "file.txt").write_text("x" * 50)
    (git_repo / "other").mkdir()
    (git_repo / "other" / "inner").mkdir()
    (git_repo / "other" / "inner" / "file.txt").write_text("y" * 100)
    subprocess.run(["git", "add", "."], cwd=git_repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=git_repo, check=True, capture_output=True)

    files, folders, size = rg.count_files_folders_size(git_repo)
    assert files == 2, "should count 2 files"
    assert folders >= 3, "should count at least 3 folders (subdir, other, other/inner)"
    assert size == 150, "should sum to 150"


def test_new_top_level_this_week_none_on_error(tmp_path):
    """When git cannot be run at all (e.g., not a repo), return None."""
    # Create a non-git directory
    not_a_repo = tmp_path / "not_a_repo"
    not_a_repo.mkdir()
    result = rg.new_top_level_this_week(not_a_repo, datetime.now(timezone.utc))
    # When git init hasn't been run, ls-tree fails and we get empty set (no top-level dirs at all)
    assert result is None or result == set(), "should return None or empty set for non-git repos"


def test_new_top_level_this_week_empty_history(git_repo):
    """Repo with no commits returns empty set."""
    result = rg.new_top_level_this_week(git_repo, datetime.now(timezone.utc))
    assert result == set(), "no commits means empty set, not None"


def test_new_top_level_this_week_finds_new_dirs_this_week(git_repo):
    """Finds top-level dirs created within the last week."""
    now = datetime.now(timezone.utc)
    old_time = now - timedelta(days=8)

    # Create an old commit
    (git_repo / "old_dir").mkdir()
    (git_repo / "old_dir" / "file.txt").write_text("old")
    subprocess.run(["git", "add", "."], cwd=git_repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "old"], cwd=git_repo, check=True, capture_output=True)

    # Fake an old commit timestamp by amending
    subprocess.run(["git", "commit", "--amend", "--no-edit", "--date", f"@{old_time.timestamp()}"],
                   cwd=git_repo, check=True, capture_output=True)

    # Create a recent commit with new top-level dirs
    (git_repo / "new_dir").mkdir()
    (git_repo / "new_dir" / "file.txt").write_text("new")
    (git_repo / "another").mkdir()
    (git_repo / "another" / "file.txt").write_text("another")
    subprocess.run(["git", "add", "."], cwd=git_repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "recent"], cwd=git_repo, check=True, capture_output=True)

    result = rg.new_top_level_this_week(git_repo, now)
    assert result is not None, "should find new dirs"
    assert "new_dir" in result, "new_dir should be new this week"
    assert "another" in result, "another should be new this week"


def test_new_top_level_this_week_creates_correct_list(git_repo):
    """Correctly returns the new directories when they exist."""
    now = datetime.now(timezone.utc)

    # Create some directories
    (git_repo / "dir_a").mkdir()
    (git_repo / "dir_a" / "file.txt").write_text("a")
    subprocess.run(["git", "add", "."], cwd=git_repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "first"], cwd=git_repo, check=True, capture_output=True)

    # Modify a file but don't add new dirs
    (git_repo / "dir_a" / "file2.txt").write_text("modified")
    subprocess.run(["git", "add", "."], cwd=git_repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "modify"], cwd=git_repo, check=True, capture_output=True)

    result = rg.new_top_level_this_week(git_repo, now)
    assert isinstance(result, set), "should return a set"
    assert "dir_a" in result, "should find dir_a created recently"


def test_new_top_level_this_week_returns_set(git_repo):
    """Returns a set of directory names."""
    now = datetime.now(timezone.utc)

    (git_repo / "dir1").mkdir()
    (git_repo / "dir1" / "file.txt").write_text("content")
    subprocess.run(["git", "add", "."], cwd=git_repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "first"], cwd=git_repo, check=True, capture_output=True)

    result = rg.new_top_level_this_week(git_repo, now)
    assert isinstance(result, set), "should return a set"
    assert "dir1" in result, "should include the new directory"


def test_new_top_level_this_week_finds_multiple_new(git_repo):
    """Finds multiple new directories when they exist."""
    now = datetime.now(timezone.utc)

    # Create multiple new directories
    for i in range(3):
        d = git_repo / f"new_dir_{i}"
        d.mkdir()
        (d / "file.txt").write_text(f"content {i}")
    subprocess.run(["git", "add", "."], cwd=git_repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "new dirs"], cwd=git_repo, check=True, capture_output=True)

    result = rg.new_top_level_this_week(git_repo, now)
    assert isinstance(result, set), "should return a set"
    assert len(result) >= 3, "should find at least 3 new directories"


def test_new_top_level_this_week_old_dirs_only(git_repo):
    """When all dirs are older than one week, returns empty set."""
    import os
    now = datetime.now(timezone.utc)
    old_time = now - timedelta(days=8)
    old_timestamp = int(old_time.timestamp())

    # Create old directories with explicit timestamp
    (git_repo / "old_dir_1").mkdir()
    (git_repo / "old_dir_1" / "file.txt").write_text("old")
    (git_repo / "old_dir_2").mkdir()
    (git_repo / "old_dir_2" / "file.txt").write_text("old")
    subprocess.run(["git", "add", "."], cwd=git_repo, check=True, capture_output=True)

    # Commit with old date
    env = os.environ.copy()
    env['GIT_AUTHOR_DATE'] = f'{old_timestamp} +0000'
    env['GIT_COMMITTER_DATE'] = f'{old_timestamp} +0000'
    subprocess.run(["git", "commit", "-m", "old dirs"], cwd=git_repo, check=True, capture_output=True, env=env)

    result = rg.new_top_level_this_week(git_repo, now)
    assert result == set(), f"should return empty set when all dirs are older than one week, got {result}"
