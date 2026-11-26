#!/usr/bin/env python3
"""Tests for lib/cleanup_sweep.py lock handling (tests 12-17 from the plan)."""
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))
import cleanup_sweep as cs
import worktree_lock


# ─── Test 12: _list_root includes "locked" field ──────────────────────────

def test_list_root_adds_locked_field():
    """_list_root computes a 'locked' field via worktree_lock.is_locked."""
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = Path(tmpdir) / "repo"
        repo.mkdir()
        git_dir = repo / ".git"
        git_dir.mkdir()

        # Mock the git operations
        with patch("cleanup_sweep._git") as mock_git:
            mock_git.side_effect = lambda *args, **kw: MagicMock(
                returncode=0,
                stdout="pipeline/ticket-1\n" if "show-current" in args else "mock"
            )

            with patch("cleanup_sweep.worktree_lock.is_locked") as mock_is_locked:
                mock_is_locked.return_value = False

                cwds = set()
                result = cs._list_root(repo, cwds)

                # Result should have a "locked" field
                assert len(result) > 0
                assert "locked" in result[0]


# ─── Test 13: decide_worktree guards locked worktrees ──────────────────────

def test_decide_worktree_keeps_locked():
    """decide_worktree returns "keep" for locked worktrees."""
    wt = {
        "repo": "G-Eskayo/marvin",
        "in_use": False,
        "locked": True,
        "dirty": False,
        "branch": "pipeline/ticket-1",
    }
    action, reason = cs.decide_worktree(wt, pr_state=None, claimed=False)
    assert action == "keep"
    assert "lock" in reason.lower()


def test_decide_worktree_allows_non_locked():
    """decide_worktree doesn't guard against unlocked worktrees."""
    wt = {
        "repo": "G-Eskayo/marvin",
        "in_use": False,
        "locked": False,  # Not locked
        "dirty": False,
        "branch": "pipeline/ticket-1",
        "ahead": 0,
        "age_hours": 25,
    }
    action, reason = cs.decide_worktree(wt, pr_state=None, claimed=False)
    # Should proceed to other checks, not keep
    assert action != "keep" or "lock" not in reason.lower()


# ─── Test 14: _default_remove_worktree re-checks lock ──────────────────────

def test_remove_worktree_aborts_if_locked():
    """_default_remove_worktree returns False if lock is held."""
    wt = {
        "path": Path("/tmp/wt"),
        "clone": Path("/tmp/repo"),
        "branch": "pipeline/ticket-1",
    }

    with patch("cleanup_sweep.worktree_lock.is_locked") as mock_is_locked:
        mock_is_locked.return_value = True
        result = cs._default_remove_worktree(wt)
        assert result is False


def test_remove_worktree_proceeds_if_not_locked():
    """_default_remove_worktree proceeds if lock is not held."""
    wt = {
        "path": Path("/tmp/wt"),
        "clone": Path("/tmp/repo"),
        "branch": "pipeline/ticket-1",
    }

    with patch("cleanup_sweep.worktree_lock.is_locked") as mock_is_locked:
        mock_is_locked.return_value = False
        with patch("cleanup_sweep._git") as mock_git:
            mock_git.return_value = MagicMock(returncode=0)
            result = cs._default_remove_worktree(wt)
            # Should attempt the removal
            assert mock_git.called


# ─── Test 15: backup_worktree aborts if locked ────────────────────────────

def test_backup_worktree_returns_none_if_locked():
    """backup_worktree returns None if the worktree is locked."""
    wt = {
        "path": Path("/tmp/wt"),
        "clone": Path("/tmp/repo"),
        "branch": "pipeline/ticket-1",
    }

    with patch("cleanup_sweep.worktree_lock.is_locked") as mock_is_locked:
        mock_is_locked.return_value = True
        result = cs.backup_worktree(wt)
        assert result is None


# ─── Test 16: sweep_worktrees respects locked in decide_worktree ──────────

def test_sweep_keeps_locked_worktrees():
    """sweep_worktrees keeps worktrees that are locked."""
    locked_wt = {
        "path": Path("/tmp/wt1"),
        "branch": "pipeline/ticket-1",
        "clone": Path("/tmp/repo"),
        "repo": "G-Eskayo/marvin",
        "in_use": False,
        "locked": True,
        "dirty": False,
        "ahead": 0,
        "age_hours": 10,
    }

    def mock_list():
        return [locked_wt]

    def mock_pr_state(repo, branch):
        return None

    def mock_is_claimed(repo, number):
        return False

    result = cs.sweep_worktrees(
        list_worktrees=mock_list,
        pr_state=mock_pr_state,
        is_claimed=mock_is_claimed,
    )

    # The locked worktree should not be removed (it's kept)
    assert len(result["removed"]) == 0
    # It should not be in review either (kept items don't appear in review)
    assert len(result["review"]) == 0


# ─── Test 17: Integration: Lock prevents cleanup but allows in-use check ───

def test_lock_integration_with_in_use():
    """A locked worktree is kept even if it looks stale."""
    wt = {
        "path": Path("/tmp/old-wt"),
        "branch": "pipeline/old-ticket",
        "clone": Path("/tmp/repo"),
        "repo": "G-Eskayo/marvin",
        "in_use": False,  # Not currently in use by a process
        "locked": True,   # But is locked
        "dirty": False,
        "ahead": 0,
        "age_hours": 100,  # Very old
    }

    # Even though it's old with no commits/changes, it should be kept
    action, reason = cs.decide_worktree(wt, pr_state=None, claimed=False)
    assert action == "keep"
    assert "lock" in reason.lower()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
