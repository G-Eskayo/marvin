"""Tests for cleanup_sweep.py. Run via:
    ~/.agents/venv/bin/python -m pytest lib/tests/test_cleanup_sweep.py -v
"""
from __future__ import annotations
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

LIB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LIB))

import subprocess  # noqa: E402
import cleanup_sweep as cs  # noqa: E402


NOW = datetime(2026, 8, 19, 12, 0, 0, tzinfo=timezone.utc)


def _iso(hours_ago):
    return (NOW - timedelta(hours=hours_ago)).isoformat().replace("+00:00", "Z")


def _issue(number, labels, updated_hours_ago):
    return {"number": number, "labels": [{"name": l} for l in labels], "updatedAt": _iso(updated_hours_ago)}


@pytest.fixture
def log_path(tmp_path, monkeypatch):
    p = tmp_path / "mr-pipeline-sweep.md"
    monkeypatch.setattr(cs, "OUTPUT_PATH", p)
    return p


# ── stale claim detection ────────────────────────────────────────────────────

def test_finds_claim_stale_past_threshold():
    stale = cs.find_stale_claims(
        threshold_hours=24,
        list_claimed_open_issues=lambda: [_issue(7, ["claimed:mac-mini"], updated_hours_ago=30)],
        now=NOW,
    )
    assert len(stale) == 1
    assert stale[0]["issue_number"] == 7
    assert stale[0]["machine_id"] == "mac-mini"


def test_does_not_flag_claim_under_threshold():
    stale = cs.find_stale_claims(
        threshold_hours=24,
        list_claimed_open_issues=lambda: [_issue(7, ["claimed:mac-mini"], updated_hours_ago=2)],
        now=NOW,
    )
    assert stale == []


def test_threshold_boundary_is_exclusive():
    # exactly at threshold -- not yet stale
    at_threshold = cs.find_stale_claims(
        threshold_hours=24,
        list_claimed_open_issues=lambda: [_issue(7, ["claimed:mac-mini"], updated_hours_ago=24)],
        now=NOW,
    )
    assert at_threshold == []

    just_over = cs.find_stale_claims(
        threshold_hours=24,
        list_claimed_open_issues=lambda: [_issue(7, ["claimed:mac-mini"], updated_hours_ago=24.01)],
        now=NOW,
    )
    assert len(just_over) == 1


def test_ignores_issues_with_no_claim_label():
    stale = cs.find_stale_claims(
        threshold_hours=24,
        list_claimed_open_issues=lambda: [_issue(7, ["ready-for-agent"], updated_hours_ago=100)],
        now=NOW,
    )
    assert stale == []


def test_sweep_stale_claims_releases_via_existing_primitive():
    import ticket_claim
    released = []
    result = cs.sweep_stale_claims(
        threshold_hours=24,
        list_claimed_open_issues=lambda: [_issue(7, ["claimed:mac-mini"], updated_hours_ago=48)],
        release=lambda n, m: released.append((n, m)),
        now=NOW,
    )
    assert released == [(7, "mac-mini")]
    assert result == [{"issue_number": 7, "machine_id": "mac-mini", "age_hours": 48}]


def test_sweep_stale_claims_default_release_is_ticket_claims_release(monkeypatch):
    import ticket_claim
    calls = []
    monkeypatch.setattr(ticket_claim, "release", lambda n, m, **kw: calls.append((n, m)))
    cs.sweep_stale_claims(
        threshold_hours=24,
        list_claimed_open_issues=lambda: [_issue(7, ["claimed:mac-mini"], updated_hours_ago=48)],
        now=NOW,
    )
    assert calls == [(7, "mac-mini")]


# ── worktree decisions (multi-repo, PR-state driven) ────────────────────────
# Found 2026-10-06: nothing ever removed a resolved ticket's worktree, the sweep
# was never scheduled, and it only knew G-Eskayo/marvin -- 39 GiB of merged
# clarity-captions/marvin/finance-os worktrees on the mac-mini (94% full).

def _wt(tmp_path, name="pipeline-g-eskayo-clarity-captions-13", repo="G-Eskayo/clarity-captions",
        branch="pipeline/g-eskayo/clarity-captions#13", ahead=0, dirty=False, age_hours=48):
    p = tmp_path / name
    p.mkdir(exist_ok=True)
    return {"path": p, "branch": branch, "repo": repo, "clone": tmp_path / "clone",
            "ahead": ahead, "dirty": dirty, "age_hours": age_hours}


@pytest.mark.parametrize("pr_state", ["MERGED", "CLOSED"])
def test_resolved_pr_is_removed(tmp_path, pr_state):
    action, _ = cs.decide_worktree(_wt(tmp_path, ahead=1), pr_state=pr_state, claimed=False)
    assert action == "remove"


def test_open_pr_is_kept(tmp_path):
    action, _ = cs.decide_worktree(_wt(tmp_path, ahead=1), pr_state="OPEN", claimed=False)
    assert action == "keep"


def test_uncommitted_work_is_never_removed_even_when_merged(tmp_path):
    action, reason = cs.decide_worktree(_wt(tmp_path, dirty=True), pr_state="MERGED", claimed=False)
    assert action == "review"
    assert "uncommitted" in reason


def test_commits_without_a_pr_are_kept_for_review(tmp_path):
    action, reason = cs.decide_worktree(_wt(tmp_path, ahead=2), pr_state=None, claimed=False)
    assert action == "review"
    assert "no PR" in reason


def test_empty_old_attempt_with_no_pr_is_removed(tmp_path):
    action, _ = cs.decide_worktree(_wt(tmp_path, ahead=0, age_hours=48), pr_state=None, claimed=False)
    assert action == "remove"


def test_a_ticket_that_just_started_is_not_mistaken_for_empty(tmp_path):
    # A fresh worktree has no PR, no commits, no changes -- exactly like an abandoned one.
    young = cs.decide_worktree(_wt(tmp_path, age_hours=2), pr_state=None, claimed=False)
    claimed = cs.decide_worktree(_wt(tmp_path, age_hours=48), pr_state=None, claimed=True)
    assert young[0] == "keep"
    assert claimed[0] == "keep"


def test_unknown_repo_is_kept(tmp_path):
    action, _ = cs.decide_worktree(_wt(tmp_path, repo=None), pr_state=None, claimed=False)
    assert action == "keep"


def test_issue_number_comes_from_the_branch():
    assert cs._extract_issue_number("pipeline/g-eskayo/marvin#7") == 7
    assert cs._extract_issue_number("pipeline/g-eskayo/clarity-captions#123") == 123
    assert cs._extract_issue_number("not-a-pipeline-branch") is None


def test_sweep_looks_up_each_worktree_in_its_own_repo(tmp_path):
    a = _wt(tmp_path)
    b = _wt(tmp_path, name="pipeline-g-eskayo-marvin-7", repo="G-Eskayo/marvin", branch="pipeline/g-eskayo/marvin#7")
    asked, removed = [], []

    def pr_state(repo, branch):
        asked.append((repo, branch))
        return {"G-Eskayo/clarity-captions": "MERGED", "G-Eskayo/marvin": "OPEN"}[repo]

    result = cs.sweep_worktrees(
        list_worktrees=lambda: [a, b],
        pr_state=pr_state,
        is_claimed=lambda repo, n: False,
        remove_worktree=lambda wt: removed.append(wt["path"]) or True,
    )
    assert ("G-Eskayo/clarity-captions", "pipeline/g-eskayo/clarity-captions#13") in asked
    assert ("G-Eskayo/marvin", "pipeline/g-eskayo/marvin#7") in asked
    assert removed == [a["path"]]
    assert [r["path"] for r in result["removed"]] == [a["path"]]


def test_sweep_reports_items_needing_review_and_failed_removals(tmp_path):
    dirty = _wt(tmp_path, dirty=True)
    stuck = _wt(tmp_path, name="pipeline-g-eskayo-marvin-8", repo="G-Eskayo/marvin", branch="pipeline/g-eskayo/marvin#8")
    result = cs.sweep_worktrees(
        list_worktrees=lambda: [dirty, stuck],
        pr_state=lambda repo, branch: "MERGED",
        is_claimed=lambda repo, n: False,
        remove_worktree=lambda wt: False,  # git refused
    )
    assert [r["path"] for r in result["review"]] == [dirty["path"], stuck["path"]]
    assert result["removed"] == []


def test_default_remove_is_lossless(tmp_path):
    """Plain `git worktree remove` (never --force) and the branch is kept, so an
    untracked file makes git refuse and a commit stays reachable."""
    import subprocess
    repo = tmp_path / "repo"
    subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], check=True)
    git = lambda *a, cwd=repo: subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *a], cwd=cwd,
                                              check=True, capture_output=True)
    (repo / "f").write_text("1")
    git("add", ".")
    git("commit", "-qm", "i")
    wt_path = tmp_path / "wts" / "pipeline-x-7"
    git("worktree", "add", "-q", "-b", "pipeline/x#7", str(wt_path))
    (wt_path / "g").write_text("2")
    git("add", ".", cwd=wt_path)
    git("commit", "-qm", "work", cwd=wt_path)
    (wt_path / "untracked.txt").write_text("keep me")

    wt = {"path": wt_path, "branch": "pipeline/x#7", "clone": repo}
    assert cs._default_remove_worktree(wt) is False
    assert (wt_path / "untracked.txt").exists()

    (wt_path / "untracked.txt").unlink()
    assert cs._default_remove_worktree(wt) is True
    assert not wt_path.exists()
    branches = subprocess.run(["git", "branch", "--list", "pipeline/x#7"], cwd=repo, capture_output=True, text=True).stdout
    assert "pipeline/x#7" in branches


def test_lists_real_worktrees_with_repo_and_state(tmp_path, monkeypatch):
    import subprocess
    origin = tmp_path / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(origin)], check=True)
    clone = tmp_path / "clone"
    subprocess.run(["git", "clone", "-q", str(origin), str(clone)], check=True, capture_output=True)
    subprocess.run(["git", "remote", "set-url", "origin", "https://github.com/G-Eskayo/clarity-captions.git"], cwd=clone, check=True)
    git = lambda *a, cwd=clone: subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *a], cwd=cwd,
                                               check=True, capture_output=True)
    (clone / "f").write_text("1")
    git("add", ".")
    git("commit", "-qm", "i")
    git("update-ref", "refs/remotes/origin/main", "HEAD")
    root = tmp_path / "wts"
    git("worktree", "add", "-q", "-b", "pipeline/g-eskayo/clarity-captions#13", str(root / "pipeline-g-eskayo-clarity-captions-13"))
    (root / "pipeline-g-eskayo-clarity-captions-13" / "new.txt").write_text("x")
    (root / "not-a-git-dir").mkdir()
    monkeypatch.setattr(cs, "WORKTREES_ROOT", root)

    [wt] = cs._default_list_worktrees()
    assert wt["repo"] == "G-Eskayo/clarity-captions"
    assert wt["branch"] == "pipeline/g-eskayo/clarity-captions#13"
    assert wt["clone"].resolve() == clone.resolve()
    assert wt["ahead"] == 0
    assert wt["dirty"] is True
    assert wt["age_hours"] < 1


# ── logging (visibility standard matching cron_health.py) ──────────────────

def test_run_daily_sweep_writes_log(log_path, tmp_path):
    wt = _wt(tmp_path, dirty=True)
    cs.run_daily_sweep(
        list_claimed_open_issues=lambda: [_issue(7, ["claimed:mac-mini"], updated_hours_ago=48)],
        list_worktrees=lambda: [wt],
        pr_state=lambda repo, branch: None,
        is_claimed=lambda repo, n: False,
        release=lambda n, m: None,
        remove_worktree=lambda w: True,
        now=NOW,
    )
    content = log_path.read_text()
    assert "#7" in content and "mac-mini" in content
    assert "uncommitted" in content and str(wt["path"]) in content


def test_run_daily_sweep_logs_nothing_removed_when_all_clean(log_path):
    cs.run_daily_sweep(list_claimed_open_issues=lambda: [], list_worktrees=lambda: [], now=NOW)
    assert "nothing" in log_path.read_text().lower()


def test_run_daily_sweep_returns_summary_dict(log_path, tmp_path):
    result = cs.run_daily_sweep(
        list_claimed_open_issues=lambda: [_issue(7, ["claimed:mac-mini"], updated_hours_ago=48)],
        list_worktrees=lambda: [_wt(tmp_path)],
        pr_state=lambda repo, branch: "MERGED",
        is_claimed=lambda repo, n: False,
        release=lambda n, m: None,
        remove_worktree=lambda w: True,
        now=NOW,
    )
    assert result["stale_claims_released"] == 1
    assert result["worktrees_removed"] == 1
    assert result["worktrees_for_review"] == 0


def test_a_failing_worktree_add_says_why(monkeypatch, tmp_path):
    import sandbox_orchestration as so
    """The failure used to surface as 'returned non-zero exit status 128' with git's message thrown away."""
    import subprocess as sp
    from types import SimpleNamespace
    real = sp.run

    def fake(cmd, **kw):
        if cmd[:3] == ["git", "worktree", "add"]:
            return SimpleNamespace(returncode=128, stdout="", stderr="fatal: invalid reference: origin/main\n")
        return real(cmd, **kw)

    monkeypatch.setattr(so, "_fetch_base", lambda *a, **k: None)
    monkeypatch.setattr(so, "_preserve_prior_attempt", lambda *a, **k: None)
    monkeypatch.setattr(so, "WORKTREES_ROOT", tmp_path / "wts")
    monkeypatch.setattr(so.subprocess, "run", fake)
    try:
        so._create_worktree(tmp_path, "G-Eskayo/marvin#9")
    except RuntimeError as e:
        assert "invalid reference: origin/main" in str(e) and "128" in str(e)
    else:
        raise AssertionError("expected a RuntimeError")


# ── build output: found 2026-10-06 each clarity worktree holding 2.1 GiB of SwiftPM .build and each
# marvin worktree 0.3 GiB of dashboard/node_modules for as long as its PR stayed open.

def _git_worktree(tmp_path):
    wt = tmp_path / "wt"
    wt.mkdir()
    subprocess.run(["git", "init", "-q", str(wt)], check=True)
    (wt / ".gitignore").write_text("node_modules/\n.build/\n")
    return wt


def test_drop_build_output_removes_ignored_build_dirs(tmp_path):
    wt = _git_worktree(tmp_path)
    (wt / "dashboard" / "node_modules" / "pkg").mkdir(parents=True)
    (wt / "dashboard" / "node_modules" / "pkg" / "index.js").write_text("x")
    (wt / "dashboard" / "src").mkdir()
    (wt / "dashboard" / "src" / "app.js").write_text("keep")
    removed = cs.drop_build_output(wt, ["dashboard/node_modules", "Packages/CaptionCore/.build"])
    assert removed == ["dashboard/node_modules"]
    assert not (wt / "dashboard" / "node_modules").exists()
    assert (wt / "dashboard" / "src" / "app.js").read_text() == "keep"


def test_drop_build_output_unlinks_a_symlink_without_touching_its_target(tmp_path):
    cache = tmp_path / "shared-cache"
    (cache / "pkg").mkdir(parents=True)
    wt = _git_worktree(tmp_path)
    (wt / "dashboard").mkdir()
    (wt / "dashboard" / "node_modules").symlink_to(cache)
    assert cs.drop_build_output(wt, ["dashboard/node_modules"]) == ["dashboard/node_modules"]
    assert not (wt / "dashboard" / "node_modules").is_symlink()
    assert (cache / "pkg").is_dir()


def test_drop_build_output_refuses_a_path_git_does_not_ignore(tmp_path):
    wt = _git_worktree(tmp_path)
    (wt / "src").mkdir()
    (wt / "src" / "real.py").write_text("work")
    assert cs.drop_build_output(wt, ["src"]) == []
    assert (wt / "src" / "real.py").exists()


def test_drop_build_output_refuses_paths_outside_the_worktree(tmp_path):
    wt = _git_worktree(tmp_path)
    outside = tmp_path / "node_modules"
    outside.mkdir()
    assert cs.drop_build_output(wt, ["../node_modules", str(outside)]) == []
    assert outside.is_dir()
