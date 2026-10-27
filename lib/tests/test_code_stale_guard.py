"""The ticket pipeline refuses to dispatch while its own code is stale (marvin#458).

2026-10-24/25: ticket #458 was rebuilt ~122 times on one Mac although it carried ready-for-human. The fix that skips
tickets needing a person (#606) had been on main for three days, but that Mac's ~/.agents code sync was stuck on an
unresolved merge conflict, so the pipeline kept running three-day-old code. Nothing stopped it and nobody was told.

Every test here builds real git repos under a temp HOME: a bare "origin", the pipeline's checkout at $HOME/.agents and
an upstream clone that lands commits on main. Never the real ~/.agents.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import failure_breaker as fb  # noqa: E402

REAL_HOME = Path.home()
NOW = datetime(2026, 10, 25, 12, 0, tzinfo=timezone.utc)


def _git(repo: Path, *args: str, at: datetime | None = None) -> str:
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com"}
    if at is not None:
        env["GIT_AUTHOR_DATE"] = env["GIT_COMMITTER_DATE"] = at.isoformat()
    return subprocess.run(["git", *args], cwd=repo, env=env, capture_output=True, text=True, check=True).stdout


class Repos:
    def __init__(self, home: Path):
        self.home = home
        self.origin = home / "origin.git"
        self.checkout = home / ".agents"
        self.upstream = home / "upstream"
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(self.origin)], check=True)
        subprocess.run(["git", "clone", "-q", str(self.origin), str(self.upstream)], check=True, capture_output=True)
        _git(self.upstream, "checkout", "-q", "-b", "main")
        self.land("base", NOW - timedelta(days=10))
        subprocess.run(["git", "clone", "-q", str(self.origin), str(self.checkout)], check=True, capture_output=True)

    def land(self, name: str, at: datetime) -> None:
        """A change landing on origin/main at `at`."""
        (self.upstream / f"{name}.txt").write_text(name)
        _git(self.upstream, "add", "-A")
        _git(self.upstream, "commit", "-q", "-m", name, at=at)
        _git(self.upstream, "push", "-q", "origin", "main")

    def fetch(self) -> None:
        """What the code sync (or the health sweep's repo:sync check) already does every cycle."""
        _git(self.checkout, "fetch", "-q", "origin")

    def catch_up(self) -> None:
        _git(self.checkout, "merge", "-q", "--ff-only", "origin/main")


@pytest.fixture
def repos(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    assert Path.home() == home and Path.home() != REAL_HOME
    return Repos(home)


def freshness(**kw):
    return fb.code_freshness(now=kw.pop("now", NOW), **kw)


# ── behind / not behind ──────────────────────────────────────────────────────

def test_current_checkout_dispatches(repos):
    repos.fetch()
    f = freshness()
    assert f["state"] == "current" and f["behind"] == 0
    assert fb.code_trip(now=NOW) is None


def test_behind_inside_the_grace_period_still_dispatches(repos):
    # Normal drift between sync cycles (every 30 min) must never pause anything.
    repos.land("fresh", NOW - timedelta(minutes=90))
    repos.fetch()
    f = freshness()
    assert f["state"] == "current" and f["behind"] == 1
    assert fb.code_trip(now=NOW) is None


def test_behind_beyond_the_grace_period_refuses_with_the_fix_text(repos):
    repos.land("old", NOW - timedelta(hours=72))
    repos.land("newer", NOW - timedelta(hours=1))
    repos.fetch()
    f = freshness()
    assert f["state"] == "stale" and f["behind"] == 2 and round(f["oldest_hours"]) == 72
    trip = fb.code_trip(now=NOW)
    assert trip["signature"] == fb.CODE_STALE_SIGNATURE and trip["project"] == fb.ALL_PROJECTS
    assert trip["fix"] == ("this Mac's MARVIN code is 2 commits behind main (oldest 72h): "
                           "code sync is stuck; resolve it (see repo:sync)")


def test_grace_boundary_is_exact_and_the_constant_is_two_hours(repos):
    assert fb.CODE_STALE_GRACE_HOURS == 2
    repos.land("edge", NOW - timedelta(hours=2))
    repos.fetch()
    assert freshness()["state"] == "stale"                                          # at the boundary: refuse
    assert freshness(now=NOW - timedelta(seconds=1))["state"] == "current"         # a second earlier: fine
    assert freshness(grace_hours=3)["state"] == "current"                           # the grace is a parameter


def test_age_is_when_a_change_landed_on_main_not_when_its_branch_was_written(repos):
    # A PR whose commits are a week old, merged ten minutes ago, is ten minutes behind, not a week.
    _git(repos.upstream, "checkout", "-q", "-b", "feature")
    (repos.upstream / "feature.txt").write_text("f")
    _git(repos.upstream, "add", "-A")
    _git(repos.upstream, "commit", "-q", "-m", "old branch work", at=NOW - timedelta(days=7))
    _git(repos.upstream, "checkout", "-q", "main")
    _git(repos.upstream, "merge", "-q", "--no-ff", "feature", "-m", "Merge PR", at=NOW - timedelta(minutes=10))
    _git(repos.upstream, "push", "-q", "origin", "main")
    repos.fetch()
    f = freshness()
    assert f["behind"] == 2 and f["state"] == "current", f


def test_reads_the_last_fetch_and_makes_no_network_call(repos):
    repos.land("old", NOW - timedelta(hours=30))
    repos.fetch()
    # Origin vanishes: the guard must still judge from the refs the last fetch left (no fetch of its own).
    _git(repos.checkout, "remote", "set-url", "origin", str(repos.home / "gone.git"))
    assert freshness()["state"] == "stale"


def test_catching_up_resumes_dispatch_by_itself(repos):
    repos.land("old", NOW - timedelta(hours=30))
    repos.fetch()
    assert fb.code_trip(now=NOW) is not None
    repos.catch_up()
    assert fb.code_trip(now=NOW) is None
    assert freshness()["state"] == "current"


# ── local work must never block ──────────────────────────────────────────────

def test_checkout_ahead_of_origin_with_local_wip_commits_dispatches(repos):
    (repos.checkout / "wip.txt").write_text("wip")
    _git(repos.checkout, "add", "-A")
    _git(repos.checkout, "commit", "-q", "-m", "local wip", at=NOW - timedelta(days=3))
    repos.fetch()
    f = freshness()
    assert f["state"] == "current" and f["behind"] == 0
    assert fb.code_trip(now=NOW) is None


def test_uncommitted_edits_do_not_block(repos):
    (repos.checkout / "base.txt").write_text("edited")
    (repos.checkout / "new.txt").write_text("untracked")
    repos.fetch()
    assert freshness()["state"] == "current"


def test_ahead_and_behind_still_refuses_on_the_missing_part(repos):
    (repos.checkout / "wip.txt").write_text("wip")
    _git(repos.checkout, "add", "-A")
    _git(repos.checkout, "commit", "-q", "-m", "local wip")
    repos.land("old", NOW - timedelta(hours=5))
    repos.fetch()
    f = freshness()
    assert f["state"] == "stale" and f["behind"] == 1


# ── detached HEAD ────────────────────────────────────────────────────────────

def test_detached_head_on_main_tip_dispatches(repos):
    repos.fetch()
    _git(repos.checkout, "checkout", "-q", "--detach", "origin/main")
    assert freshness()["state"] == "current"


def test_detached_head_on_an_old_commit_refuses(repos):
    # code_sync skips a detached HEAD, so it will never catch up by itself: the old code is what runs.
    base = _git(repos.checkout, "rev-parse", "HEAD").strip()
    repos.land("old", NOW - timedelta(hours=10))
    repos.fetch()
    repos.catch_up()
    _git(repos.checkout, "checkout", "-q", "--detach", base)
    f = freshness()
    assert f["state"] == "stale" and f["behind"] == 1


# ── stuck sync: conflict or leftover stash ───────────────────────────────────

def test_an_unresolved_merge_conflict_refuses_even_when_not_behind(repos):
    (repos.checkout / "base.txt").write_text("mine")
    _git(repos.checkout, "commit", "-q", "-am", "mine")
    repos.land("x", NOW - timedelta(minutes=5))
    (repos.upstream / "base.txt").write_text("theirs")
    _git(repos.upstream, "commit", "-q", "-am", "theirs", at=NOW - timedelta(minutes=5))
    _git(repos.upstream, "push", "-q", "origin", "main")
    repos.fetch()
    with pytest.raises(subprocess.CalledProcessError):
        _git(repos.checkout, "merge", "origin/main")   # with an identity: the temp HOME has no global git config
    assert (repos.checkout / ".git" / "MERGE_HEAD").exists()   # the conflict is real and left in place
    f = freshness()
    assert f["state"] == "stuck" and "merge conflict" in f["detail"]
    trip = fb.code_trip(now=NOW)
    assert trip and "code sync is stuck" in trip["fix"] and "repo:sync" in trip["fix"]
    # never auto-resolved: still conflicted after the guard ran
    assert (repos.checkout / ".git" / "MERGE_HEAD").exists()
    assert "<<<<<<<" in (repos.checkout / "base.txt").read_text()


def test_a_leftover_stash_refuses_and_is_left_alone(repos):
    repos.fetch()
    (repos.checkout / "base.txt").write_text("wip")
    _git(repos.checkout, "stash", "push", "-q", "-m", "code_sync auto-stash")
    f = freshness()
    assert f["state"] == "stuck" and "stash" in f["detail"]
    assert fb.code_trip(now=NOW) is not None
    assert _git(repos.checkout, "stash", "list").strip()   # still there


def test_clearing_the_stash_resumes_dispatch(repos):
    repos.fetch()
    (repos.checkout / "base.txt").write_text("wip")
    _git(repos.checkout, "stash", "push", "-q")
    assert fb.code_trip(now=NOW) is not None
    _git(repos.checkout, "stash", "drop", "-q")
    assert fb.code_trip(now=NOW) is None


# ── can't tell: fail open, loudly ────────────────────────────────────────────

def test_no_origin_main_ref_fails_open_with_a_reason(repos):
    _git(repos.checkout, "update-ref", "-d", "refs/remotes/origin/main")
    f = freshness()
    assert f["state"] == "unknown" and "origin/main" in f["detail"]
    assert fb.code_trip(now=NOW) is None


def test_missing_checkout_fails_open(repos, tmp_path):
    f = fb.code_freshness(repo_rel="not-there", now=NOW)
    assert f["state"] == "unknown"
    assert fb.code_trip(repo_rel="not-there", now=NOW) is None


def test_a_broken_git_runner_fails_open_and_never_raises(repos, monkeypatch):
    import health_checks
    def boom(*a, **k):
        raise OSError("git is gone")
    monkeypatch.setattr(health_checks, "_run_repo_state", boom)
    f = freshness()
    assert f["state"] == "unknown" and "git is gone" in f["detail"]


def test_a_stuck_tree_refuses_even_when_origin_main_is_unreadable(repos):
    # Unknown freshness fails open, but a conflict is local, certain evidence: still refuse.
    (repos.checkout / "base.txt").write_text("wip")
    _git(repos.checkout, "stash", "push", "-q")
    _git(repos.checkout, "update-ref", "-d", "refs/remotes/origin/main")
    assert freshness()["state"] == "stuck"


# ── the CLI the other Mac's Health check reads ───────────────────────────────

def test_json_cli_includes_the_stale_code_trip(repos, monkeypatch, capsys):
    repos.land("old", NOW - timedelta(hours=30))
    repos.fetch()
    monkeypatch.setattr(sys, "argv", ["failure_breaker.py", "--json"])
    monkeypatch.setattr(fb, "_now", lambda: NOW)
    fb.main()
    trips = json.loads(capsys.readouterr().out)
    assert [t["signature"] for t in trips] == [fb.CODE_STALE_SIGNATURE]
    assert "1 commit behind main" in trips[0]["fix"]
