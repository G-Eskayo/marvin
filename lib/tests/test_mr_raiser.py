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
    assert "## Device" in body
    assert "## Metrics Comparison" in body
    assert "## Test Results" in body
    assert "## Dev Environment Evidence" in body
    # order matters -- mr_review.js's section-extraction reads each section
    # up to the *next* "## " header, so getting the order wrong would
    # silently corrupt every section after the swapped one.
    assert (
        body.index("## Device")
        < body.index("## Metrics Comparison")
        < body.index("## Test Results")
        < body.index("## Dev Environment Evidence")
    )


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

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        class R:
            stdout = "https://github.com/G-Eskayo/marvin/pull/99\n"
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

    body = calls[0][calls[0].index("--body") + 1]
    assert "![Screenshot](docs/evidence/pipeline-ticket-1.png)" in body
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


def test_default_open_pr_includes_device_in_body(monkeypatch):
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
