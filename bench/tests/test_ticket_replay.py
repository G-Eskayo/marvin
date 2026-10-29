"""Tests for ticket_replay.py — git/PR mechanics to replay a ticket scenario.
~/.agents/venv/bin/python -m pytest bench/tests/test_ticket_replay.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch, call

import pytest

BENCH = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BENCH / "lib"))

import ticket_replay as tr


class TestResolveMergeCommit:
    def test_resolve_merge_commit_fetches_via_gh(self):
        """Test that resolve_merge_commit uses gh CLI with correct JSON query."""
        mock_gh = MagicMock()
        mock_gh.stdout = "merge123\n"
        mock_gh.returncode = 0

        with patch("subprocess.run", return_value=mock_gh) as mock_run:
            commit = tr.resolve_merge_commit("720", "/tmp/repo")

            # Verify gh pr view was called
            call_args = mock_run.call_args
            assert "gh" in call_args[0][0]
            assert "pr" in call_args[0][0]
            assert "view" in call_args[0][0]
            assert "720" in call_args[0][0]
            assert call_args[1].get("cwd") == "/tmp/repo"

            # Should return the merge commit, not the parent
            assert commit == "merge123"

    def test_resolve_merge_commit_returns_none_on_gh_error(self):
        """Test that resolve_merge_commit returns None on gh CLI error."""
        mock_gh = MagicMock()
        mock_gh.stdout = ""
        mock_gh.returncode = 1

        with patch("subprocess.run", return_value=mock_gh):
            commit = tr.resolve_merge_commit("720", "/tmp/repo")
            assert commit is None

    def test_resolve_merge_commit_returns_merge_oid(self):
        """Test that resolve_merge_commit returns the merge commit OID, not the parent."""
        mock_gh = MagicMock()
        mock_gh.stdout = "merge123\n"
        mock_gh.returncode = 0

        with patch("subprocess.run", return_value=mock_gh) as mock_run:
            commit = tr.resolve_merge_commit("720", "/tmp/repo")

            # Should only call gh once (just to get the merge commit)
            assert mock_run.call_count == 1
            assert commit == "merge123"

    def test_resolve_merge_commit_handles_exception(self):
        """Test that resolve_merge_commit never raises, returns None on error."""
        with patch("subprocess.run", side_effect=Exception("permission denied")):
            commit = tr.resolve_merge_commit("720", "/tmp/repo")
            assert commit is None


class TestGetPRBody:
    def test_get_pr_body_fetches_via_gh(self):
        """Test that get_pr_body uses gh to fetch PR body."""
        mock_result = MagicMock()
        mock_result.stdout = "## Summary\nThis is a test PR"
        mock_result.returncode = 0

        with patch("subprocess.run", return_value=mock_result):
            body = tr.get_pr_body("720", "/tmp/repo")
            assert "Summary" in body

    def test_get_pr_body_uses_repo_cwd(self):
        """Test that get_pr_body uses repo_path as cwd for gh command."""
        mock_result = MagicMock()
        mock_result.stdout = "test body"
        mock_result.returncode = 0

        with patch("subprocess.run", return_value=mock_result) as mock_run:
            tr.get_pr_body("720", "/path/to/repo")

            # Verify cwd was set to repo_path
            call_kwargs = mock_run.call_args[1]
            assert call_kwargs.get("cwd") == "/path/to/repo"

    def test_get_pr_body_returns_empty_on_error(self):
        """Test that get_pr_body returns empty string on error."""
        mock_result = MagicMock()
        mock_result.returncode = 1

        with patch("subprocess.run", return_value=mock_result):
            body = tr.get_pr_body("720", "/tmp/repo")
            assert body == ""


class TestGetTestFiles:
    def test_get_test_files_uses_git_diff(self):
        """Test that get_test_files uses git diff --name-only."""
        mock_result = MagicMock()
        mock_result.stdout = "bench/tests/test_foo.py\nbench/tests/test_bar.py\nlib/main.py\n"
        mock_result.returncode = 0

        with patch("subprocess.run", return_value=mock_result) as mock_run:
            files = tr.get_test_files("abc123", "merge456", "/tmp/repo")

            # Verify git diff was called
            call_args = mock_run.call_args
            assert "git" in call_args[0][0]
            assert "diff" in call_args[0][0]
            assert "--name-only" in call_args[0][0]
            assert "abc123" in call_args[0][0]
            assert "merge456" in call_args[0][0]

            # Should extract test files
            assert len(files) == 2
            assert "test_foo.py" in files[0]
            assert "test_bar.py" in files[1]

    def test_get_test_files_filters_by_test_pattern(self):
        """Test that get_test_files filters for test*.py files."""
        mock_result = MagicMock()
        mock_result.stdout = "bench/tests/test_foo.py\nlib/main.py\nutil/test_helpers.py\n"
        mock_result.returncode = 0

        with patch("subprocess.run", return_value=mock_result):
            files = tr.get_test_files("abc123", "merge456", "/tmp/repo")

            # Should only include files with "test" in the name
            assert len(files) == 2
            assert all("test" in f.lower() for f in files)

    def test_get_test_files_returns_empty_on_error(self):
        """Test that get_test_files returns empty list on git error."""
        mock_result = MagicMock()
        mock_result.returncode = 1

        with patch("subprocess.run", return_value=mock_result):
            files = tr.get_test_files("abc123", "merge456", "/tmp/repo")
            assert files == []


class TestCreateWorktree:
    def test_create_worktree_calls_git_worktree_add(self):
        """Test that create_worktree runs git worktree add."""
        mock_result = MagicMock()
        mock_result.returncode = 0

        with patch("subprocess.run", return_value=mock_result) as mock_run:
            with patch("tempfile.mkdtemp", return_value="/tmp/bench-wt-123"):
                path = tr.create_worktree("abc123", "/tmp/repo")

                # Verify git worktree add was called
                call_args = mock_run.call_args
                assert "git" in call_args[0][0]
                assert "worktree" in call_args[0][0]
                assert "add" in call_args[0][0]
                assert path == Path("/tmp/bench-wt-123")

    def test_create_worktree_cleans_up_on_failure(self):
        """Test that create_worktree cleans up temp dir on git failure."""
        mock_result = MagicMock()
        mock_result.returncode = 1

        with patch("subprocess.run", return_value=mock_result):
            with patch("tempfile.mkdtemp", return_value="/tmp/bench-wt-123"):
                with patch("shutil.rmtree") as mock_rmtree:
                    path = tr.create_worktree("abc123", "/tmp/repo")

                    assert path is None
                    mock_rmtree.assert_called_once()

    def test_create_worktree_returns_none_on_exception(self):
        """Test that create_worktree returns None on exception."""
        with patch("subprocess.run", side_effect=Exception("oops")):
            with patch("tempfile.mkdtemp", return_value="/tmp/bench-wt-123"):
                with patch("shutil.rmtree"):
                    path = tr.create_worktree("abc123", "/tmp/repo")
                    assert path is None


class TestReplayTicket:
    def test_replay_ticket_orchestrates_full_flow(self):
        """Test that replay_ticket calls resolve, create, get_pr, get_test_files."""
        with patch.object(tr, "resolve_merge_commit", return_value="merge123"):
            with patch("subprocess.run") as mock_run:
                # Mock git rev-parse for parent
                parent_result = MagicMock()
                parent_result.stdout = "base456\n"
                parent_result.returncode = 0

                # Mock git worktree add
                worktree_result = MagicMock()
                worktree_result.returncode = 0

                # Return different results for different calls
                mock_run.side_effect = [
                    parent_result,  # rev-parse
                    worktree_result,  # worktree add
                ]

                with patch("tempfile.mkdtemp", return_value="/tmp/bench-wt"):
                    with patch.object(tr, "get_pr_body", return_value="Test prompt"):
                        with patch.object(tr, "get_test_files", return_value=["test.py"]):
                            result = tr.replay_ticket("720", "/tmp/repo")

                            assert result.get("prompt") == "Test prompt"
                            assert "test.py" in result.get("test_files", [])
                            assert result.get("worktree_path") is not None
                            assert "cleanup_fn" in result
                            assert result.get("merge_commit") == "merge123"
                            assert result.get("base_commit") == "base456"

    def test_replay_ticket_returns_error_on_failed_resolve(self):
        """Test that replay_ticket returns error dict on failed resolve."""
        with patch.object(tr, "resolve_merge_commit", return_value=None):
            result = tr.replay_ticket("720", "/tmp/repo")

            assert result.get("error") is not None
            assert "Could not resolve" in result["error"]

    def test_replay_ticket_cleanup_function_removes_worktree(self):
        """Test that cleanup function removes the worktree with --force flag."""
        with patch.object(tr, "resolve_merge_commit", return_value="merge123"):
            with patch("subprocess.run") as mock_run:
                parent_result = MagicMock()
                parent_result.stdout = "base456\n"
                parent_result.returncode = 0

                worktree_result = MagicMock()
                worktree_result.returncode = 0

                # Mock all subsequent subprocess calls (rev-parse, worktree add, cleanup)
                cleanup_remove = MagicMock()
                cleanup_remove.returncode = 0
                cleanup_prune = MagicMock()
                cleanup_prune.returncode = 0

                mock_run.side_effect = [
                    parent_result,  # rev-parse
                    worktree_result,  # worktree add
                    cleanup_remove,  # worktree remove (in cleanup)
                    cleanup_prune,  # worktree prune (in cleanup)
                ]

                with patch("tempfile.mkdtemp", return_value="/tmp/bench-wt"):
                    with patch.object(tr, "get_pr_body", return_value="Test prompt"):
                        with patch.object(tr, "get_test_files", return_value=[]):
                            with patch("shutil.rmtree") as mock_rmtree:
                                result = tr.replay_ticket("720", "/tmp/repo")
                                cleanup = result.get("cleanup_fn")

                                # Cleanup should remove the worktree with --force
                                cleanup()

                                # Check that git worktree remove was called with --force
                                remove_call = mock_run.call_args_list[2]
                                assert "--force" in remove_call[0][0]
                                assert "worktree" in remove_call[0][0]
                                assert "remove" in remove_call[0][0]

                                # rmtree should also be called
                                mock_rmtree.assert_called()
