"""Tests for code_sync.py's push(). Run via:
    ~/.agents/venv/bin/python -m pytest lib/tests/test_code_sync_push.py -v

Uses real temp git repos (a bare "origin" plus a working clone) rather than
mocking `git` — push()'s whole job is orchestrating real git state, so a
mocked subprocess wouldn't catch the class of bug this file guards against.
"""
from __future__ import annotations
import subprocess
import sys
from pathlib import Path

LIB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LIB))

import code_sync as cs  # noqa: E402


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


def _make_origin_and_clone(tmp_path: Path) -> Path:
    origin = tmp_path / "origin.git"
    origin.mkdir()
    _git(origin, "init", "--bare", "-b", "main")

    seed = tmp_path / "seed"
    seed.mkdir()
    _git(seed, "init", "-b", "main")
    _git(seed, "config", "user.email", "test@example.com")
    _git(seed, "config", "user.name", "Test")
    (seed / "sync-log.md").write_text("# log\n")
    (seed / "file.md").write_text("v1\n")
    _git(seed, "add", "-A")
    _git(seed, "commit", "-m", "seed")
    _git(seed, "push", str(origin), "main")

    clone = tmp_path / "clone"
    subprocess.run(["git", "clone", str(origin), str(clone)], check=True, capture_output=True)
    _git(clone, "config", "user.email", "test@example.com")
    _git(clone, "config", "user.name", "Test")
    return clone


def test_push_ships_a_clean_tree_with_unpushed_commits(tmp_path, monkeypatch):
    """Reproduces the real bug: a manual `git commit` (e.g. resolving a
    stash conflict by hand) leaves the working tree clean, but the commit
    itself was never pushed. push() must not silently no-op in that case."""
    monkeypatch.setattr(cs, "LOG_PATH", tmp_path / "unused-log.md")
    monkeypatch.setattr(cs, "notify", lambda *a, **kw: None)

    clone = _make_origin_and_clone(tmp_path)
    (clone / "file.md").write_text("v2 — resolved by hand\n")
    _git(clone, "add", "-A")
    _git(clone, "commit", "-m", "manual resolution commit")

    assert subprocess.run(["git", "status", "--porcelain"], cwd=clone, capture_output=True, text=True).stdout == ""

    cs.push(clone)

    origin_head = subprocess.run(["git", "rev-parse", "main"], cwd=clone.parent / "origin.git", capture_output=True, text=True).stdout.strip()
    clone_head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=clone, capture_output=True, text=True).stdout.strip()
    assert origin_head == clone_head, "push() left an already-committed, unpushed change stranded on a clean working tree"


def test_push_no_ops_when_truly_nothing_to_do(tmp_path, monkeypatch):
    monkeypatch.setattr(cs, "LOG_PATH", tmp_path / "unused-log.md")
    monkeypatch.setattr(cs, "notify", lambda *a, **kw: None)

    clone = _make_origin_and_clone(tmp_path)
    before = subprocess.run(["git", "rev-parse", "HEAD"], cwd=clone, capture_output=True, text=True).stdout.strip()

    cs.push(clone)

    after = subprocess.run(["git", "rev-parse", "HEAD"], cwd=clone, capture_output=True, text=True).stdout.strip()
    assert before == after


def test_stuck_from_previous_run_includes_stashed_file_names(tmp_path, monkeypatch):
    """When a stash is left behind, the error message names the touched files."""
    monkeypatch.setattr(cs, "LOG_PATH", tmp_path / "unused-log.md")
    monkeypatch.setattr(cs, "notify", lambda *a, **kw: None)

    clone = _make_origin_and_clone(tmp_path)

    # Create a stash with some tracked files
    (clone / "file.md").write_text("modified\n")
    (clone / "new-file.txt").write_text("untracked\n")
    _git(clone, "stash", "push", "-u", "-m", "test stash")

    # Call _stuck_from_previous_run and check that file names are included
    result = cs._stuck_from_previous_run(clone)
    assert result is not None
    assert "stash@{0} touches:" in result
    assert "file.md" in result or "new-file.txt" in result


# ── marvin#427: the log only says "pushed" after a push that succeeded ────────

def _second_clone(tmp_path: Path, name: str = "other") -> Path:
    other = tmp_path / name
    subprocess.run(["git", "clone", str(tmp_path / "origin.git"), str(other)], check=True, capture_output=True)
    _git(other, "config", "user.email", "test@example.com")
    _git(other, "config", "user.name", "Test")
    return other


def _origin_head(tmp_path: Path) -> str:
    return subprocess.run(["git", "rev-parse", "main"], cwd=tmp_path / "origin.git", capture_output=True, text=True).stdout.strip()


def _quiet(monkeypatch, log: Path) -> None:
    monkeypatch.setattr(cs, "LOG_PATH", log)
    monkeypatch.setattr(cs, "notify", lambda *a, **kw: None)
    monkeypatch.setattr(cs, "_live_edit_lease", lambda *a, **kw: None)
    monkeypatch.setattr(cs.error_log, "record", lambda *a, **kw: None)


def test_rejected_push_with_merge_conflict_never_logs_pushed(tmp_path, monkeypatch):
    """The 2026-10-14 16:37:30 case: the remote moved, the push was rejected, the merge conflicted, origin never got
    the commit, but sync-log.md said 'committed + pushed'."""
    log = tmp_path / "sync-log.md"
    _quiet(monkeypatch, log)
    clone = _make_origin_and_clone(tmp_path)
    other = _second_clone(tmp_path)
    (other / "file.md").write_text("the other Mac's edit\n")
    _git(other, "commit", "-am", "other mac")
    _git(other, "push", "origin", "main")
    origin_before = _origin_head(tmp_path)

    (clone / "file.md").write_text("this Mac's conflicting edit\n")
    cs.push(clone)

    text = log.read_text()
    assert _origin_head(tmp_path) == origin_before, "test setup: the push must really have failed"
    assert "pushed" not in text.replace("NOT pushed", ""), f"log claims a push that never happened:\n{text}"
    assert "committed locally" in text and "NOT pushed" in text
    assert cs.SYNC_FAILURE_RE.match(text.split("\n", 3)[2]), "the entry must read as a failure so Health and the report see it"


def test_push_that_fails_outright_never_logs_pushed(tmp_path, monkeypatch):
    """origin unreachable (Mini asleep, Tailscale down): commit lands locally, push fails, the merge can't even fetch."""
    log = tmp_path / "sync-log.md"
    _quiet(monkeypatch, log)
    clone = _make_origin_and_clone(tmp_path)
    _git(clone, "remote", "set-url", "origin", str(tmp_path / "gone.git"))
    (clone / "file.md").write_text("v2\n")

    cs.push(clone)

    text = log.read_text()
    assert "pushed" not in text.replace("NOT pushed", ""), text
    assert "NOT pushed" in text
    entries = [e for e in text.split("\n## ") if e.strip()]
    assert all(cs.SYNC_FAILURE_RE.match(e.split("\n", 1)[1]) for e in entries), text


def test_successful_push_logs_pushed_once_after_the_fact(tmp_path, monkeypatch):
    log = tmp_path / "sync-log.md"
    _quiet(monkeypatch, log)
    clone = _make_origin_and_clone(tmp_path)
    (clone / "file.md").write_text("v2\n")

    cs.push(clone)

    text = log.read_text()
    assert _origin_head(tmp_path) == subprocess.run(["git", "rev-parse", "HEAD"], cwd=clone, capture_output=True, text=True).stdout.strip()
    assert text.count("committed + pushed 1 file(s)") == 1, text


def test_rejected_push_that_merges_cleanly_logs_pushed_after_the_retry(tmp_path, monkeypatch):
    log = tmp_path / "sync-log.md"
    _quiet(monkeypatch, log)
    clone = _make_origin_and_clone(tmp_path)
    other = _second_clone(tmp_path)
    (other / "elsewhere.md").write_text("non-overlapping\n")
    _git(other, "add", "-A")
    _git(other, "commit", "-m", "other mac")
    _git(other, "push", "origin", "main")

    (clone / "file.md").write_text("v2\n")
    cs.push(clone)

    text = log.read_text()
    assert _origin_head(tmp_path) == subprocess.run(["git", "rev-parse", "HEAD"], cwd=clone, capture_output=True, text=True).stdout.strip()
    assert text.count("pushed") == 1 and "merged remote changes first" in text, text


def test_log_inside_the_repo_does_not_leave_it_ahead_or_conflicted(tmp_path, monkeypatch):
    """~/.claude logs into itself. Logging after the push leaves the entry as a trailing change; it must not be
    committed-but-unpushed, and a second push with nothing else changed must stay a quiet no-op."""
    clone = _make_origin_and_clone(tmp_path)
    log = clone / "sync-log.md"
    _quiet(monkeypatch, log)
    (clone / "file.md").write_text("v2\n")

    cs.push(clone)
    head = _origin_head(tmp_path)
    size = log.stat().st_size
    cs.push(clone)

    assert _origin_head(tmp_path) == head
    assert subprocess.run(["git", "rev-list", "--count", "origin/main..HEAD"], cwd=clone, capture_output=True, text=True).stdout.strip() == "0"
    assert log.stat().st_size == size, "a no-op push must not log anything"
