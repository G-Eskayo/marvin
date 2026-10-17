"""marvin#426: a blocked memory/code sync is a hard stop at the top of the session-start report. Run via:
    ~/.agents/venv/bin/python -m pytest lib/tests/test_session_start_sync_block.py -v

Real temp git repos (bare origin + clones) and a temp HOME; never the real ~/.claude (2026-10-09 logs wipe).
"""
from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

LIB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LIB))

import session_start_report as ssr  # noqa: E402

@pytest.fixture(autouse=True)
def _no_real_home_writes(monkeypatch, tmp_path):
    """A failing check must never log into the real ~/.claude."""
    monkeypatch.setattr(ssr, "log_hook_error", lambda *a, **kw: None)
    monkeypatch.setattr(ssr, "CLAUDE_DIR", tmp_path / "home" / ".claude")
    monkeypatch.setattr(ssr, "_last_wake", lambda: None)  # never this Mac's real wake time (#451 tests set their own)


NOW = datetime(2026, 10, 14, 16, 0, tzinfo=timezone.utc)
ME = "macbook-pro"


def _git(repo: Path, *args: str, env: dict | None = None) -> str:
    return subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True,
                          env={**os.environ, **(env or {})}).stdout


def _dated(when: datetime) -> dict:
    stamp = when.strftime("%Y-%m-%dT%H:%M:%S+0000")
    return {"GIT_COMMITTER_DATE": stamp, "GIT_AUTHOR_DATE": stamp}


def _origin_and_clone(tmp_path: Path, name: str = "repo") -> Path:
    origin = tmp_path / f"{name}-origin.git"
    origin.mkdir()
    _git(origin, "init", "--bare", "-b", "main")
    clone = tmp_path / name
    subprocess.run(["git", "clone", str(origin), str(clone)], check=True, capture_output=True)
    for c in (clone,):
        _git(c, "config", "user.email", "t@example.com")
        _git(c, "config", "user.name", "T")
        _git(c, "symbolic-ref", "HEAD", "refs/heads/main")
    (clone / "file.md").write_text("v1\n")
    _git(clone, "add", "-A")
    _git(clone, "commit", "-m", "seed", env=_dated(NOW - timedelta(days=5)))
    _git(clone, "push", "origin", "main")
    _git(clone, "branch", "--set-upstream-to=origin/main", "main")
    return clone


def _other_clone(tmp_path: Path, name: str = "repo") -> Path:
    other = tmp_path / f"{name}-other"
    subprocess.run(["git", "clone", str(tmp_path / f"{name}-origin.git"), str(other)], check=True, capture_output=True)
    _git(other, "config", "user.email", "t@example.com")
    _git(other, "config", "user.name", "T")
    return other


def _conflict(tmp_path: Path, clone: Path) -> None:
    other = _other_clone(tmp_path)
    (other / "file.md").write_text("theirs\n")
    _git(other, "commit", "-am", "theirs")
    _git(other, "push", "origin", "main")
    (clone / "file.md").write_text("ours\n")
    _git(clone, "commit", "-am", "ours")
    _git(clone, "fetch", "origin")
    subprocess.run(["git", "merge", "origin/main"], cwd=clone, capture_output=True)


def _entry(ts: datetime, summary: str, repo: Path, machine: str = ME, action: str = "push") -> str:
    return f"\n## {ts.isoformat()} — {action} ({machine}) [{repo}]\n{summary}\n"


def _block(repos, log_text: str = "", now: datetime = NOW, tmp_path: Path | None = None):
    log = (tmp_path or Path(repos[0]).parent) / "sync-log.md"
    log.write_text(log_text)
    return ssr.check_sync_block(repos=repos, log_path=log, machine=ME, now=now)


# ── nothing wrong → nothing printed ──────────────────────────────────────────

def test_clean_synced_repo_with_no_log_is_silent(tmp_path):
    clone = _origin_and_clone(tmp_path)
    assert _block([clone]) is None


def test_missing_repo_missing_log_and_non_git_dir_never_raise(tmp_path):
    plain = tmp_path / "not-a-repo"
    plain.mkdir()
    assert ssr.check_sync_block(repos=[tmp_path / "nope", plain], log_path=tmp_path / "absent.md", machine=ME, now=NOW) is None


def test_garbage_log_is_ignored_not_fatal(tmp_path):
    clone = _origin_and_clone(tmp_path)
    junk = "## not-a-date — push (macbook-pro) [x]\nREFUSING\n\x00\x01 <<<<<<< \n## \n" * 50
    assert _block([clone], junk) is None


def test_repo_without_an_origin_is_not_a_block(tmp_path):
    lone = tmp_path / "lone"
    lone.mkdir()
    _git(lone, "init", "-b", "main")
    _git(lone, "-c", "user.email=a@b", "-c", "user.name=a", "commit", "--allow-empty", "-m", "x")
    assert _block([lone]) is None


# ── live git state ───────────────────────────────────────────────────────────

def test_unresolved_merge_conflict_blocks(tmp_path):
    clone = _origin_and_clone(tmp_path)
    _conflict(tmp_path, clone)
    out = _block([clone])
    assert out and "merge conflict" in out


def test_conflict_resolved_in_content_but_never_git_added_still_blocks(tmp_path):
    """The real 2026-10-10 state: quarantine.md fixed by hand, never `git add`ed, so still UU."""
    clone = _origin_and_clone(tmp_path)
    _conflict(tmp_path, clone)
    (clone / "file.md").write_text("resolved by hand, no markers\n")
    out = _block([clone])
    assert out and "merge conflict" in out


def test_leftover_stash_blocks(tmp_path):
    clone = _origin_and_clone(tmp_path)
    (clone / "file.md").write_text("wip\n")
    _git(clone, "stash", "push", "-m", "code_sync auto-stash")
    out = _block([clone])
    assert out and "stash" in out


def test_unpushed_commit_older_than_threshold_blocks(tmp_path):
    clone = _origin_and_clone(tmp_path)
    (clone / "file.md").write_text("v2\n")
    _git(clone, "commit", "-am", "auto-sync", env=_dated(NOW - timedelta(hours=5)))
    out = _block([clone])
    assert out and "1 commit" in out and "not pushed" in out


def test_fresh_unpushed_commit_is_not_yet_a_block(tmp_path):
    """A push in flight or just retried: the next cycle may clear it."""
    clone = _origin_and_clone(tmp_path)
    (clone / "file.md").write_text("v2\n")
    _git(clone, "commit", "-am", "auto-sync", env=_dated(NOW - timedelta(minutes=20)))
    assert _block([clone]) is None


def test_behind_origin_after_the_pull_ran_blocks(tmp_path):
    clone = _origin_and_clone(tmp_path)
    other = _other_clone(tmp_path)
    (other / "new.md").write_text("from the other Mac\n")
    _git(other, "add", "-A")
    _git(other, "commit", "-m", "theirs", env=_dated(NOW - timedelta(hours=30)))
    _git(other, "push", "origin", "main")
    _git(clone, "fetch", "origin")
    out = _block([clone])
    assert out and "1 commit" in out and "not merged" in out


def test_feature_branch_checked_out_does_not_flag_main(tmp_path):
    """~/.agents is often on a ticket branch; pull merges origin/main into it, so local `main` lagging is normal."""
    clone = _origin_and_clone(tmp_path)
    other = _other_clone(tmp_path)
    (other / "new.md").write_text("x\n")
    _git(other, "add", "-A")
    _git(other, "commit", "-m", "theirs", env=_dated(NOW - timedelta(hours=30)))
    _git(other, "push", "origin", "main")
    _git(clone, "checkout", "-b", "ticket/1-x")
    _git(clone, "fetch", "origin")
    assert _block([clone]) is None


# ── sync-log streak: how long, how many ──────────────────────────────────────

def test_streak_reports_since_when_and_how_many_refused(tmp_path):
    clone = _origin_and_clone(tmp_path)
    _conflict(tmp_path, clone)
    start = NOW - timedelta(days=3, hours=22)
    log = _entry(start - timedelta(hours=1), "committed + pushed 3 file(s)", clone)
    for i in range(766):
        log += _entry(start + timedelta(minutes=7 * i), "REFUSING to run — an unresolved merge conflict is already sitting in the working tree", clone,
                      action="pull" if i % 2 else "push")
    out = _block([clone], log)
    assert "766" in out, out
    assert "3d 22h" in out, out
    assert start.strftime("%Y-%m-%d %H:%M") in out, out


def test_deferrals_do_not_break_the_streak(tmp_path):
    clone = _origin_and_clone(tmp_path)
    log = (_entry(NOW - timedelta(hours=6), "REFUSING to run — x", clone)
           + _entry(NOW - timedelta(hours=5), "deferring — a.md was edited 1 min ago by a live session; will retry next cycle", clone)
           + _entry(NOW - timedelta(hours=4), "REFUSING to run — x", clone))
    out = _block([clone], log)
    assert out and "2 failed" in out and "6h" in out, out


def test_a_later_success_clears_a_log_only_streak(tmp_path):
    clone = _origin_and_clone(tmp_path)
    log = (_entry(NOW - timedelta(hours=6), "CONFLICT merging origin/main — merge aborted", clone, action="pull")
           + _entry(NOW - timedelta(hours=1), "merged abc..def", clone, action="pull"))
    assert _block([clone], log) is None


def test_other_macs_entries_and_other_repos_are_not_counted(tmp_path):
    """sync-log.md is itself synced, so this Mac's copy holds the other Mac's (possibly stale) failures too."""
    clone = _origin_and_clone(tmp_path)
    log = (_entry(NOW - timedelta(hours=9), "REFUSING to run — x", clone, machine="mac-mini")
           + _entry(NOW - timedelta(hours=9), "REFUSING to run — x", tmp_path / "some-other-repo"))
    assert _block([clone], log) is None


def test_push_rejected_not_pushed_entry_from_427_counts_as_a_block(tmp_path):
    clone = _origin_and_clone(tmp_path)
    log = _entry(NOW - timedelta(hours=3), "CONFLICT merging remote after push rejection — committed locally, NOT pushed (origin/main does not have it); local commit preserved, needs manual resolution:", clone)
    out = _block([clone], log)
    assert out and "NOT pushed" in out


def test_one_recent_failure_alone_is_shown_too(tmp_path):
    """A failure the log reports as the latest state is a block now, not after N hours; the live checks age-gate."""
    clone = _origin_and_clone(tmp_path)
    out = _block([clone], _entry(NOW - timedelta(minutes=2), "push failed even after merge retry — committed locally, NOT pushed:", clone))
    assert out and "1 failed" in out


# ── placement in the report ──────────────────────────────────────────────────

def test_block_sits_directly_under_identity_above_brief_and_backlog(tmp_path, monkeypatch, capsys):
    clone = _origin_and_clone(tmp_path)
    _conflict(tmp_path, clone)
    monkeypatch.setattr(ssr, "check_identity", lambda: "MARVIN active — test")
    monkeypatch.setattr(ssr, "check_morning_brief", lambda: "# Morning brief\n\nstuff")
    monkeypatch.setattr(ssr, "check_suggestions", lambda: "52 architecture suggestion(s) pending")
    real_block = _block([clone])
    assert real_block
    monkeypatch.setattr(ssr, "check_sync_block", lambda: real_block)
    for name in ("check_handoff", "load_lexicon", "check_improvement_queue", "process_and_check_quarantine",
                 "check_hook_errors", "check_cron_health", "check_auto_fix_log", "check_sync_log",
                 "check_auto_merge_report", "check_daily_digest", "check_research_digest"):
        monkeypatch.setattr(ssr, name, lambda: None)

    ssr.main()
    out = capsys.readouterr().out

    assert out.startswith("MARVIN active — test\n"), "the identity banner must stay the very first line"
    sync, brief, backlog = out.index("SYNC BLOCKED"), out.index("Morning brief"), out.index("52 architecture")
    assert sync < brief < backlog
    checklist = out[out.index("## Session-start checklist"):]
    assert "merge conflict" not in checklist, "the conflict must not also be buried as a checklist bullet"


def test_report_still_prints_when_the_sync_check_crashes(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(ssr, "log_hook_error", lambda *a, **kw: None)
    monkeypatch.setattr(ssr, "check_identity", lambda: "MARVIN active — test")

    def boom():
        raise RuntimeError("git exploded")
    monkeypatch.setattr(ssr, "check_sync_block", boom)
    for name in ("check_morning_brief", "check_handoff", "load_lexicon", "check_suggestions", "check_improvement_queue",
                 "process_and_check_quarantine", "check_hook_errors", "check_cron_health", "check_auto_fix_log",
                 "check_sync_log", "check_auto_merge_report", "check_daily_digest", "check_research_digest"):
        monkeypatch.setattr(ssr, name, lambda: None)
    ssr.main()
    assert capsys.readouterr().out.startswith("MARVIN active — test")


# ── marvin#451: age counts from this Mac's last wake as well as the commit time ──

def _behind_by_old_commit(tmp_path: Path) -> Path:
    clone = _origin_and_clone(tmp_path)
    other = _other_clone(tmp_path)
    (other / "new.md").write_text("landed overnight while this Mac slept\n")
    _git(other, "add", "-A")
    _git(other, "commit", "-m", "theirs", env=_dated(NOW - timedelta(hours=8)))
    _git(other, "push", "origin", "main")
    _git(clone, "fetch", "origin")
    return clone


def test_old_commits_right_after_waking_are_not_a_block(tmp_path, monkeypatch):
    clone = _behind_by_old_commit(tmp_path)
    monkeypatch.setattr(ssr, "_last_wake", lambda: NOW - timedelta(minutes=30))
    assert _block([clone]) is None


def test_old_commits_long_after_waking_block_with_age_from_the_wake(tmp_path, monkeypatch):
    clone = _behind_by_old_commit(tmp_path)
    monkeypatch.setattr(ssr, "_last_wake", lambda: NOW - timedelta(hours=3))
    out = _block([clone])
    assert out and "not merged" in out and "3h 0m" in out, out


def test_unpushed_commit_right_after_waking_is_not_a_block(tmp_path, monkeypatch):
    clone = _origin_and_clone(tmp_path)
    (clone / "file.md").write_text("v2\n")
    _git(clone, "commit", "-am", "auto-sync before sleep", env=_dated(NOW - timedelta(hours=19)))
    monkeypatch.setattr(ssr, "_last_wake", lambda: NOW - timedelta(minutes=10))
    assert _block([clone]) is None


def test_wake_in_the_future_or_unknown_falls_back_to_commit_time(tmp_path, monkeypatch):
    clone = _behind_by_old_commit(tmp_path)
    monkeypatch.setattr(ssr, "_last_wake", lambda: None)
    assert "8h 0m" in (_block([clone]) or "")
    monkeypatch.setattr(ssr, "_last_wake", lambda: NOW + timedelta(days=1))
    assert "8h 0m" in (_block([clone]) or ""), "a clock-skewed wake time must not hide a real block"


_real_last_wake = ssr._last_wake  # captured at import, before the autouse fixture stubs it


def test_last_wake_parses_sysctl_and_survives_garbage(monkeypatch):
    class R:
        def __init__(self, out, rc=0):
            self.stdout, self.returncode = out, rc
    for out, rc, want in [("{ sec = 1792088940, usec = 501336 } Thu Oct 15 12:29:00 2026\n", 0, 1792088940),
                          ("", 1, None), ("garbage", 0, None), ("{ sec = -5 }", 0, None)]:
        monkeypatch.setattr(ssr.subprocess, "run", lambda *a, **kw: R(out, rc))
        got = _real_last_wake()
        assert (got.timestamp() if got else None) == want, (out, got)

    def boom(*a, **kw):
        raise OSError("no sysctl")
    monkeypatch.setattr(ssr.subprocess, "run", boom)
    assert _real_last_wake() is None
