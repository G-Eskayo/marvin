"""Tests for lib/tests/fake_github.py (test 10): the fake GitHub's own misuse cases.
Run via:
    ~/.agents/venv/bin/python -m pytest lib/tests/test_fake_github.py -v

This tests the fake module itself in isolation, before it's used by test_loop.py.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tests import fake_github as fg


class TestGitHubStateSerialization:
    """GitHubState.to_dict / from_dict round-trip."""

    def test_empty_state_round_trips(self):
        s = fg.GitHubState()
        d = s.to_dict()
        s2 = fg.GitHubState.from_dict(d)
        assert s2.counter == 1000
        assert s2.repos == {}

    def test_state_with_data_round_trips(self):
        s = fg.GitHubState()
        fg._ensure_repo(s, "test/repo")
        s.issues["test/repo"] = {1: {"number": 1, "title": "Test"}}
        d = s.to_dict()
        s2 = fg.GitHubState.from_dict(d)
        assert s2.repos["test/repo"]["owner"] == "test"
        assert s2.issues["test/repo"][1]["title"] == "Test"
        assert s2.counter == 1000


class TestBasicIssueOperations:
    """Issue create, list, comment, close, edit."""

    def test_issue_create_requires_title(self):
        s = fg.GitHubState()
        rc, stdout, stderr = fg.dispatch(s, ["issue", "create", "-R", "o/r"], "user")
        assert rc == 1 and "title" in stderr

    def test_issue_create_requires_repo(self):
        s = fg.GitHubState()
        rc, stdout, stderr = fg.dispatch(s, ["issue", "create", "--title", "t"], "user")
        assert rc == 1 and "-R" in stderr

    def test_issue_create_succeeds_with_minimal_args(self):
        s = fg.GitHubState()
        rc, stdout, stderr = fg.dispatch(s, ["issue", "create", "-R", "o/r", "--title", "Test"], "user")
        assert rc == 0
        issue = json.loads(stdout)
        assert issue["number"] == 1
        assert issue["title"] == "Test"
        assert issue["state"] == "open"
        assert issue["author"]["login"] == "user"

    def test_issue_list_empty_repo(self):
        s = fg.GitHubState()
        rc, stdout, stderr = fg.dispatch(s, ["issue", "list"], "user")
        assert rc == 0
        assert json.loads(stdout) == []

    def test_issue_list_after_create(self):
        s = fg.GitHubState()
        fg.dispatch(s, ["issue", "create", "-R", "o/r", "--title", "A"], "user")
        fg.dispatch(s, ["issue", "create", "-R", "o/r", "--title", "B"], "user")
        rc, stdout, stderr = fg.dispatch(s, ["issue", "list", "-R", "o/r"], "user")
        issues = json.loads(stdout)
        assert len(issues) == 2
        assert [i["number"] for i in issues] == [1, 2]

    def test_issue_comment_requires_number(self):
        s = fg.GitHubState()
        rc, stdout, stderr = fg.dispatch(s, ["issue", "comment"], "user")
        assert rc == 1 and "required" in stderr

    def test_issue_comment_requires_body(self):
        s = fg.GitHubState()
        fg.dispatch(s, ["issue", "create", "-R", "o/r", "--title", "t"], "user")
        rc, stdout, stderr = fg.dispatch(s, ["issue", "comment", "1", "-R", "o/r"], "user")
        assert rc == 1 and "body" in stderr

    def test_issue_comment_succeeds(self):
        s = fg.GitHubState()
        fg.dispatch(s, ["issue", "create", "-R", "o/r", "--title", "t"], "user")
        rc, stdout, stderr = fg.dispatch(s, ["issue", "comment", "1", "-R", "o/r", "-b", "Great!"], "user")
        assert rc == 0
        comment = json.loads(stdout)
        assert comment["body"] == "Great!"
        assert comment["author"]["login"] == "user"
        assert "databaseId" in comment

    def test_issue_comment_with_file(self, tmp_path):
        s = fg.GitHubState()
        fg.dispatch(s, ["issue", "create", "-R", "o/r", "--title", "t"], "user")
        body_file = tmp_path / "body.md"
        body_file.write_text("# Body from file")
        rc, stdout, stderr = fg.dispatch(s, ["issue", "comment", "1", "-R", "o/r", "--body-file", str(body_file)], "user")
        assert rc == 0
        assert json.loads(stdout)["body"] == "# Body from file"

    def test_issue_close_nonexistent_fails(self):
        s = fg.GitHubState()
        rc, stdout, stderr = fg.dispatch(s, ["issue", "close", "1"], "user")
        assert rc == 1 and "not found" in stderr

    def test_issue_close_succeeds(self):
        s = fg.GitHubState()
        fg.dispatch(s, ["issue", "create", "-R", "o/r", "--title", "t"], "user")
        rc, stdout, stderr = fg.dispatch(s, ["issue", "close", "1", "-R", "o/r"], "user")
        assert rc == 0 and json.loads(stdout)["state"] == "closed"

    def test_issue_edit_nonexistent_fails(self):
        s = fg.GitHubState()
        rc, stdout, stderr = fg.dispatch(s, ["issue", "edit", "1", "-R", "o/r", "-b", "new"], "user")
        assert rc == 1 and "not found" in stderr

    def test_issue_edit_body(self):
        s = fg.GitHubState()
        fg.dispatch(s, ["issue", "create", "-R", "o/r", "--title", "t", "-b", "old"], "user")
        rc, stdout, stderr = fg.dispatch(s, ["issue", "edit", "1", "-R", "o/r", "-b", "new"], "user")
        assert rc == 0
        issue = json.loads(stdout)
        assert issue["body"] == "new"


class TestBasicPROperations:
    """PR create, view, edit, ready, merge."""

    def test_pr_create_requires_repo(self):
        s = fg.GitHubState()
        rc, stdout, stderr = fg.dispatch(s, ["pr", "create", "--title", "t"], "user")
        assert rc == 1 and "-R" in stderr

    def test_pr_create_succeeds(self):
        s = fg.GitHubState()
        rc, stdout, stderr = fg.dispatch(s, ["pr", "create", "-R", "o/r", "-t", "PR", "--head", "feature", "--base", "main"], "user")
        assert rc == 0
        pr = json.loads(stdout)
        assert pr["number"] == 1
        assert pr["title"] == "PR"
        assert pr["state"] == "open"
        assert pr["headRefName"] == "feature"
        assert pr["baseRefName"] == "main"

    def test_pr_view_nonexistent(self):
        s = fg.GitHubState()
        rc, stdout, stderr = fg.dispatch(s, ["pr", "view", "1"], "user")
        assert rc == 1 and "not found" in stderr

    def test_pr_view_succeeds(self):
        s = fg.GitHubState()
        fg.dispatch(s, ["pr", "create", "-R", "o/r", "-t", "PR", "--head", "f"], "user")
        rc, stdout, stderr = fg.dispatch(s, ["pr", "view", "1", "-R", "o/r"], "user")
        assert rc == 0
        assert json.loads(stdout)["number"] == 1

    def test_pr_merge_nonexistent(self):
        s = fg.GitHubState()
        rc, stdout, stderr = fg.dispatch(s, ["pr", "merge", "1"], "user")
        assert rc == 1

    def test_pr_merge_succeeds(self):
        s = fg.GitHubState()
        fg.dispatch(s, ["pr", "create", "-R", "o/r", "-t", "PR", "--head", "f"], "user")
        rc, stdout, stderr = fg.dispatch(s, ["pr", "merge", "1", "-R", "o/r"], "user")
        assert rc == 0
        assert json.loads(stdout)["state"] == "merged"
        # Verify it's merged now
        rc2, stdout2, _ = fg.dispatch(s, ["pr", "view", "1", "-R", "o/r"], "user")
        assert json.loads(stdout2)["state"] == "merged"


class TestLabelOperations:
    """Label create."""

    def test_label_create_requires_repo(self):
        s = fg.GitHubState()
        rc, stdout, stderr = fg.dispatch(s, ["label", "create", "-n", "bug"], "user")
        assert rc == 1 and "-R" in stderr

    def test_label_create_succeeds(self):
        s = fg.GitHubState()
        rc, stdout, stderr = fg.dispatch(s, ["label", "create", "-R", "o/r", "-n", "bug", "-c", "ff0000"], "user")
        assert rc == 0
        label = json.loads(stdout)
        assert label["name"] == "bug"
        assert label["color"] == "ff0000"


class TestAPIOperations:
    """API endpoints."""

    def test_api_repo_view(self):
        s = fg.GitHubState()
        fg._ensure_repo(s, "o/r")
        rc, stdout, stderr = fg.dispatch(s, ["api", "repos/o/r"], "user")
        assert rc == 0
        assert json.loads(stdout)["name"] == "r"

    def test_api_repo_view_nonexistent(self):
        s = fg.GitHubState()
        rc, stdout, stderr = fg.dispatch(s, ["api", "repos/o/r"], "user")
        assert rc == 1 and "not found" in stderr

    def test_api_compare(self):
        s = fg.GitHubState()
        fg._ensure_repo(s, "o/r")
        rc, stdout, stderr = fg.dispatch(s, ["api", "repos/o/r/compare/main...feature"], "user")
        assert rc == 0
        assert json.loads(stdout)["status"] == "ahead"

    def test_api_graphql(self):
        s = fg.GitHubState()
        rc, stdout, stderr = fg.dispatch(s, ["api", "graphql", "-f", "query={...}"], "user")
        assert rc == 0
        data = json.loads(stdout)
        assert "data" in data
        assert "prs" in data["data"]

    def test_api_rate_limit(self):
        s = fg.GitHubState()
        rc, stdout, stderr = fg.dispatch(s, ["api", "rate_limit"], "user")
        assert rc == 0
        data = json.loads(stdout)
        assert data["resources"]["core"]["remaining"] > 0


class TestFakeGitHubClass:
    """FakeGitHub in-process interface."""

    def test_run_persists_state(self, tmp_path):
        state_file = tmp_path / "state.json"
        gh = fg.FakeGitHub(state_file)
        gh.run(["issue", "create", "-R", "o/r", "-t", "Issue 1"], actor="user1")
        # Load from disk in a new instance
        gh2 = fg.FakeGitHub(state_file)
        rc, stdout, _ = fg.dispatch(gh2.state, ["issue", "list", "-R", "o/r"], "user1")
        issues = json.loads(stdout)
        assert len(issues) == 1
        assert issues[0]["title"] == "Issue 1"

    def test_run_returns_completed_process_shape(self, tmp_path):
        gh = fg.FakeGitHub(tmp_path / "state.json")
        result = gh.run(["issue", "list"])
        assert hasattr(result, "returncode")
        assert hasattr(result, "stdout")
        assert hasattr(result, "stderr")
        assert result.returncode == 0

    def test_different_actors_in_different_calls(self, tmp_path):
        gh = fg.FakeGitHub(tmp_path / "state.json")
        gh.run(["issue", "create", "-R", "o/r", "-t", "t"], actor="alice")
        gh.run(["issue", "comment", "1", "-R", "o/r", "-b", "hi"], actor="bob")

        rc, stdout, _ = fg.dispatch(gh.state, ["issue", "list", "-R", "o/r"], "anyone")
        issues = json.loads(stdout)
        assert issues[0]["author"]["login"] == "alice"

        comments = gh.state.comments.get("o/r", {}).get(1, [])
        assert comments[0]["author"]["login"] == "bob"

    def test_full_workflow_in_process(self, tmp_path):
        """Test a complete issue→comment→close workflow in-process."""
        gh = fg.FakeGitHub(tmp_path / "state.json")

        # Create issue
        result = gh.run(["issue", "create", "-R", "test/repo", "-t", "Build feature"], actor="user")
        assert result.returncode == 0
        issue = json.loads(result.stdout)
        issue_num = issue["number"]

        # View issue
        result = gh.run(["issue", "view", str(issue_num), "-R", "test/repo"], actor="user")
        assert result.returncode == 0
        viewed = json.loads(result.stdout)
        assert viewed["title"] == "Build feature"

        # Comment
        result = gh.run(["issue", "comment", str(issue_num), "-R", "test/repo", "-b", "Done!"], actor="user")
        assert result.returncode == 0

        # Close
        result = gh.run(["issue", "close", str(issue_num), "-R", "test/repo"], actor="user")
        assert result.returncode == 0

        # Verify closed
        result = gh.run(["issue", "view", str(issue_num), "-R", "test/repo"], actor="user")
        final = json.loads(result.stdout)
        assert final["state"] == "closed"
