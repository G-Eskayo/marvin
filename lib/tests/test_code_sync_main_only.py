"""marvin#440: code_sync only commits, stashes or merges when `main` is checked out. Run via:
    ~/.agents/venv/bin/python -m pytest lib/tests/test_code_sync_main_only.py -v

2026-10-14: the shared ~/.agents sat on a ticket branch during a test run; auto-sync committed onto it, sweeping another
session's uncommitted work into PR #439, then pushed `main`, which carried none of it. Real temp repos, temp log.
"""
from __future__ import annotations

import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

LIB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LIB))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import code_sync as cs  # noqa: E402
import health_checks  # noqa: E402
import session_start_report as ssr  # noqa: E402
from test_code_sync_push import _make_origin_and_clone, _second_clone, _origin_head, _quiet, _git  # noqa: E402


def _out(repo: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True).stdout.strip()


def _setup(tmp_path, monkeypatch, branch: str | None = "ticket/1-x"):
    log = tmp_path / "sync-log.md"
    _quiet(monkeypatch, log)
    clone = _make_origin_and_clone(tmp_path)
    if branch:
        _git(clone, "checkout", "-q", "-b", branch)
    return clone, log


def _log(log: Path) -> str:
    return log.read_text() if log.exists() else ""


def test_push_on_a_feature_branch_commits_nothing_and_leaves_wip_alone(tmp_path, monkeypatch):
    clone, log = _setup(tmp_path, monkeypatch)
    (clone / "file.md").write_text("another session's WIP\n")
    (clone / "new.md").write_text("untracked WIP\n")
    head, origin = _out(clone, "rev-parse", "HEAD"), _origin_head(tmp_path)

    cs.push(clone)

    assert _out(clone, "rev-parse", "HEAD") == head, "committed onto the feature branch"
    assert _origin_head(tmp_path) == origin
    assert {l.strip() for l in _out(clone, "status", "--porcelain").splitlines()} == {"M file.md", "?? new.md"}
    assert (clone / "file.md").read_text() == "another session's WIP\n"
    assert "skipping" in _log(log) and "ticket/1-x" in _log(log)


def test_pull_on_a_feature_branch_neither_stashes_nor_merges(tmp_path, monkeypatch):
    clone, log = _setup(tmp_path, monkeypatch)
    other = _second_clone(tmp_path)
    (other / "elsewhere.md").write_text("from the other Mac\n")
    _git(other, "add", "-A")
    _git(other, "commit", "-m", "theirs")
    _git(other, "push", "origin", "main")
    (clone / "file.md").write_text("WIP\n")
    head = _out(clone, "rev-parse", "HEAD")

    cs.pull(clone)

    assert _out(clone, "rev-parse", "HEAD") == head
    assert _out(clone, "stash", "list") == ""
    assert _out(clone, "status", "--porcelain") == "M file.md"


def test_skip_is_logged_once_per_branch_not_every_cycle(tmp_path, monkeypatch):
    clone, log = _setup(tmp_path, monkeypatch)
    (clone / "file.md").write_text("WIP\n")
    for _ in range(3):
        cs.push(clone)
        cs.pull(clone)
    assert _log(log).count("skipping") == 1, _log(log)

    _git(clone, "checkout", "-q", "-b", "ticket/2-y")
    cs.push(clone)
    cs.push(clone)
    assert _log(log).count("skipping") == 2 and "ticket/2-y" in _log(log)


def test_detached_head_mid_rebase_is_skipped_too(tmp_path, monkeypatch):
    clone, log = _setup(tmp_path, monkeypatch, branch=None)
    _git(clone, "checkout", "-q", "--detach")
    (clone / "file.md").write_text("WIP\n")
    head = _out(clone, "rev-parse", "HEAD")

    cs.push(clone)

    assert _out(clone, "rev-parse", "HEAD") == head
    assert "detached" in _log(log)


def test_back_on_main_syncs_normally_again(tmp_path, monkeypatch):
    clone, log = _setup(tmp_path, monkeypatch)
    cs.push(clone)
    _git(clone, "checkout", "-q", "main")
    (clone / "file.md").write_text("v2\n")

    cs.push(clone)

    assert _origin_head(tmp_path) == _out(clone, "rev-parse", "HEAD")
    assert "committed + pushed 1 file(s)" in _log(log)


def test_a_stuck_repo_still_refuses_loudly_on_a_branch(tmp_path, monkeypatch):
    """A leftover stash is a failure whatever is checked out; the branch skip must not hide it."""
    clone, log = _setup(tmp_path, monkeypatch)
    (clone / "file.md").write_text("WIP\n")
    _git(clone, "stash", "push", "-m", "leftover")

    cs.push(clone)

    assert "REFUSING" in _log(log)
    assert "skipping" not in _log(log)


def test_skip_is_not_a_failure_and_does_not_hide_an_earlier_one(tmp_path, monkeypatch):
    """Neutral, like 'deferring': not an error for Health or the report, and not a success that ends a failure run."""
    clone, log = _setup(tmp_path, monkeypatch)
    assert not cs.SYNC_FAILURE_RE.match("skipping — ticket/1-x checked out, not main; whoever checked it out owns its commits")
    start = datetime.now(timezone.utc) - timedelta(hours=6)
    log.write_text(f"\n## {start.isoformat()} — push ({cs.machine_label()}) [{clone}]\ncommit failed:\n")

    cs.push(clone)

    later = datetime.now(timezone.utc) + timedelta(minutes=1)
    stuck = [r for r in health_checks.check_sync_stuck_from_text(_log(log), now=later, only_machine=cs.machine_label())
             if r["id"].endswith(f"{clone}:push")]
    assert stuck and stuck[0]["severity"] == "red", _log(log)
    streak = ssr._sync_failure_streak(_log(log), cs.machine_label(), clone)
    assert streak and streak[0] == 1


def test_repo_with_no_branch_info_at_all_never_raises(tmp_path, monkeypatch):
    log = tmp_path / "sync-log.md"
    _quiet(monkeypatch, log)
    plain = tmp_path / "plain"
    plain.mkdir()
    cs.push(plain)
    cs.pull(plain)
