"""Tests for mr_mrr.py. Run via:
    ~/.agents/venv/bin/python -m pytest lib/tests/test_mr_mrr.py -v
"""
from __future__ import annotations
import subprocess
import sys
from pathlib import Path

import pytest

LIB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LIB))

import mr_raiser as mrr  # noqa: E402


@pytest.fixture(autouse=True)
def stub_machine_profile(monkeypatch):
    """Stub machine_profile.registry_id to prevent hermetic tests from shelling
    out to ioreg/sysctl/scutil or writing ~/.claude/machine-profile.json."""
    monkeypatch.setattr(mrr.machine_profile, "registry_id", lambda: "test-machine")


@pytest.fixture(autouse=True)
def stub_ticket_title(monkeypatch):
    """No test reaches the real GitHub for a ticket title; tests that care set their own."""
    monkeypatch.setattr(mrr, "_ticket_title", lambda ref: None)


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

def test_open_pr_called_with_ticket_branch_comparison_test_results_and_dev_evidence(repo_with_worktree):
    captured = {}

    def open_pr(ticket_ref, branch, comparison, test_results, dev_evidence):
        captured["ticket_ref"] = ticket_ref
        captured["branch"] = branch
        captured["comparison"] = comparison
        captured["test_results"] = test_results
        captured["dev_evidence"] = dev_evidence
        return "http://fake-pr"

    mrr.raise_mr(
        "G-Eskayo/marvin#1", _passing_result(repo_with_worktree),
        test_results={"suite": "pytest", "passed": 11, "failed": 0, "total": 11},
        dev_evidence={"na": True, "reason": "no UI"},
        open_pr=open_pr, comment_on_ticket=lambda *a: None, notify=lambda *a: None,
    )
    assert captured["ticket_ref"] == "G-Eskayo/marvin#1"
    assert captured["branch"] == "pipeline/ticket-1"
    assert captured["comparison"]["verdict"] == "improved"
    assert captured["test_results"] == {"suite": "pytest", "passed": 11, "failed": 0, "total": 11}
    assert captured["dev_evidence"] == {"na": True, "reason": "no UI"}


def test_open_pr_receives_none_test_results_and_dev_evidence_when_not_supplied(repo_with_worktree):
    captured = {}

    mrr.raise_mr(
        "G-Eskayo/marvin#1", _passing_result(repo_with_worktree),
        open_pr=lambda ticket_ref, branch, comparison, test_results, dev_evidence: captured.update(
            test_results=test_results, dev_evidence=dev_evidence
        )
        or "http://fake-pr",
        comment_on_ticket=lambda *a: None, notify=lambda *a: None,
    )
    assert captured["test_results"] is None
    assert captured["dev_evidence"] is None


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


def test_default_open_pr_body_uses_the_evidence_schema_headers(monkeypatch):
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        class R:
            stdout = "https://github.com/G-Eskayo/marvin/pull/99\n"
            returncode = 0
        return R()

    monkeypatch.setattr(mrr.subprocess, "run", fake_run)
    comparison = {"subsystem": "route-classifier", "verdict": "improved", "metrics": {}}
    mrr._default_open_pr("G-Eskayo/marvin#1", "pipeline/ticket-1", comparison)

    body = calls[0][calls[0].index("--body") + 1]
    assert "## Metrics Comparison" in body
    assert "## Test Results" in body
    assert "## Dev Environment Evidence" in body
    # order matters -- mr_review.js's section-extraction reads each section
    # up to the *next* "## " header, so getting the order wrong would
    # silently corrupt every section after the swapped one.
    assert (
        body.index("## Metrics Comparison")
        < body.index("## Test Results")
        < body.index("## Dev Environment Evidence")
    )


def test_default_open_pr_includes_device_section_when_registry_id_succeeds(monkeypatch):
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        class R:
            stdout = "https://github.com/G-Eskayo/marvin/pull/99\n"
            returncode = 0
        return R()

    monkeypatch.setattr(mrr.subprocess, "run", fake_run)
    monkeypatch.setattr(mrr.machine_profile, "registry_id", lambda: "mac-mini")
    comparison = {"subsystem": "route-classifier", "verdict": "improved", "metrics": {}}
    mrr._default_open_pr("G-Eskayo/marvin#1", "pipeline/ticket-1", comparison)

    body = calls[0][calls[0].index("--body") + 1]
    assert "## Device" in body
    assert "mac-mini" in body


def test_device_section_is_ordered_first_in_evidence_schema(monkeypatch):
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        class R:
            stdout = "https://github.com/G-Eskayo/marvin/pull/99\n"
            returncode = 0
        return R()

    monkeypatch.setattr(mrr.subprocess, "run", fake_run)
    monkeypatch.setattr(mrr.machine_profile, "registry_id", lambda: "macbook-pro")
    comparison = {"subsystem": "route-classifier", "verdict": "improved", "metrics": {}}
    mrr._default_open_pr("G-Eskayo/marvin#1", "pipeline/ticket-1", comparison)

    body = calls[0][calls[0].index("--body") + 1]
    assert (
        body.index("## Device")
        < body.index("## Metrics Comparison")
        < body.index("## Test Results")
        < body.index("## Dev Environment Evidence")
    )


def test_format_device_returns_registry_id(monkeypatch):
    monkeypatch.setattr(mrr.machine_profile, "registry_id", lambda: "test-device")
    result = mrr._format_device()
    assert result == "test-device"


def test_format_device_falls_back_when_registry_id_raises(monkeypatch):
    def raising_registry_id():
        raise Exception("Permission denied")
    monkeypatch.setattr(mrr.machine_profile, "registry_id", raising_registry_id)
    result = mrr._format_device()
    assert result == "unknown-machine"


def test_default_open_pr_still_succeeds_when_device_formatting_fails(monkeypatch):
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        class R:
            stdout = "https://github.com/G-Eskayo/marvin/pull/99\n"
            returncode = 0
        return R()

    def raising_registry_id():
        raise Exception("Registry lookup failed")

    monkeypatch.setattr(mrr.subprocess, "run", fake_run)
    monkeypatch.setattr(mrr.machine_profile, "registry_id", raising_registry_id)
    comparison = {"subsystem": "route-classifier", "verdict": "improved", "metrics": {}}
    url = mrr._default_open_pr("G-Eskayo/marvin#1", "pipeline/ticket-1", comparison)

    assert url == "https://github.com/G-Eskayo/marvin/pull/99"
    body = calls[0][calls[0].index("--body") + 1]
    assert "## Device" in body
    assert "unknown-machine" in body


def test_default_open_pr_includes_test_results_section_when_supplied(monkeypatch):
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        class R:
            stdout = "https://github.com/G-Eskayo/marvin/pull/99\n"
            returncode = 0
        return R()

    monkeypatch.setattr(mrr.subprocess, "run", fake_run)
    comparison = {"subsystem": "route-classifier", "verdict": "improved", "metrics": {}}
    test_results = {"suite": "pytest", "passed": 11, "failed": 0, "total": 11}
    mrr._default_open_pr("G-Eskayo/marvin#1", "pipeline/ticket-1", comparison, test_results)

    body = calls[0][calls[0].index("--body") + 1]
    assert "**Suite**: pytest" in body
    assert "**Passed**: 11" in body
    assert "**Failed**: 0" in body
    assert "**Total**: 11" in body


def test_default_open_pr_marks_test_results_not_available_when_missing(monkeypatch):
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        class R:
            stdout = "https://github.com/G-Eskayo/marvin/pull/99\n"
            returncode = 0
        return R()

    monkeypatch.setattr(mrr.subprocess, "run", fake_run)
    comparison = {"subsystem": "route-classifier", "verdict": "improved", "metrics": {}}
    mrr._default_open_pr("G-Eskayo/marvin#1", "pipeline/ticket-1", comparison)

    body = calls[0][calls[0].index("--body") + 1]
    assert "Not available." in body


def test_default_open_pr_marks_dev_evidence_na_for_a_non_ui_ticket(monkeypatch):
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        class R:
            stdout = "https://github.com/G-Eskayo/marvin/pull/99\n"
            returncode = 0
        return R()

    monkeypatch.setattr(mrr.subprocess, "run", fake_run)
    comparison = {"subsystem": "route-classifier", "verdict": "improved", "metrics": {}}
    mrr._default_open_pr(
        "G-Eskayo/marvin#1", "pipeline/ticket-1", comparison,
        dev_evidence={"na": True, "reason": "no UI"},
    )

    body = calls[0][calls[0].index("--body") + 1]
    assert "N/A — no UI" in body


def test_default_open_pr_includes_screenshot_reference_for_a_ui_ticket(monkeypatch):
    calls = []

    sha = "b" * 40

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        class R:
            stdout = (sha if cmd[:2] == ["gh", "api"] else "https://github.com/G-Eskayo/marvin/pull/99") + "\n"
            returncode = 0
        return R()

    monkeypatch.setattr(mrr.subprocess, "run", fake_run)
    comparison = {"subsystem": "route-classifier", "verdict": "improved", "metrics": {}}
    dev_evidence = {
        "na": False,
        "screenshot_path": "docs/evidence/pipeline-ticket-1.png",
        "description": "Live screenshot captured from the running app.",
    }
    mrr._default_open_pr("G-Eskayo/marvin#1", "pipeline/ticket-1", comparison, dev_evidence=dev_evidence)

    assert calls[0] == ["gh", "api", "repos/G-Eskayo/marvin/commits/pipeline%2Fticket-1", "-q", ".sha"]
    create = next(c for c in calls if c[:3] == ["gh", "pr", "create"])
    body = create[create.index("--body") + 1]
    # #374: a PR body can't show a repo-relative image; #735: pinned to the pushed commit, not the branch
    assert f"![Screenshot](https://raw.githubusercontent.com/G-Eskayo/marvin/{sha}/docs/evidence/pipeline-ticket-1.png)" in body
    assert "Live screenshot captured from the running app." in body


def test_default_open_pr_marks_dev_evidence_not_available_when_missing(monkeypatch):
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        class R:
            stdout = "https://github.com/G-Eskayo/marvin/pull/99\n"
            returncode = 0
        return R()

    monkeypatch.setattr(mrr.subprocess, "run", fake_run)
    comparison = {"subsystem": "route-classifier", "verdict": "improved", "metrics": {}}
    mrr._default_open_pr("G-Eskayo/marvin#1", "pipeline/ticket-1", comparison)

    body = calls[0][calls[0].index("--body") + 1]
    # both Test Results and Dev Environment Evidence fall back to this when
    # neither was supplied -- confirm it appears twice, once per section.
    assert body.count("Not available.") == 2


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


# ── other projects ──────────────────────────────────────────────────────────

def _spy_run(monkeypatch):
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        class R:
            stdout = "https://github.com/G-Eskayo/clarity-captions/pull/21\n"
            returncode = 0
        return R()

    monkeypatch.setattr(mrr.subprocess, "run", fake_run)
    return calls


def test_the_pr_is_opened_in_the_tickets_own_repo_not_wherever_the_process_happens_to_be(monkeypatch):
    calls = _spy_run(monkeypatch)
    comparison = {"subsystem": "ticket-7", "verdict": "improved", "metrics": {}}
    mrr._default_open_pr("G-Eskayo/clarity-captions#7", "pipeline/g-eskayo/clarity-captions#7", comparison)
    cmd = calls[0]
    assert cmd[cmd.index("--repo") + 1] == "G-Eskayo/clarity-captions"
    assert "Closes G-Eskayo/clarity-captions#7" in cmd[cmd.index("--body") + 1]


def test_the_ticket_comment_is_posted_on_the_tickets_own_repo(monkeypatch):
    calls = _spy_run(monkeypatch)
    mrr._default_comment_on_ticket("G-Eskayo/clarity-captions#7", "https://github.com/x/pull/1")
    cmd = calls[0]
    assert cmd[:4] == ["gh", "issue", "comment", "7"]
    assert cmd[cmd.index("--repo") + 1] == "G-Eskayo/clarity-captions"


def test_the_pr_says_what_was_not_verified():
    text = mrr._format_test_results({"suite": "Core", "passed": 60, "failed": 0, "total": 61, "notes": "App build: not verified (needs xcodegen)"})
    assert "**Suite**: Core" in text and "not verified" in text


# ── rework of a sent-back ticket ────

def test_commenting_the_new_pr_on_the_ticket_clears_needs_reengagement(monkeypatch):
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        class R:
            stdout = ""
            returncode = 0
        return R()

    monkeypatch.setattr(mrr.subprocess, "run", fake_run)
    mrr._default_comment_on_ticket("o/r#23", "https://github.com/o/r/pull/30")
    edit = [c for c in calls if "edit" in c][0]
    assert "--remove-label" in edit and "needs-reengagement" in edit


def test_pushing_over_a_stale_pipeline_branch_succeeds(repo_with_worktree):
    """A re-dispatched ticket rebuilds pipeline/<ref> from the new main while origin still holds the first
    attempt (behind its open PR). That attempt is preserved under refs/rescue/, so a lease-protected
    replace is safe; a plain push is rejected."""
    wt = repo_with_worktree
    _run(["git", "config", "user.email", "t@t.com"], cwd=wt)
    _run(["git", "config", "user.name", "T"], cwd=wt)
    (wt / "first_attempt.txt").write_text("v1\n")
    _run(["git", "add", "-A"], cwd=wt)
    _run(["git", "commit", "-q", "-m", "first attempt"], cwd=wt)
    _run(["git", "push", "-u", "origin", "pipeline/ticket-1"], cwd=wt)
    _run(["git", "fetch", "origin"], cwd=wt)  # the lease is measured against what this clone last saw
    _run(["git", "reset", "-q", "--hard", "origin/main"], cwd=wt)  # the rebuild from main
    (wt / "second_attempt.txt").write_text("v2\n")
    assert mrr._commit_and_push(wt, "G-Eskayo/marvin#1") == "pipeline/ticket-1"
    remote = subprocess.run(["git", "rev-parse", "origin/pipeline/ticket-1"], cwd=wt, capture_output=True, text=True).stdout
    assert remote == subprocess.run(["git", "rev-parse", "HEAD"], cwd=wt, capture_output=True, text=True).stdout


def test_a_non_pipeline_branch_is_never_replaced(monkeypatch):
    calls = []
    monkeypatch.setattr(mrr.subprocess, "run", lambda cmd, **kw: calls.append(cmd) or type("R", (), {"stdout": "", "returncode": 0})())
    monkeypatch.setattr(mrr, "_current_branch", lambda wt: "main")
    mrr._commit_and_push(Path("/x"), "o/r#1")
    assert not any("--force-with-lease" in c for c in calls)


def test_open_pr_updates_the_existing_pr_when_one_is_already_open_for_the_branch(monkeypatch):
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        if "create" in cmd:
            raise subprocess.CalledProcessError(1, cmd, stderr='a pull request for branch "pipeline/x" into branch "main" already exists:\nhttps://github.com/o/r/pull/30')
        return type("R", (), {"stdout": "https://github.com/o/r/pull/30\n", "returncode": 0})()

    monkeypatch.setattr(mrr.subprocess, "run", fake_run)
    url = mrr._default_open_pr("o/r#23", "pipeline/x", {"subsystem": "s", "verdict": "improved", "metrics": {}})
    assert url == "https://github.com/o/r/pull/30"
    assert any("pr" in c and "edit" in c for c in calls) and any("pr" in c and "comment" in c for c in calls)


def test_rework_retitle_includes_new_title_in_pr_edit(monkeypatch):
    """When a reworked PR is sent back and pushed to the same branch, the PR is retitled to the current _subject."""
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        if "create" in cmd:
            raise subprocess.CalledProcessError(1, cmd, stderr='a pull request for branch "pipeline/x" into branch "main" already exists:\nhttps://github.com/o/r/pull/30')
        return type("R", (), {"stdout": "https://github.com/o/r/pull/30\n", "returncode": 0})()

    monkeypatch.setattr(mrr.subprocess, "run", fake_run)
    # Stub _ticket_title so we get a resolved title, not the fallback "Implement"
    monkeypatch.setattr(mrr, "_ticket_title", lambda ref: "Fix the cache bug (o/r#23)")

    url = mrr._default_open_pr("o/r#23", "pipeline/x", {"subsystem": "s", "verdict": "improved", "metrics": {}})

    # Find the pr edit call and verify it includes both --body and --title
    edit_calls = [c for c in calls if "pr" in c and "edit" in c]
    assert len(edit_calls) == 1
    edit_cmd = edit_calls[0]
    assert "--title" in edit_cmd
    title_idx = edit_cmd.index("--title")
    title_value = edit_cmd[title_idx + 1]
    assert "Fix the cache bug" in title_value


def test_stale_title_rework_gets_new_title(monkeypatch):
    """On a second rework, the PR is retitled again if the ticket title changed."""
    calls = []
    title_calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        if "create" in cmd:
            raise subprocess.CalledProcessError(1, cmd, stderr='a pull request for branch "pipeline/x" into branch "main" already exists:\nhttps://github.com/o/r/pull/30')
        return type("R", (), {"stdout": "https://github.com/o/r/pull/30\n", "returncode": 0})()

    def fake_ticket_title(ref):
        title_calls.append(ref)
        # Simulate changed title on second call (reworked)
        return "Improved cache performance" if len(title_calls) > 1 else "Fix the cache bug"

    monkeypatch.setattr(mrr.subprocess, "run", fake_run)
    monkeypatch.setattr(mrr, "_ticket_title", fake_ticket_title)

    # First call
    mrr._default_open_pr("o/r#23", "pipeline/x", {"subsystem": "s", "verdict": "improved", "metrics": {}})
    # Second call (rework)
    mrr._default_open_pr("o/r#23", "pipeline/x", {"subsystem": "s", "verdict": "improved", "metrics": {}})

    edit_calls = [c for c in calls if "pr" in c and "edit" in c]
    assert len(edit_calls) == 2
    # Second edit should have the new title
    second_edit = edit_calls[1]
    assert "--title" in second_edit
    title_idx = second_edit.index("--title")
    title_value = second_edit[title_idx + 1]
    assert "Improved cache performance" in title_value


def test_subject_never_returns_bare_implement_without_title(monkeypatch):
    """_subject always returns "Title (#n)" form when ticket title is available."""
    monkeypatch.setattr(mrr, "_ticket_title", lambda ref: "Test ticket title")
    result = mrr._subject("o/r#23")
    assert result == "Test ticket title (#23)"
    assert not result.startswith("Implement o/r")


def test_subject_falls_back_to_implement_when_title_fetch_times_out(monkeypatch):
    """_subject falls back to 'Implement' when GitHub doesn't respond in time."""
    # Simulate a timeout during title fetch
    monkeypatch.setattr(mrr, "_ticket_title", lambda ref: None)
    result = mrr._subject("o/r#23")
    assert result == "Implement o/r#23"


def test_failed_pr_edit_on_rework_is_not_swallowed(monkeypatch):
    """If pr edit fails during rework, the error is raised, not ignored."""
    def fake_run(cmd, **kwargs):
        if "create" in cmd:
            raise subprocess.CalledProcessError(1, cmd, stderr='already exists')
        if "edit" in cmd:
            raise subprocess.CalledProcessError(1, cmd, stderr="HTTP 422: validation failed")
        return type("R", (), {"stdout": "https://github.com/o/r/pull/30\n", "returncode": 0})()

    monkeypatch.setattr(mrr.subprocess, "run", fake_run)
    monkeypatch.setattr(mrr, "_ticket_title", lambda ref: "Test title")

    with pytest.raises(subprocess.CalledProcessError):
        mrr._default_open_pr("o/r#23", "pipeline/x", {"subsystem": "s", "verdict": "v", "metrics": {}})


def test_open_pr_still_raises_on_other_gh_failures(monkeypatch):
    def fake_run(cmd, **kwargs):
        raise subprocess.CalledProcessError(1, cmd, stderr="HTTP 401 bad credentials")
    monkeypatch.setattr(mrr.subprocess, "run", fake_run)
    with pytest.raises(subprocess.CalledProcessError):
        mrr._default_open_pr("o/r#23", "pipeline/x", {"subsystem": "s", "verdict": "v", "metrics": {}})


def test_generated_files_are_left_out_of_the_pipeline_commit(repo_with_worktree, monkeypatch):
    import project_profile as pp
    wt = repo_with_worktree
    (wt / "graphify-out").mkdir()
    (wt / "graphify-out" / "graph.json").write_text("noise\n")
    monkeypatch.setattr(pp, "load_profile", lambda repo: {"generated": [{"path": "graphify-out"}]})
    mrr._commit_and_push(wt, "G-Eskayo/finance-os#3")
    files = subprocess.run(["git", "show", "--name-only", "--format=", "HEAD"], cwd=wt, capture_output=True, text=True).stdout.split()
    assert "new_file.txt" in files and "graphify-out/graph.json" not in files


def test_a_project_without_generated_rules_commits_everything_as_before(repo_with_worktree):
    wt = repo_with_worktree
    mrr._commit_and_push(wt, "G-Eskayo/marvin#1")
    assert "new_file.txt" in subprocess.run(["git", "show", "--name-only", "--format=", "HEAD"], cwd=wt, capture_output=True, text=True).stdout


def test_a_failed_push_says_what_git_said(repo_with_worktree):
    """Every macbook push died as 'returned non-zero exit status 128' with git's reason thrown away (the locked keychain,
    2026-10-07), so three attempts were burned and the ticket parked before anyone could see why."""
    wt = repo_with_worktree
    _run(["git", "config", "user.email", "t@t.com"], cwd=wt)
    _run(["git", "config", "user.name", "T"], cwd=wt)
    _run(["git", "remote", "set-url", "origin", "/nonexistent/remote.git"], cwd=wt)
    (wt / "x.txt").write_text("x\n")
    with pytest.raises(RuntimeError, match=r"git push of pipeline/ticket-1 failed.*nonexistent"):
        mrr._commit_and_push(wt, "G-Eskayo/marvin#1")


def test_a_raised_pr_gets_a_north_star_fit_check(repo_with_worktree):
    # marvin#276: every pipeline PR shows its fit next to measured facts.
    checked = []
    result = mrr.raise_mr(
        "G-Eskayo/marvin#1", _passing_result(repo_with_worktree),
        open_pr=lambda *a: "http://fake/pr/9", comment_on_ticket=lambda *a: None, notify=lambda *a: {},
        fit_check=lambda ticket, worktree, url: checked.append((ticket, worktree, url)),
    )
    assert result["raised"] is True
    assert checked == [("G-Eskayo/marvin#1", _passing_result(repo_with_worktree)["worktree_path"], "http://fake/pr/9")]


def test_a_failing_fit_check_never_blocks_the_pr(monkeypatch):
    import fit_check
    monkeypatch.setattr(fit_check, "post", lambda *a: (_ for _ in ()).throw(RuntimeError("gh down")))
    mrr._post_fit_check("G-Eskayo/marvin#1", "/nowhere", "http://fake")  # must not raise


# ── code review result on the PR (2026-10-09): the review ran in the build loop, so the PR says what it found ──

def _body_for(monkeypatch, comparison):
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        class R:
            stdout = "https://github.com/G-Eskayo/marvin/pull/99\n"
            returncode = 0
        return R()
    monkeypatch.setattr(mrr.subprocess, "run", fake_run)
    mrr._default_open_pr("G-Eskayo/marvin#1", "pipeline/ticket-1", {"subsystem": "s", "verdict": "improved",
                                                                      "metrics": {}, **comparison})
    return calls[0][calls[0].index("--body") + 1]


def test_a_clean_review_with_notes_is_shown_last_with_its_notes(monkeypatch):
    body = _body_for(monkeypatch, {"code_review": {"clean": True, "findings": [], "notes": ["a.py:1 — could cache"]}})
    assert body.index("## Dev Environment Evidence") < body.index("## Code Review")
    assert "Passed" in body and "- a.py:1 — could cache" in body


def test_a_review_that_did_not_run_says_so_plainly(monkeypatch):
    body = _body_for(monkeypatch, {"code_review": {"clean": None, "error": "judge timed out"}})
    assert "not reviewed" in body.lower() and "judge timed out" in body


def test_no_review_recorded_says_not_reviewed(monkeypatch):
    assert "not reviewed" in _body_for(monkeypatch, {}).lower()


def _head(worktree, fmt):
    return subprocess.run(["git", "log", "-1", f"--format={fmt}"], cwd=worktree, capture_output=True, text=True).stdout.strip()


def test_the_commit_says_what_it_did_not_just_which_ticket(repo_with_worktree, monkeypatch):
    monkeypatch.setattr(mrr, "_ticket_title", lambda ref: "Errors are never silent")
    mrr._commit_and_push(repo_with_worktree, "G-Eskayo/marvin#422")
    assert _head(repo_with_worktree, "%s") == "Errors are never silent (#422)"


def test_gil_is_the_author_and_marvin_the_co_author_whatever_the_repo_config_says(repo_with_worktree):
    mrr._commit_and_push(repo_with_worktree, "G-Eskayo/marvin#1")
    assert _head(repo_with_worktree, "%an <%ae>") == mrr.AUTHOR
    assert _head(repo_with_worktree, "%(trailers:key=Co-Authored-By,valueonly)") == mrr.CO_AUTHOR.split(": ", 1)[1]


def test_an_unreadable_ticket_title_still_commits_under_the_old_subject(repo_with_worktree):
    mrr._commit_and_push(repo_with_worktree, "G-Eskayo/marvin#1")
    assert _head(repo_with_worktree, "%s") == "Implement G-Eskayo/marvin#1"


def test_a_title_that_looks_like_a_flag_or_spans_lines_cannot_break_the_commit(repo_with_worktree, monkeypatch):
    monkeypatch.setattr(mrr, "_ticket_title", lambda ref: "--amend\nCo-Authored-By: Someone Else <x@y>")
    mrr._commit_and_push(repo_with_worktree, "G-Eskayo/marvin#7")
    assert _head(repo_with_worktree, "%s") == "--amend Co-Authored-By: Someone Else <x@y> (#7)"
    assert "Someone Else" not in _head(repo_with_worktree, "%(trailers:key=Co-Authored-By,valueonly)")


def test_the_pr_title_matches_the_commit_subject(monkeypatch):
    calls = _spy_run(monkeypatch)
    monkeypatch.setattr(mrr, "_ticket_title", lambda ref: "Seal Speak website")
    mrr._default_open_pr("G-Eskayo/clarity-captions#44", "pipeline/x", {"subsystem": "s", "verdict": "v", "metrics": {}})
    cmd = calls[0]
    assert cmd[cmd.index("--title") + 1] == "Seal Speak website (#44)"


def test_ticket_title_is_none_when_gh_fails(monkeypatch):
    monkeypatch.undo()
    class R:
        returncode, stdout, stderr = 1, "", "boom"
    monkeypatch.setattr(mrr.subprocess, "run", lambda *a, **k: R())
    assert mrr._ticket_title("G-Eskayo/marvin#1") is None


def test_a_box_build_commits_as_the_bot_never_as_the_owner(monkeypatch):
    # Found on the first live box build (#870 → PR #984): every pipeline commit carried the owner as author.
    import mr_raiser as mr
    monkeypatch.delenv("MARVIN_BOX_BUILD", raising=False)
    assert mr._author_args() == [f"--author={mr.AUTHOR}"]
    for value in ("1",):
        monkeypatch.setenv("MARVIN_BOX_BUILD", value)
        assert mr._author_args() == []
    monkeypatch.setenv("MARVIN_BOX_BUILD", "0")
    assert mr._author_args() == [f"--author={mr.AUTHOR}"]
