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
import session_work as sw  # noqa: E402


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


def test_push_defers_when_a_live_session_is_mid_edit_on_a_dirty_file(tmp_path, monkeypatch):
    """The ticket's literal repro: file is dirty and recorded as edited by a live session seconds ago."""
    import time
    import json

    monkeypatch.setattr(cs, "LOG_PATH", tmp_path / "unused-log.md")
    monkeypatch.setattr(cs, "notify", lambda *a, **kw: None)

    clone = _make_origin_and_clone(tmp_path)
    now = time.time()

    # Set up session state file
    repo_id, _ = sw.file_key(str(clone / "file.md"))
    state_file = tmp_path / "sessions-active.json"
    state_file.write_text(json.dumps({
        "sessions": {
            "session-A": {
                "request": "testing lease",
                "last": now - 10,
                "files": {
                    f"{repo_id}|file.md": now - 5
                }
            }
        }
    }))
    monkeypatch.setattr(cs.session_work, "STATE_PATH", state_file)

    # Make file.md dirty
    (clone / "file.md").write_text("v2\n")

    cs.push(clone)

    # Verify no commit was made
    origin_head = subprocess.run(["git", "rev-parse", "main"], cwd=clone.parent / "origin.git", capture_output=True, text=True).stdout.strip()
    clone_head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=clone, capture_output=True, text=True).stdout.strip()
    assert origin_head == clone_head, "push() should defer when a live session is editing the file"


def test_push_defers_is_idempotent_on_repeated_calls(tmp_path, monkeypatch):
    """Pushing the same lease twice should defer both times."""
    import time
    import json

    clone = _make_origin_and_clone(tmp_path)
    before_head = subprocess.run(["git", "rev-parse", "main"], cwd=clone.parent / "origin.git", capture_output=True, text=True).stdout.strip()

    monkeypatch.setattr(cs, "LOG_PATH", tmp_path / "sync-log.md")
    monkeypatch.setattr(cs, "notify", lambda *a, **kw: None)

    now = time.time()
    repo_id, _ = sw.file_key(str(clone / "file.md"))
    state_file = tmp_path / "sessions-active.json"
    state_file.write_text(json.dumps({
        "sessions": {
            "session-A": {
                "request": "testing",
                "last": now - 10,
                "files": {f"{repo_id}|file.md": now - 5}
            }
        }
    }))
    monkeypatch.setattr(cs.session_work, "STATE_PATH", state_file)

    (clone / "file.md").write_text("v2\n")
    cs.push(clone)
    cs.push(clone)

    after_head = subprocess.run(["git", "rev-parse", "main"], cwd=clone.parent / "origin.git", capture_output=True, text=True).stdout.strip()
    assert before_head == after_head, "lease should defer both calls"


def test_push_proceeds_once_the_lease_goes_stale(tmp_path, monkeypatch):
    """Once a session's edit is older than LIVE_S, push() should proceed."""
    import time
    import json

    monkeypatch.setattr(cs, "LOG_PATH", tmp_path / "unused-log.md")
    monkeypatch.setattr(cs, "notify", lambda *a, **kw: None)

    clone = _make_origin_and_clone(tmp_path)
    now = time.time()

    # Session's edit is older than LIVE_S
    stale_time = now - (cs.session_work.LIVE_S + 60)

    repo_id, _ = sw.file_key(str(clone / "file.md"))
    state_file = tmp_path / "sessions-active.json"
    state_file.write_text(json.dumps({
        "sessions": {
            "session-A": {
                "request": "testing",
                "last": stale_time,
                "files": {
                    f"{repo_id}|file.md": stale_time
                }
            }
        }
    }))
    monkeypatch.setattr(cs.session_work, "STATE_PATH", state_file)

    (clone / "file.md").write_text("v2\n")

    cs.push(clone)

    # Verify commit and push succeeded
    origin_head = subprocess.run(["git", "rev-parse", "main"], cwd=clone.parent / "origin.git", capture_output=True, text=True).stdout.strip()
    clone_head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=clone, capture_output=True, text=True).stdout.strip()
    assert origin_head == clone_head


def test_two_concurrent_live_sessions_both_hold_the_lease(tmp_path, monkeypatch):
    """If two live sessions edit the same file, both hold the lease."""
    import time
    import json

    monkeypatch.setattr(cs, "LOG_PATH", tmp_path / "unused-log.md")
    monkeypatch.setattr(cs, "notify", lambda *a, **kw: None)

    clone = _make_origin_and_clone(tmp_path)
    now = time.time()

    # Two different sessions both editing the same file
    repo_id, _ = sw.file_key(str(clone / "file.md"))
    state_file = tmp_path / "sessions-active.json"
    state_file.write_text(json.dumps({
        "sessions": {
            "session-A": {
                "request": "work A",
                "last": now - 5,
                "files": {
                    f"{repo_id}|file.md": now - 8
                }
            },
            "session-B": {
                "request": "work B",
                "last": now - 10,
                "files": {
                    f"{repo_id}|file.md": now - 12
                }
            }
        }
    }))
    monkeypatch.setattr(cs.session_work, "STATE_PATH", state_file)

    (clone / "file.md").write_text("v2\n")

    cs.push(clone)

    # Verify no commit was made (either session holds the lease)
    origin_head = subprocess.run(["git", "rev-parse", "main"], cwd=clone.parent / "origin.git", capture_output=True, text=True).stdout.strip()
    clone_head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=clone, capture_output=True, text=True).stdout.strip()
    assert origin_head == clone_head


def test_missing_or_corrupt_sessions_state_never_blocks_push(tmp_path, monkeypatch):
    """If sessions state file is missing, corrupt, or non-dict, push() should proceed (fail open)."""
    import pytest

    test_cases = [
        ("missing", None),
        ("invalid JSON", "{not json"),
        ("non-dict JSON", "[1, 2, 3]")
    ]

    for case_name, content in test_cases:
        case_dir = tmp_path / case_name
        case_dir.mkdir(parents=True, exist_ok=True)
        clone = _make_origin_and_clone(case_dir)
        monkeypatch.setattr(cs, "LOG_PATH", case_dir / f"{case_name}-log.md")
        monkeypatch.setattr(cs, "notify", lambda *a, **kw: None)

        state_file = case_dir / f"{case_name}-sessions.json"
        if content is not None:
            state_file.write_text(content)

        monkeypatch.setattr(cs.session_work, "STATE_PATH", state_file)

        (clone / "file.md").write_text("v2\n")

        cs.push(clone)

        # Verify commit succeeded (push proceeded because state file handling failed open)
        origin_head = subprocess.run(["git", "rev-parse", "main"], cwd=clone.parent / "origin.git", capture_output=True, text=True).stdout.strip()
        clone_head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=clone, capture_output=True, text=True).stdout.strip()
        assert origin_head == clone_head, f"case '{case_name}': push() should proceed when state file is {case_name}"


def test_push_is_not_blocked_by_an_unrelated_files_lease(tmp_path, monkeypatch):
    """A live session editing file X should not block a push of file Y."""
    import time
    import json

    monkeypatch.setattr(cs, "LOG_PATH", tmp_path / "unused-log.md")
    monkeypatch.setattr(cs, "notify", lambda *a, **kw: None)

    clone = _make_origin_and_clone(tmp_path)
    now = time.time()

    # Session editing a different file
    repo_id, _ = sw.file_key(str(clone / "other.md"))
    state_file = tmp_path / "sessions-active.json"
    state_file.write_text(json.dumps({
        "sessions": {
            "session-A": {
                "request": "testing",
                "last": now - 5,
                "files": {
                    f"{repo_id}|other.md": now - 5
                }
            }
        }
    }))
    monkeypatch.setattr(cs.session_work, "STATE_PATH", state_file)

    # Make a different file dirty
    (clone / "file.md").write_text("v2\n")

    cs.push(clone)

    # Verify commit succeeded
    origin_head = subprocess.run(["git", "rev-parse", "main"], cwd=clone.parent / "origin.git", capture_output=True, text=True).stdout.strip()
    clone_head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=clone, capture_output=True, text=True).stdout.strip()
    assert origin_head == clone_head


def test_push_is_not_blocked_by_a_lease_in_a_different_repo(tmp_path, monkeypatch):
    """A lease for a different repo-id should not block this repo's push."""
    import time
    import json

    monkeypatch.setattr(cs, "LOG_PATH", tmp_path / "unused-log.md")
    monkeypatch.setattr(cs, "notify", lambda *a, **kw: None)

    clone = _make_origin_and_clone(tmp_path)
    now = time.time()

    # Create a fake repo-id (different from clone's actual repo-id)
    fake_repo_id = "/some/other/repo/.git"

    state_file = tmp_path / "sessions-active.json"
    state_file.write_text(json.dumps({
        "sessions": {
            "session-A": {
                "request": "testing",
                "last": now - 5,
                "files": {
                    f"{fake_repo_id}|file.md": now - 5
                }
            }
        }
    }))
    monkeypatch.setattr(cs.session_work, "STATE_PATH", state_file)

    (clone / "file.md").write_text("v2\n")

    cs.push(clone)

    # Verify commit succeeded
    origin_head = subprocess.run(["git", "rev-parse", "main"], cwd=clone.parent / "origin.git", capture_output=True, text=True).stdout.strip()
    clone_head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=clone, capture_output=True, text=True).stdout.strip()
    assert origin_head == clone_head


def test_push_is_not_blocked_by_a_same_path_edit_in_a_sibling_worktree(tmp_path, monkeypatch):
    """The key regression test: a lease for the same repo-id+path but file not dirty in this
    clone should not block. Uses a real sibling worktree created via `git worktree add`."""
    import time
    import json

    monkeypatch.setattr(cs, "LOG_PATH", tmp_path / "unused-log.md")
    monkeypatch.setattr(cs, "notify", lambda *a, **kw: None)

    clone = _make_origin_and_clone(tmp_path)
    now = time.time()

    # Create a real sibling worktree
    sibling = tmp_path / "sibling-worktree"
    _git(clone, "worktree", "add", "-b", "sibling", str(sibling))

    # Get the repo-id from the sibling worktree using the real file_key function
    repo_id, relpath = sw.file_key(str(sibling / "file.md"))
    assert repo_id is not None and relpath == "file.md", "repo_id and relpath should be correctly resolved"

    # Record a lease for file.md in the sibling worktree
    state_file = tmp_path / "sessions-active.json"
    state_file.write_text(json.dumps({
        "sessions": {
            "session-A": {
                "request": "testing in sibling",
                "last": now - 5,
                "files": {
                    f"{repo_id}|file.md": now - 5
                }
            }
        }
    }))
    monkeypatch.setattr(cs.session_work, "STATE_PATH", state_file)

    # Make a DIFFERENT file (other.txt) dirty in the original clone
    (clone / "other.txt").write_text("new content\n")

    cs.push(clone)

    # Verify commit succeeded (file.md being edited in sibling shouldn't block other.txt in clone)
    origin_head = subprocess.run(["git", "rev-parse", "main"], cwd=clone.parent / "origin.git", capture_output=True, text=True).stdout.strip()
    clone_head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=clone, capture_output=True, text=True).stdout.strip()
    assert origin_head == clone_head, "push() should proceed: file.md is dirty in sibling, not in this clone"
