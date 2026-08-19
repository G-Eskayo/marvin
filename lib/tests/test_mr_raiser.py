"""Tests for mr_raiser.py. Run via:
    ~/.agents/venv/bin/python -m pytest lib/tests/test_mr_raiser.py -v
"""
from __future__ import annotations
import subprocess
import sys
from pathlib import Path

import pytest

LIB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LIB))

import mr_raiser as mrr  # noqa: E402


def _run(cmd, cwd):
    subprocess.run(cmd, cwd=cwd, check=True, capture_output=True)


@pytest.fixture
def repo_with_worktree(tmp_path):
    """A bare 'origin' remote, a main-repo clone with one commit, and a
    worktree branched off it with an uncommitted change -- mirrors what
    sandbox_orchestration.execute_ticket leaves behind."""
    origin = tmp_path / "origin.git"
    origin.mkdir()
    _run(["git", "init", "-q", "--bare"], cwd=origin)

    main_repo = tmp_path / "main-repo"
    main_repo.mkdir()
    _run(["git", "init", "-q"], cwd=main_repo)
    _run(["git", "config", "user.email", "test@test.com"], cwd=main_repo)
    _run(["git", "config", "user.name", "Test"], cwd=main_repo)
    (main_repo / "README.md").write_text("hello\n")
    _run(["git", "add", "."], cwd=main_repo)
    _run(["git", "commit", "-q", "-m", "init"], cwd=main_repo)
    _run(["git", "branch", "-M", "main"], cwd=main_repo)
    _run(["git", "remote", "add", "origin", str(origin)], cwd=main_repo)
    _run(["git", "push", "-u", "origin", "main"], cwd=main_repo)

    worktree = tmp_path / "worktree"
    _run(["git", "worktree", "add", "-b", "pipeline/ticket-1", str(worktree)], cwd=main_repo)
    (worktree / "new_file.txt").write_text("a change\n")

    return worktree


def _passing_result(worktree_path):
    return {
        "passing": True,
        "worktree_path": worktree_path,
        "iterations": 2,
        "final_comparison": {
            "subsystem": "test-subsystem",
            "verdict": "improved",
            "passing": True,
            "metrics": {"accuracy": {"baseline": 0.70, "current": 0.90, "delta": 0.20, "direction": "improved"}},
        },
        "explanation": None,
    }


def _failing_result(worktree_path):
    return {
        "passing": False,
        "worktree_path": worktree_path,
        "iterations": 3,
        "final_comparison": {"subsystem": "test-subsystem", "verdict": "regressed", "passing": False, "metrics": {}},
        "explanation": "Did not reach a passing comparison after 3 iterations.",
    }


# ── passing gate ─────────────────────────────────────────────────────────────

def test_skips_when_execution_result_not_passing(repo_with_worktree):
    calls = {"open_pr": 0, "comment": 0}

    result = mrr.raise_mr(
        "G-Eskayo/marvin#1", _failing_result(repo_with_worktree),
        open_pr=lambda *a: calls.__setitem__("open_pr", calls["open_pr"] + 1) or "http://fake",
        comment_on_ticket=lambda *a: calls.__setitem__("comment", calls["comment"] + 1),
    )
    assert result["raised"] is False
    assert result["pr_url"] is None
    assert result["reason"]
    assert calls["open_pr"] == 0
    assert calls["comment"] == 0


def test_no_git_operations_happen_when_not_passing(repo_with_worktree):
    # branch should not have been pushed to origin
    mrr.raise_mr(
        "G-Eskayo/marvin#1", _failing_result(repo_with_worktree),
        open_pr=lambda *a: "http://fake", comment_on_ticket=lambda *a: None,
    )
    ls_remote = subprocess.run(
        ["git", "ls-remote", "--heads", "origin", "pipeline/ticket-1"],
        cwd=repo_with_worktree, capture_output=True, text=True,
    )
    assert ls_remote.stdout.strip() == ""


# ── commit + push ────────────────────────────────────────────────────────────

def test_commits_and_pushes_branch_when_passing(repo_with_worktree):
    mrr.raise_mr(
        "G-Eskayo/marvin#1", _passing_result(repo_with_worktree),
        open_pr=lambda *a: "http://fake-pr", comment_on_ticket=lambda *a: None, notify=lambda *a: None,
    )
    ls_remote = subprocess.run(
        ["git", "ls-remote", "--heads", "origin", "pipeline/ticket-1"],
        cwd=repo_with_worktree, capture_output=True, text=True,
    )
    assert "pipeline/ticket-1" in ls_remote.stdout


def test_no_error_when_worktree_already_committed(repo_with_worktree):
    _run(["git", "add", "."], cwd=repo_with_worktree)
    _run(["git", "commit", "-q", "-m", "pre-committed"], cwd=repo_with_worktree)
    result = mrr.raise_mr(
        "G-Eskayo/marvin#1", _passing_result(repo_with_worktree),
        open_pr=lambda *a: "http://fake-pr", comment_on_ticket=lambda *a: None, notify=lambda *a: None,
    )
    assert result["raised"] is True


# ── open_pr / comment_on_ticket hooks ───────────────────────────────────────

def test_open_pr_called_with_ticket_branch_and_comparison(repo_with_worktree):
    captured = {}

    def open_pr(ticket_ref, branch, comparison):
        captured["ticket_ref"] = ticket_ref
        captured["branch"] = branch
        captured["comparison"] = comparison
        return "http://fake-pr"

    mrr.raise_mr(
        "G-Eskayo/marvin#1", _passing_result(repo_with_worktree),
        open_pr=open_pr, comment_on_ticket=lambda *a: None, notify=lambda *a: None,
    )
    assert captured["ticket_ref"] == "G-Eskayo/marvin#1"
    assert captured["branch"] == "pipeline/ticket-1"
    assert captured["comparison"]["verdict"] == "improved"


def test_comment_on_ticket_called_with_ticket_and_pr_url(repo_with_worktree):
    captured = {}

    mrr.raise_mr(
        "G-Eskayo/marvin#1", _passing_result(repo_with_worktree),
        open_pr=lambda *a: "http://fake-pr-url",
        comment_on_ticket=lambda ticket_ref, pr_url: captured.update(ticket_ref=ticket_ref, pr_url=pr_url),
        notify=lambda *a: None,
    )
    assert captured["ticket_ref"] == "G-Eskayo/marvin#1"
    assert captured["pr_url"] == "http://fake-pr-url"


def test_returns_raised_true_with_pr_url_on_success(repo_with_worktree):
    result = mrr.raise_mr(
        "G-Eskayo/marvin#1", _passing_result(repo_with_worktree),
        open_pr=lambda *a: "http://fake-pr-url", comment_on_ticket=lambda *a: None, notify=lambda *a: None,
    )
    assert result["raised"] is True
    assert result["pr_url"] == "http://fake-pr-url"
    assert result["reason"] is None


# ── notify hook (G-Eskayo/marvin#5) ─────────────────────────────────────────

def test_notify_called_with_ticket_and_pr_url_on_success(repo_with_worktree):
    captured = {}

    mrr.raise_mr(
        "G-Eskayo/marvin#1", _passing_result(repo_with_worktree),
        open_pr=lambda *a: "http://fake-pr-url", comment_on_ticket=lambda *a: None,
        notify=lambda ticket_ref, pr_url: captured.update(ticket_ref=ticket_ref, pr_url=pr_url),
    )
    assert captured["ticket_ref"] == "G-Eskayo/marvin#1"
    assert captured["pr_url"] == "http://fake-pr-url"


def test_notify_not_called_when_not_passing(repo_with_worktree):
    calls = []
    mrr.raise_mr(
        "G-Eskayo/marvin#1", _failing_result(repo_with_worktree),
        open_pr=lambda *a: "http://fake", comment_on_ticket=lambda *a: None,
        notify=lambda *a: calls.append(a),
    )
    assert calls == []


# ── default gh-backed hooks (mocked subprocess, no real API calls) ──────────

def test_default_open_pr_includes_ticket_and_comparison_in_body(monkeypatch):
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        class R:
            stdout = "https://github.com/G-Eskayo/marvin/pull/99\n"
            returncode = 0
        return R()

    monkeypatch.setattr(mrr.subprocess, "run", fake_run)
    comparison = {"subsystem": "route-classifier", "verdict": "improved", "metrics": {
        "accuracy": {"baseline": 0.70, "current": 0.90, "delta": 0.20, "direction": "improved"}
    }}
    url = mrr._default_open_pr("G-Eskayo/marvin#1", "pipeline/ticket-1", comparison)

    assert url == "https://github.com/G-Eskayo/marvin/pull/99"
    cmd = calls[0]
    assert "pr" in cmd and "create" in cmd
    body = cmd[cmd.index("--body") + 1]
    assert "G-Eskayo/marvin#1" in body
    assert "route-classifier" in body
    assert "0.9" in body


def test_default_comment_on_ticket_posts_to_correct_issue(monkeypatch):
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        class R:
            stdout = ""
            returncode = 0
        return R()

    monkeypatch.setattr(mrr.subprocess, "run", fake_run)
    mrr._default_comment_on_ticket("G-Eskayo/marvin#1", "https://github.com/G-Eskayo/marvin/pull/99")

    cmd = calls[0]
    assert "issue" in cmd and "comment" in cmd
    assert "1" in cmd
    body = cmd[cmd.index("--body") + 1]
    assert "99" in body or "pull/99" in body
