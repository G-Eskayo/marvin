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


@pytest.fixture(autouse=True)
def no_real_simulators(monkeypatch):
    """No test may list or delete this Mac's real simulators; simulator tests inject their own."""
    monkeypatch.setattr(cs, "_default_list_simulators", lambda: [])
    monkeypatch.setattr(cs, "_default_delete_simulator", lambda sim: pytest.fail(f"tried to delete a real simulator: {sim}"))


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


def test_uncommitted_work_is_backed_up_never_plainly_removed_even_when_merged(tmp_path):
    # #629: "needs a look" was never looked at (43 worktrees, 11.8 GiB). Leftover edits go to a backup branch first.
    action, reason = cs.decide_worktree(_wt(tmp_path, dirty=True), pr_state="MERGED", claimed=False)
    assert action == "backup"
    assert "uncommitted" in reason


def test_commits_without_a_pr_are_backed_up(tmp_path):
    action, reason = cs.decide_worktree(_wt(tmp_path, ahead=2), pr_state=None, claimed=False)
    assert action == "backup"
    assert "no PR" in reason


def test_recent_leftover_work_is_left_alone_for_now(tmp_path):
    # A helper may still be working in it: only idle worktrees are backed up.
    action, reason = cs.decide_worktree(_wt(tmp_path, dirty=True, age_hours=cs.BACKUP_MIN_AGE_HOURS - 1),
                                        pr_state=None, claimed=False)
    assert action == "review"
    assert "uncommitted" in reason


@pytest.mark.parametrize("why", ["claimed", "open_pr", "in_use"])
def test_leftover_work_that_something_still_owns_is_never_touched(tmp_path, why):
    wt = _wt(tmp_path, dirty=True, ahead=1, age_hours=500)
    if why == "in_use":
        wt["in_use"] = True
    action, _ = cs.decide_worktree(wt, pr_state="OPEN" if why == "open_pr" else None, claimed=why == "claimed")
    assert action in ("keep", "review")


def test_a_process_inside_a_clean_merged_worktree_keeps_it(tmp_path):
    wt = _wt(tmp_path, age_hours=500)
    wt["in_use"] = True
    assert cs.decide_worktree(wt, pr_state="MERGED", claimed=False)[0] == "keep"


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
    dirty = _wt(tmp_path, dirty=True, age_hours=1)
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
    monkeypatch.setattr(cs, "worktree_roots", lambda: [root])  # never the real ~/Developer
    monkeypatch.setattr(cs, "_cwds_in_use", lambda: set())

    [wt] = cs._default_list_worktrees()
    assert wt["repo"] == "G-Eskayo/clarity-captions"
    assert wt["branch"] == "pipeline/g-eskayo/clarity-captions#13"
    assert wt["clone"].resolve() == clone.resolve()
    assert wt["ahead"] == 0
    assert wt["dirty"] is True
    assert wt["age_hours"] < 1
    assert wt["in_use"] is False


# ── logging (visibility standard matching cron_health.py) ──────────────────

def test_run_daily_sweep_writes_log(log_path, tmp_path):
    wt = _wt(tmp_path, dirty=True, age_hours=1)
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


# ── simulators (ADR 0065: a builder's simulator is disposable once its ticket is done) ──

STOCK = {"iPhone 17 Pro", "iPhone 17", "iPad Pro 13-inch (M5)", "iPad (A16)"}


def _sim(name, state="Shutdown", udid=None):
    return {"name": name, "udid": udid or f"U-{name}", "state": state}


def test_a_simulator_named_for_a_merged_ticket_is_removed_even_while_booted():
    """Seal-118 ran for four days after clarity-captions #118 merged (2026-10-14)."""
    action, _ = cs.decide_simulator(_sim("Seal-118", "Booted"), STOCK, ticket_open=lambda n: False)
    assert action == "remove"


def test_a_simulator_whose_ticket_is_still_open_somewhere_is_kept():
    action, _ = cs.decide_simulator(_sim("Seal-118"), STOCK, ticket_open=lambda n: True)
    assert action == "keep"


def test_xcodes_own_devices_are_never_touched_even_though_their_names_end_in_numbers():
    for name in STOCK:
        action, _ = cs.decide_simulator(_sim(name), STOCK, ticket_open=lambda n: False)
        assert action == "keep", name


def test_a_simulator_the_sweep_cannot_tie_to_a_ticket_is_reported_not_deleted():
    action, _ = cs.decide_simulator(_sim("My test phone"), STOCK, ticket_open=lambda n: False)
    assert action == "review"


def test_a_leftover_capture_simulator_is_removed_once_it_is_shut_down():
    assert cs.decide_simulator(_sim("marvin-1a2b3c4d"), STOCK, ticket_open=lambda n: True)[0] == "remove"
    assert cs.decide_simulator(_sim("marvin-1a2b3c4d", "Booted"), STOCK, ticket_open=lambda n: True)[0] == "keep"


def test_a_github_failure_never_reads_as_ticket_closed():
    def boom(n):
        raise RuntimeError("gh: rate limited")
    removed = []
    out = cs.sweep_simulators(list_simulators=lambda: [_sim("Seal-118", "Booted")], stock_names=lambda: STOCK,
                              ticket_open=boom, delete_simulator=lambda s: removed.append(s) or True)
    assert removed == [] and out["review"][0]["name"] == "Seal-118"


def test_the_sweep_deletes_only_what_it_decided_to_remove():
    sims = [_sim("Seal-118", "Booted"), _sim("Seal-140"), _sim("iPhone 17 Pro", "Booted"), _sim("Scratch")]
    deleted = []
    out = cs.sweep_simulators(list_simulators=lambda: sims, stock_names=lambda: STOCK,
                              ticket_open=lambda n: n == 140, delete_simulator=lambda s: deleted.append(s["name"]) or True)
    assert deleted == ["Seal-118"]
    assert [s["name"] for s in out["removed"]] == ["Seal-118"]
    assert [s["name"] for s in out["review"]] == ["Scratch"]


def test_no_stock_list_means_nothing_is_deleted():
    """If simctl can't say which devices are Xcode's own, every name ending in a number looks like a ticket."""
    deleted = []
    out = cs.sweep_simulators(list_simulators=lambda: [_sim("iPhone 17")], stock_names=lambda: set(),
                              ticket_open=lambda n: False, delete_simulator=lambda s: deleted.append(s) or True)
    assert deleted == [] and out["removed"] == []


def test_ticket_open_checks_every_project_and_counts_open_anywhere_as_open(monkeypatch):
    seen = []
    def state(repo, n):
        seen.append(repo)
        return {"G-Eskayo/a": "CLOSED", "G-Eskayo/b": "OPEN"}[repo]
    assert cs._ticket_open_anywhere(118, repos=["G-Eskayo/a", "G-Eskayo/b"], issue_state=state) is True
    assert cs._ticket_open_anywhere(118, repos=["G-Eskayo/a"], issue_state=state) is False


def test_a_number_that_is_not_an_issue_in_any_project_counts_as_open():
    """No such ticket anywhere: the name only looks like a ticket, so leave it for a person."""
    assert cs._ticket_open_anywhere(9999, repos=["G-Eskayo/a"], issue_state=lambda r, n: None) is True


def test_the_nightly_outcome_check_also_runs_ticket_promotion_on_the_mini(monkeypatch):
    """A second, older copy of _default_outcome_check overrode #305's, so promotion never ran (found 2026-10-14)."""
    import types
    monkeypatch.undo()  # conftest stubs _default_outcome_check for every test, which is how the duplicate hid
    calls = []
    monkeypatch.setitem(sys.modules, "machine_profile", types.SimpleNamespace(registry_id=lambda: cs.OUTCOME_CHECK_MACHINE))
    monkeypatch.setitem(sys.modules, "purpose_metrics", types.SimpleNamespace(run=lambda: calls.append("metrics")))
    monkeypatch.setitem(sys.modules, "output_contracts", types.SimpleNamespace(run_promotion=lambda: calls.append("promotion")))
    cs._default_outcome_check()
    assert calls == ["metrics", "promotion"]


def test_the_sweep_log_says_what_compression_did(tmp_path, monkeypatch):
    monkeypatch.setattr(cs, "OUTPUT_PATH", tmp_path / "sweep.md")
    cs._write_log([], {"removed": [], "review": []}, None,
                  {"compressed": [{"path": Path("a"), "saved_kb": 2048}], "failed": [{"path": Path("b"), "reason": "afsctool refused"}],
                   "saved_kb": 2048, "skipped": None})
    log = (tmp_path / "sweep.md").read_text()
    assert "Compressed 1 cold transcript(s), 2 MiB saved" in log and "afsctool refused" in log


def test_the_sweep_log_says_when_compression_was_skipped(tmp_path, monkeypatch):
    monkeypatch.setattr(cs, "OUTPUT_PATH", tmp_path / "sweep.md")
    cs._write_log([], {"removed": [], "review": []}, None, {"compressed": [], "failed": [], "saved_kb": 0, "skipped": "afsctool not installed"})
    assert "Transcript compression skipped: afsctool not installed" in (tmp_path / "sweep.md").read_text()


def test_no_xcrun_means_no_simulators_not_a_failed_sweep(monkeypatch):
    # mac-mini-2012 runs Linux: no Xcode is a normal state, not something that "needs a look" (ADR 0069).
    import cleanup_sweep as cs
    monkeypatch.setattr(cs.shutil, "which", lambda name: None)
    monkeypatch.setattr(cs.subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(FileNotFoundError("xcrun")))
    assert cs._simctl_json("devices") == {}


def test_a_machine_without_xcode_has_no_simulators_to_review(monkeypatch):
    # mac-mini-2012 runs Linux: "needs a look" every day for simulators that can't exist is noise (ADR 0069).
    import cleanup_sweep as cs
    monkeypatch.setattr(cs.shutil, "which", lambda name: None)
    assert cs.sweep_simulators() == {"removed": [], "review": []}


def test_a_second_sweep_while_one_is_running_skips_at_once(monkeypatch, tmp_path):
    """#586: a sweep stuck in a size walk must not have tomorrow's launchd run queue up behind it."""
    import fcntl
    import subprocess as sp
    lock = tmp_path / "cleanup-sweep.lock"
    monkeypatch.setattr(cs, "LOCK_PATH", lock)
    monkeypatch.setattr(cs, "run_daily_sweep", lambda: pytest.fail("swept while another sweep held the lock"))
    holder = sp.Popen([sys.executable, "-c", f"import fcntl,time; f=open({str(lock)!r},'a'); "
                       f"fcntl.flock(f, fcntl.LOCK_EX); print('held', flush=True); time.sleep(30)"],
                      stdout=sp.PIPE, text=True)
    try:
        assert holder.stdout.readline().strip() == "held"
        assert cs.main() == {"busy": True}
    finally:
        holder.kill()
        holder.wait()
    monkeypatch.setattr(cs, "run_daily_sweep", lambda: {"ok": 1})
    assert cs.main() == {"ok": 1}, "the lock outlived the process that held it"


# ── #629: back up leftover edits to a branch, then remove (real git) ───────

def _origin_clone_wt(tmp_path, branch="pipeline/g-eskayo/marvin#57", name="pipeline-g-eskayo-marvin-57"):
    import subprocess
    origin = tmp_path / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(origin)], check=True)
    clone = tmp_path / "clone"
    subprocess.run(["git", "clone", "-q", str(origin), str(clone)], check=True, capture_output=True)
    git = lambda *a, cwd=clone: subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *a], cwd=cwd,
                                               check=True, capture_output=True, text=True)
    (clone / ".gitignore").write_text(".build/\n")
    (clone / "f").write_text("1")
    git("add", ".")
    git("commit", "-qm", "i")
    git("push", "-q", "origin", "main")
    wt_path = tmp_path / "wts" / name
    git("worktree", "add", "-q", "-b", branch, str(wt_path))
    return origin, clone, wt_path, git


def test_backup_pushes_every_leftover_edit_to_a_backup_branch_then_removal_succeeds(tmp_path):
    origin, clone, wt_path, git = _origin_clone_wt(tmp_path)
    (wt_path / "f").write_text("edited")
    (wt_path / "new.py").write_text("print('only copy')")
    (wt_path / ".build").mkdir()
    (wt_path / ".build" / "big.o").write_text("x" * 100)
    wt = {"path": wt_path, "branch": "pipeline/g-eskayo/marvin#57", "clone": clone}

    ref = cs.backup_worktree(wt, today="20261024", guard=lambda *a: True)
    assert ref == "backup/pipeline/g-eskayo/marvin#57-20261024"
    # the backup on origin holds both edits and not the ignored build output
    show = lambda path: git("--git-dir", str(origin), "show", f"{ref}:{path}", cwd=tmp_path).stdout
    assert show("f") == "edited"
    assert show("new.py") == "print('only copy')"
    listed = git("--git-dir", str(origin), "ls-tree", "-r", "--name-only", ref, cwd=tmp_path).stdout
    assert ".build" not in listed
    assert cs._default_remove_worktree(wt) is True
    assert not wt_path.exists()


def test_a_failed_push_means_no_backup_and_nothing_removed(tmp_path):
    origin, clone, wt_path, git = _origin_clone_wt(tmp_path)
    (wt_path / "new.py").write_text("only copy")
    git("remote", "set-url", "origin", str(tmp_path / "gone.git"), cwd=clone)
    wt = {"path": wt_path, "branch": "pipeline/g-eskayo/marvin#57", "clone": clone}
    removed = []
    result = cs.sweep_worktrees(
        list_worktrees=lambda: [{**wt, "repo": "G-Eskayo/marvin", "ahead": 0, "dirty": True, "age_hours": 500}],
        pr_state=lambda repo, branch: None,
        is_claimed=lambda repo, n: False,
        remove_worktree=lambda w: removed.append(w) or True,
        backup=lambda w: cs.backup_worktree(w, today="20261024", guard=lambda *a: True),
    )
    assert removed == []
    assert result["removed"] == []
    assert "backup failed" in result["review"][0]["reason"]
    assert (wt_path / "new.py").read_text() == "only copy"


def test_backup_with_only_unpushed_commits_pushes_them(tmp_path):
    origin, clone, wt_path, git = _origin_clone_wt(tmp_path)
    (wt_path / "g").write_text("committed, never pushed")
    git("add", ".", cwd=wt_path)
    git("commit", "-qm", "work", cwd=wt_path)
    wt = {"path": wt_path, "branch": "pipeline/g-eskayo/marvin#57", "clone": clone}
    ref = cs.backup_worktree(wt, today="20261024", guard=lambda *a: True)
    assert git("--git-dir", str(origin), "show", f"{ref}:g", cwd=tmp_path).stdout == "committed, never pushed"


def test_sweep_backs_up_then_removes_and_a_second_run_finds_nothing_left(tmp_path, monkeypatch):
    origin, clone, wt_path, git = _origin_clone_wt(tmp_path)
    git("update-ref", "refs/remotes/origin/main", "main", cwd=clone)
    (wt_path / "new.py").write_text("only copy")
    import os
    old = 1_000_000_000
    os.utime(wt_path, (old, old))
    monkeypatch.setattr(cs, "worktree_roots", lambda: [tmp_path / "wts"])
    monkeypatch.setattr(cs, "_cwds_in_use", lambda: set())
    monkeypatch.setattr(cs, "GITHUB_REPO_RE", __import__("re").compile(r"(origin)\.git$"))
    kw = dict(pr_state=lambda repo, branch: None, is_claimed=lambda repo, n: False,
              backup=lambda w: cs.backup_worktree(w, today="20261024", guard=lambda *a: True))

    first = cs.sweep_worktrees(**kw)
    assert [r["path"] for r in first["removed"]] == [wt_path]
    assert "backup/pipeline/g-eskayo/marvin#57-20261024" in first["removed"][0]["reason"]
    assert not wt_path.exists()
    second = cs.sweep_worktrees(**kw)
    assert second == {"removed": [], "review": []}
    assert git("--git-dir", str(origin), "show", "backup/pipeline/g-eskayo/marvin#57-20261024:new.py",
               cwd=tmp_path).stdout == "only copy"


def test_roots_cover_pipeline_worktrees_and_every_repos_helper_worktrees(tmp_path, monkeypatch):
    monkeypatch.setattr(cs, "WORKTREES_ROOT", tmp_path / "pipeline")
    monkeypatch.setattr(cs, "HOME", tmp_path)
    (tmp_path / "pipeline").mkdir()
    (tmp_path / "Developer" / "clarity-captions" / ".claude" / "worktrees").mkdir(parents=True)
    (tmp_path / "Developer" / "no-helpers").mkdir(parents=True)
    (tmp_path / ".agents" / ".claude" / "worktrees").mkdir(parents=True)
    roots = cs.worktree_roots()
    assert tmp_path / "pipeline" in roots
    assert tmp_path / "Developer" / "clarity-captions" / ".claude" / "worktrees" in roots
    assert tmp_path / ".agents" / ".claude" / "worktrees" in roots
    assert not any("no-helpers" in str(r) for r in roots)


def test_a_folder_with_no_git_record_is_listed_never_deleted(tmp_path, monkeypatch):
    root = tmp_path / "wts"
    broken = root / "pipeline-g-eskayo-marvin-283"
    broken.mkdir(parents=True)
    (broken / ".git").write_text("gitdir: /nowhere/.git/worktrees/x")
    (broken / "work.py").write_text("maybe the only copy")
    monkeypatch.setattr(cs, "worktree_roots", lambda: [root])
    result = cs.sweep_worktrees(pr_state=lambda r, b: None, is_claimed=lambda r, n: False)
    assert [r["path"] for r in result["review"]] == [broken]
    assert "no git record" in result["review"][0]["reason"]
    assert (broken / "work.py").exists()


def test_cwds_in_use_marks_a_worktree_a_process_is_inside(tmp_path, monkeypatch):
    inside = tmp_path / "wts" / "a"
    (inside / "sub").mkdir(parents=True)
    monkeypatch.setattr(cs, "_cwds_in_use", lambda: {str((inside / "sub").resolve())})
    assert cs._in_use(inside, cs._cwds_in_use()) is True
    assert cs._in_use(tmp_path / "wts" / "b", cs._cwds_in_use()) is False
    assert cs._in_use(tmp_path / "wts" / "a-other", cs._cwds_in_use()) is False


# ── aerial screen-saver cache (macOS re-downloads a video almost daily) ─────

def test_trim_aerials_keeps_only_the_newest_video(tmp_path):
    import os
    d = tmp_path / "videos"
    d.mkdir()
    for i, name in enumerate(["old.mov", "mid.mov", "new.mov"]):
        (d / name).write_bytes(b"x" * 10)
        os.utime(d / name, (1000 + i, 1000 + i))
    (d / "notes.txt").write_text("not a video")
    freed = cs.trim_aerial_videos(d)
    assert sorted(p.name for p in d.iterdir()) == ["new.mov", "notes.txt"]
    assert freed == 20
    assert cs.trim_aerial_videos(d) == 0


def test_trim_aerials_with_no_folder_does_nothing(tmp_path):
    assert cs.trim_aerial_videos(tmp_path / "missing") == 0


def test_the_daily_run_trims_aerials_and_logs_it(log_path, monkeypatch):
    import os
    d = cs.HOME / cs.AERIAL_SUBPATH  # conftest's temp home, never ~/Library
    d.mkdir(parents=True)
    for i, name in enumerate(["a.mov", "b.mov"]):
        (d / name).write_bytes(b"x" * (3 * 2**20))
        os.utime(d / name, (1000 + i, 1000 + i))
    cs.run_daily_sweep(list_claimed_open_issues=lambda: [], list_worktrees=lambda: [], now=NOW)
    assert [p.name for p in d.iterdir()] == ["b.mov"]
    assert "aerial" in log_path.read_text() and "3 MiB" in log_path.read_text()


def test_the_suite_never_points_the_sweep_at_the_real_home():
    import pathlib
    assert cs.HOME != pathlib.Path.home()
    assert not str(cs.WORKTREES_ROOT).startswith(str(pathlib.Path.home() / ".agents-pipeline-worktrees"))


def test_a_huge_leftover_file_is_not_committed_and_the_edits_stay_as_they_were(tmp_path, monkeypatch):
    origin, clone, wt_path, git = _origin_clone_wt(tmp_path)
    monkeypatch.setattr(cs, "BACKUP_MAX_FILE_BYTES", 1000)
    (wt_path / "model.bin").write_bytes(b"x" * 5000)
    (wt_path / "small.py").write_text("y")
    wt = {"path": wt_path, "branch": "pipeline/g-eskayo/marvin#57", "clone": clone}
    before = git("rev-parse", "HEAD", cwd=wt_path).stdout
    assert cs.backup_worktree(wt, today="20261024", guard=lambda *a: True) is None
    assert git("rev-parse", "HEAD", cwd=wt_path).stdout == before  # nothing committed
    assert git("diff", "--cached", "--name-only", cwd=wt_path).stdout == ""  # nothing left staged
    assert sorted(git("status", "--porcelain", cwd=wt_path).stdout.split()) == ["??", "??", "model.bin", "small.py"]
    assert git("--git-dir", str(origin), "branch", "--list", "backup/*", cwd=tmp_path).stdout == ""


# ── backups pass the ADR 0071 push guard in every repo, hook or not ────────
# Found 2026-10-25: clarity-captions (public) has no pre-push hook, so its backups went out unchecked (they were
# clean). marvin's hook refused 11; the sweep must never depend on a repo having it.

def test_a_refused_backup_pushes_nothing(tmp_path):
    origin, clone, wt_path, git = _origin_clone_wt(tmp_path)
    (wt_path / "new.py").write_text("work")
    wt = {"path": wt_path, "branch": "pipeline/g-eskayo/marvin#57", "clone": clone}
    asked = []
    ref = cs.backup_worktree(wt, today="20261024", guard=lambda *a: asked.append(a) or False)
    assert ref is None
    assert asked and asked[0][0] == wt_path
    assert git("--git-dir", str(origin), "branch", "--list", "backup/*", cwd=tmp_path).stdout == ""


def test_the_real_guard_blocks_a_private_string_in_a_repo_without_the_hook(tmp_path, monkeypatch):
    origin, clone, wt_path, git = _origin_clone_wt(tmp_path)
    assert not (clone / ".git" / "hooks" / "pre-push").exists()  # like clarity-captions
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    (home / ".claude" / "private-push-patterns.txt").write_text("555-0142\n")
    monkeypatch.setenv("HOME", str(home))
    (wt_path / "notes.md").write_text("call me at 555-0142")
    wt = {"path": wt_path, "branch": "pipeline/g-eskayo/marvin#57", "clone": clone}
    assert cs.backup_worktree(wt, today="20261024") is None
    assert git("--git-dir", str(origin), "branch", "--list", "backup/*", cwd=tmp_path).stdout == ""


def test_the_real_guard_lets_clean_work_through(tmp_path, monkeypatch):
    origin, clone, wt_path, git = _origin_clone_wt(tmp_path)
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    (home / ".claude" / "private-push-patterns.txt").write_text("555-0142\n")
    monkeypatch.setenv("HOME", str(home))
    (wt_path / "code.py").write_text("x = 1")
    wt = {"path": wt_path, "branch": "pipeline/g-eskayo/marvin#57", "clone": clone}
    assert cs.backup_worktree(wt, today="20261024") == "backup/pipeline/g-eskayo/marvin#57-20261024"


def test_the_guard_always_uses_marvins_shared_patterns_even_in_another_repo(tmp_path, monkeypatch):
    origin, clone, wt_path, git = _origin_clone_wt(tmp_path)
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    (home / ".claude" / "private-push-patterns.txt").write_text("# none\n")
    monkeypatch.setenv("HOME", str(home))
    key = "AKIA" + "ABCDEFGHIJKLMNOP"  # an AWS access-key shape, from the shared patterns
    (wt_path / "cfg.py").write_text(f"KEY = '{key}'")
    wt = {"path": wt_path, "branch": "pipeline/g-eskayo/marvin#57", "clone": clone}
    assert cs.backup_worktree(wt, today="20261024") is None
