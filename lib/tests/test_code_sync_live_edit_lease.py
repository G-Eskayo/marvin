"""Tests for code_sync.py's live edit lease (deferring push when a session is editing).
Run via:
    ~/.agents/venv/bin/python -m pytest lib/tests/test_code_sync_live_edit_lease.py -v

Uses real temp git repos and real session_work state isolation (via conftest fixture).
"""
from __future__ import annotations
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

LIB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LIB))

import code_sync as cs  # noqa: E402
import session_work as sw  # noqa: E402

T = 1_800_000_000.0


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


def _git_status(repo: Path) -> str:
    """Returns porcelain status output."""
    result = subprocess.run(["git", "status", "--porcelain"], cwd=repo, capture_output=True, text=True)
    return result.stdout


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


# ── Acceptance criteria tests ──

def test_push_defers_and_commits_nothing_when_a_live_session_is_mid_edit_on_a_dirty_file(
    tmp_path, monkeypatch
):
    """The ticket's literal example — simulate an edit in progress plus a push tick,
    assert nothing is committed (git log unchanged, working tree still dirty)."""
    monkeypatch.setattr(cs, "LOG_PATH", tmp_path / "sync-log.md")
    monkeypatch.setattr(cs, "notify", lambda *a, **kw: None)

    clone = _make_origin_and_clone(tmp_path)
    repo_id, _ = sw.file_key(str(clone / "file.md"))

    # Record that a session edited file.md recently
    with sw._Locked() as st:
        sw.record_prompt(st, "sess-A", "working on something", T)
        sw.record_edit(st, "sess-A", (repo_id, "file.md"), T)

    # Now dirty the file locally
    (clone / "file.md").write_text("v2 — mid-edit\n")
    assert _git_status(clone).strip()  # tree is dirty

    # Try to push with injected now time
    before_head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=clone, capture_output=True, text=True).stdout.strip()
    cs.push(clone, now=T + 60)
    after_head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=clone, capture_output=True, text=True).stdout.strip()

    # Nothing should be committed
    assert before_head == after_head, "push() committed despite an active edit lease"
    assert _git_status(clone).strip(), "working tree should still be dirty"


def test_push_commits_and_pushes_dirty_files_when_no_lease_is_held(tmp_path, monkeypatch):
    """Regression guard: dirty files with no active lease should commit and push."""
    monkeypatch.setattr(cs, "LOG_PATH", tmp_path / "sync-log.md")
    monkeypatch.setattr(cs, "notify", lambda *a, **kw: None)

    clone = _make_origin_and_clone(tmp_path)

    # Dirty a file with no active session lease
    (clone / "file.md").write_text("v2\n")
    assert _git_status(clone).strip()

    cs.push(clone)

    # File should be committed and pushed
    assert not _git_status(clone).strip(), "working tree should be clean after push"
    origin_head = subprocess.run(["git", "rev-parse", "main"], cwd=clone.parent / "origin.git", capture_output=True, text=True).stdout.strip()
    clone_head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=clone, capture_output=True, text=True).stdout.strip()
    assert origin_head == clone_head, "commit should be pushed to origin"


# ── Break-it tests ──

def test_push_proceeds_once_a_held_lease_goes_stale(tmp_path, monkeypatch):
    """Builder crashes holding the lease → once the file's recorded edit timestamp ages
    past LIVE_S with no further activity, push() proceeds and commits."""
    monkeypatch.setattr(cs, "LOG_PATH", tmp_path / "sync-log.md")
    monkeypatch.setattr(cs, "notify", lambda *a, **kw: None)

    clone = _make_origin_and_clone(tmp_path)
    repo_id, _ = sw.file_key(str(clone / "file.md"))

    # Record an old edit (beyond LIVE_S)
    with sw._Locked() as st:
        sw.record_prompt(st, "sess-A", "old work", T)
        sw.record_edit(st, "sess-A", (repo_id, "file.md"), T)

    # Dirty the file
    (clone / "file.md").write_text("v2\n")

    # Push at a time when the lease is stale (more than LIVE_S seconds later)
    now = T + sw.LIVE_S + 1
    before_head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=clone, capture_output=True, text=True).stdout.strip()
    cs.push(clone, now=now)
    after_head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=clone, capture_output=True, text=True).stdout.strip()

    # Should have committed and pushed
    assert before_head != after_head, "push() should have committed once the lease is stale"
    assert not _git_status(clone).strip(), "working tree should be clean after push"
    origin_head = subprocess.run(["git", "rev-parse", "main"], cwd=clone.parent / "origin.git", capture_output=True, text=True).stdout.strip()
    assert origin_head == after_head, "commit should be pushed to origin"


def test_live_edits_for_returns_every_live_session_not_just_one(tmp_path, monkeypatch):
    """Two sessions editing at once → both appear in result (not just the first)."""
    monkeypatch.setattr(sw, "STATE_PATH", tmp_path / "s.json")

    repo_id = "/repo"
    with sw._Locked() as st:
        sw.record_prompt(st, "sess-A", "task 1", T)
        sw.record_edit(st, "sess-A", (repo_id, "file.md"), T)
        sw.record_prompt(st, "sess-B", "task 2", T + 10)
        sw.record_edit(st, "sess-B", (repo_id, "file.md"), T + 10)

    edits = sw.live_edits_for(repo_id, ["file.md"], T + 20)
    sessions = {e["session"] for e in edits}
    assert sessions == {"sess-A", "sess-B"}, "both sessions should be returned"


def test_push_defers_when_either_of_two_concurrent_sessions_holds_the_lease(
    tmp_path, monkeypatch
):
    """Two concurrent sessions editing → push still correctly defers."""
    monkeypatch.setattr(cs, "LOG_PATH", tmp_path / "sync-log.md")
    monkeypatch.setattr(cs, "notify", lambda *a, **kw: None)

    clone = _make_origin_and_clone(tmp_path)
    repo_id, _ = sw.file_key(str(clone / "file.md"))

    with sw._Locked() as st:
        sw.record_prompt(st, "sess-A", "task 1", T)
        sw.record_edit(st, "sess-A", (repo_id, "file.md"), T)
        sw.record_prompt(st, "sess-B", "task 2", T + 10)
        sw.record_edit(st, "sess-B", (repo_id, "file.md"), T + 10)

    (clone / "file.md").write_text("v2\n")
    before_head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=clone, capture_output=True, text=True).stdout.strip()
    cs.push(clone, now=T + 60)
    after_head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=clone, capture_output=True, text=True).stdout.strip()

    assert before_head == after_head, "push should defer when any session holds the lease"


def test_pull_merges_a_remote_commit_while_local_dirty_content_survives_under_a_live_edit_lease(
    tmp_path, monkeypatch
):
    """Sync on the other Mac pulling mid-edit: a second clone pushes a real commit to origin
    while this clone has local dirty content (under an active edit lease elsewhere). pull()
    must stash, merge the real remote commit, and pop — landing the remote change AND
    preserving the local in-progress edit without ever committing it."""
    monkeypatch.setattr(cs, "LOG_PATH", tmp_path / "sync-log.md")
    monkeypatch.setattr(cs, "notify", lambda *a, **kw: None)

    clone = _make_origin_and_clone(tmp_path)
    origin = clone.parent / "origin.git"
    repo_id, _ = sw.file_key(str(clone / "file.md"))

    with sw._Locked() as st:
        sw.record_prompt(st, "sess-A", "editing", T)
        sw.record_edit(st, "sess-A", (repo_id, "file.md"), T)

    # The "other Mac": a second clone commits + pushes a real, unrelated change to origin.
    other = tmp_path / "other-clone"
    subprocess.run(["git", "clone", str(origin), str(other)], check=True, capture_output=True)
    _git(other, "config", "user.email", "test@example.com")
    _git(other, "config", "user.name", "Test")
    (other / "remote-change.txt").write_text("from the other Mac\n")
    _git(other, "add", "-A")
    _git(other, "commit", "-m", "other Mac's commit")
    _git(other, "push", "origin", "main")

    before_head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=clone,
                                  capture_output=True, text=True).stdout.strip()

    (clone / "file.md").write_text("local dirty\n")
    original_content = (clone / "file.md").read_text()

    cs.pull(clone)

    after_head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=clone,
                                 capture_output=True, text=True).stdout.strip()
    origin_head = subprocess.run(["git", "rev-parse", "main"], cwd=origin,
                                  capture_output=True, text=True).stdout.strip()

    assert after_head != before_head, "pull() should have merged the remote's new commit"
    assert after_head == origin_head, "clone should now match origin's HEAD"
    assert (clone / "remote-change.txt").exists(), "the other Mac's commit should have landed"
    assert (clone / "file.md").read_text() == original_content, \
        "local mid-edit content must survive the stash/merge/pop cycle"
    assert _git_status(clone).strip(), \
        "file.md should still be dirty (uncommitted) after pull — pull() must never commit it"


# ── Robustness tests ──

def test_push_proceeds_when_sessions_state_is_missing(tmp_path, monkeypatch):
    """Missing state file → push() still commits normally, never crashes."""
    monkeypatch.setattr(cs, "LOG_PATH", tmp_path / "sync-log.md")
    monkeypatch.setattr(cs, "notify", lambda *a, **kw: None)

    clone = _make_origin_and_clone(tmp_path)
    (clone / "file.md").write_text("v2\n")

    monkeypatch.setattr(sw, "STATE_PATH", tmp_path / "missing" / "s.json")
    cs.push(clone)
    assert not _git_status(clone).strip(), "should commit when state is missing"


def test_push_proceeds_when_sessions_state_is_corrupt(tmp_path, monkeypatch):
    """Corrupt JSON state → push() still commits normally, never crashes."""
    monkeypatch.setattr(cs, "LOG_PATH", tmp_path / "sync-log.md")
    monkeypatch.setattr(cs, "notify", lambda *a, **kw: None)

    clone = _make_origin_and_clone(tmp_path)
    (clone / "file.md").write_text("v3\n")
    monkeypatch.setattr(sw, "STATE_PATH", tmp_path / "corrupt.json")
    (tmp_path / "corrupt.json").write_text("{not valid json")
    cs.push(clone)
    assert not _git_status(clone).strip(), "should commit when state is corrupt"


def test_push_proceeds_when_sessions_state_is_wrong_shape(tmp_path, monkeypatch):
    """Wrong-shaped state (list instead of dict) → push() still commits normally."""
    monkeypatch.setattr(cs, "LOG_PATH", tmp_path / "sync-log.md")
    monkeypatch.setattr(cs, "notify", lambda *a, **kw: None)

    clone = _make_origin_and_clone(tmp_path)
    (clone / "file.md").write_text("v4\n")
    monkeypatch.setattr(sw, "STATE_PATH", tmp_path / "wrong.json")
    (tmp_path / "wrong.json").write_text("[]")
    cs.push(clone)
    assert not _git_status(clone).strip(), "should commit when state is wrong shape"


def test_live_edits_for_returns_empty_for_stale_sessions():
    """Sessions older than LIVE_S are not returned, preventing stale leases."""
    repo_id = "/repo"
    stale_time = T
    current_time = T + sw.LIVE_S + 100  # way beyond LIVE_S

    with sw._Locked() as st:
        sw.record_prompt(st, "stale-session", "old work", stale_time)
        sw.record_edit(st, "stale-session", (repo_id, "file.md"), stale_time)

    # When querying at current_time, the stale session should be pruned out
    edits = sw.live_edits_for(repo_id, ["file.md"], current_time)
    assert edits == [], "stale sessions should not be returned as active leases"


def test_live_edit_lease_returns_none_for_no_changed_files(tmp_path, monkeypatch):
    """Empty input → _live_edit_lease returns None immediately."""
    monkeypatch.setattr(cs, "LOG_PATH", tmp_path / "sync-log.md")

    clone = _make_origin_and_clone(tmp_path)
    lease = cs._live_edit_lease(clone, [])
    assert lease is None, "lease should be None for empty file list"


def test_live_edit_lease_handles_a_large_changed_file_list(tmp_path, monkeypatch):
    """A few hundred changed files with one leased file → lease is found correctly."""
    monkeypatch.setattr(cs, "LOG_PATH", tmp_path / "sync-log.md")

    clone = _make_origin_and_clone(tmp_path)
    repo_id, _ = sw.file_key(str(clone / "file.md"))

    # Create a large number of files
    files = [f"file-{i}.txt" for i in range(300)]
    for fname in files:
        (clone / fname).write_text(f"content {fname}\n")
    _git(clone, "add", "-A")
    _git(clone, "commit", "-m", "add many files")
    _git(clone, "push", "origin", "main")

    # Record a lease on one file in the middle of the list
    with sw._Locked() as st:
        sw.record_prompt(st, "sess-A", "editing large set", T)
        sw.record_edit(st, "sess-A", (repo_id, "file-150.txt"), T)

    lease = cs._live_edit_lease(clone, files, now=T + 60)
    assert lease is not None, "lease should be found for file-150.txt in the large list"
    assert "file-150.txt" in lease, "lease reason should mention the leased file"


def test_push_defers_idempotently_across_repeated_calls_while_lease_holds(
    tmp_path, monkeypatch
):
    """Calling push() twice in a row while the lease holds → both defer with no partial commit."""
    monkeypatch.setattr(cs, "LOG_PATH", tmp_path / "sync-log.md")
    monkeypatch.setattr(cs, "notify", lambda *a, **kw: None)

    clone = _make_origin_and_clone(tmp_path)
    repo_id, _ = sw.file_key(str(clone / "file.md"))

    with sw._Locked() as st:
        sw.record_prompt(st, "sess-A", "work", T)
        sw.record_edit(st, "sess-A", (repo_id, "file.md"), T)

    (clone / "file.md").write_text("v2\n")
    before_head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=clone, capture_output=True, text=True).stdout.strip()

    # First call
    cs.push(clone, now=T + 60)
    after_first = subprocess.run(["git", "rev-parse", "HEAD"], cwd=clone, capture_output=True, text=True).stdout.strip()
    assert before_head == after_first, "first push should defer"

    # Second call
    cs.push(clone, now=T + 60)
    after_second = subprocess.run(["git", "rev-parse", "HEAD"], cwd=clone, capture_output=True, text=True).stdout.strip()
    assert before_head == after_second, "second push should also defer"


@pytest.mark.skipif(hasattr(os, "geteuid") and os.geteuid() == 0, reason="chmod 000 doesn't block root")
def test_push_proceeds_when_sessions_state_is_unreadable_due_to_permissions(
    tmp_path, monkeypatch
):
    """State file unreadable (chmod 000) → fails open, push() still proceeds and commits."""
    monkeypatch.setattr(cs, "LOG_PATH", tmp_path / "sync-log.md")
    monkeypatch.setattr(cs, "notify", lambda *a, **kw: None)

    clone = _make_origin_and_clone(tmp_path)
    (clone / "file.md").write_text("v2\n")

    # Create an unreadable state file
    state_file = tmp_path / "unreadable.json"
    state_file.write_text('{"sessions": {}}')
    state_file.chmod(0o000)
    monkeypatch.setattr(sw, "STATE_PATH", state_file)

    try:
        before_head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=clone, capture_output=True, text=True).stdout.strip()
        cs.push(clone)
        after_head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=clone, capture_output=True, text=True).stdout.strip()
        # Should have proceeded and committed
        assert before_head != after_head, "push() should have proceeded when state is unreadable"
        assert not _git_status(clone).strip(), "working tree should be clean after push"
        origin_head = subprocess.run(["git", "rev-parse", "main"], cwd=clone.parent / "origin.git", capture_output=True, text=True).stdout.strip()
        assert origin_head == after_head, "commit should be pushed to origin"
    finally:
        state_file.chmod(0o644)


def test_live_edits_for_treats_a_future_timestamp_as_live_not_stale(
    tmp_path, monkeypatch
):
    """A file timestamp slightly in the future (clock skew) is still live."""
    monkeypatch.setattr(sw, "STATE_PATH", tmp_path / "s.json")

    repo_id = "/repo"
    future_time = T + 100  # 100 seconds in the future
    with sw._Locked() as st:
        sw.record_prompt(st, "sess-A", "work", future_time)
        sw.record_edit(st, "sess-A", (repo_id, "file.md"), future_time)

    edits = sw.live_edits_for(repo_id, ["file.md"], T)
    assert len(edits) > 0, "future timestamp should be considered live (clock skew)"


def test_live_edits_for_ignores_old_crashed_session_entries(tmp_path, monkeypatch):
    """An old crashed session's leftover entry (well past LIVE_S) is ignored."""
    monkeypatch.setattr(sw, "STATE_PATH", tmp_path / "s.json")

    repo_id = "/repo"
    old_time = T
    current_time = T + sw.LIVE_S + 3600  # way beyond LIVE_S

    with sw._Locked() as st:
        sw.record_prompt(st, "sess-old", "ancient work", old_time)
        sw.record_edit(st, "sess-old", (repo_id, "file.md"), old_time)

    edits = sw.live_edits_for(repo_id, ["file.md"], current_time)
    assert len(edits) == 0, "old stale sessions should be pruned out"
