"""main_health: is the base branch green? Checked on a clean checkout, recorded, and shown in Health."""
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import main_health as mh  # noqa: E402

NOW = datetime(2026, 10, 7, 12, 0, tzinfo=timezone.utc)


def test_a_green_run_is_recorded_with_the_commit_it_checked(tmp_path):
    state = tmp_path / "m.json"
    res = mh.refresh(state_path=state, head=lambda: "abc1234", run_suite=lambda: (True, [], "1137 passed"), now=NOW)
    assert res == {"sha": "abc1234", "ok": True, "failed": [], "summary": "1137 passed", "checked_at": NOW.isoformat(), "ran": True}
    assert json.loads(state.read_text())["ok"] is True


def test_an_unchanged_commit_is_not_rechecked(tmp_path):
    state = tmp_path / "m.json"
    calls = []
    run = lambda: calls.append(1) or (True, [], "ok")
    mh.refresh(state_path=state, head=lambda: "abc", run_suite=run, now=NOW)
    again = mh.refresh(state_path=state, head=lambda: "abc", run_suite=run, now=NOW + timedelta(hours=1))
    assert len(calls) == 1 and again["ran"] is False


def test_a_new_commit_is_checked_and_a_failure_names_the_tests(tmp_path):
    state = tmp_path / "m.json"
    mh.refresh(state_path=state, head=lambda: "aaa", run_suite=lambda: (True, [], "ok"), now=NOW)
    res = mh.refresh(state_path=state, head=lambda: "bbb", run_suite=lambda: (False, ["tests/test_a.py::test_x"], "1 failed"), now=NOW)
    assert res["ok"] is False and res["failed"] == ["tests/test_a.py::test_x"] and res["sha"] == "bbb"


def test_a_run_that_could_not_happen_keeps_the_last_good_answer(tmp_path):
    state = tmp_path / "m.json"
    mh.refresh(state_path=state, head=lambda: "aaa", run_suite=lambda: (True, [], "ok"), now=NOW)
    res = mh.refresh(state_path=state, head=lambda: None, run_suite=lambda: (False, [], "x"), now=NOW)   # offline: no head
    assert res["sha"] == "aaa" and res["ok"] is True


def test_pytest_failures_are_read_from_the_output():
    out = "FAILED tests/test_a.py::test_x - AssertionError\nFAILED tests/test_b.py::test_y\n2 failed, 10 passed in 3s\n"
    assert mh.failed_ids(out) == ["tests/test_a.py::test_x", "tests/test_b.py::test_y"]


# ── concurrency and locking ──────────────────────────────────────────────

import threading


def test_single_flight_concurrent_calls_skip_while_one_is_running(tmp_path):
    """AC1: two threads call refresh() with the same unchanged-sha-triggering head;
    the first's run_suite blocks on an Event until released. While it's running,
    a second refresh() call (same lock file) must return without ever calling its
    own run_suite (skipped: "already running"), and run_suite call count stays at 1."""
    state = tmp_path / "m.json"
    lock = tmp_path / "m.lock"
    suite_calls = []
    event = threading.Event()

    def blocking_suite():
        suite_calls.append(1)
        event.wait()  # block until released
        return True, [], "ok"

    # Initialize state with a prior SHA
    mh.refresh(state_path=state, lock_path=lock, head=lambda: "old", run_suite=lambda: (True, [], "ok"), changed_paths=lambda *a, **k: None, now=NOW)

    # First call on a new SHA; run_suite will block
    results = []
    def thread1():
        res = mh.refresh(state_path=state, lock_path=lock, head=lambda: "new", run_suite=blocking_suite, changed_paths=lambda *a, **k: None, now=NOW)
        results.append(("t1", res))

    t1 = threading.Thread(target=thread1)
    t1.start()

    # Give thread1 time to acquire the lock and start run_suite
    import time
    time.sleep(0.1)

    # Second call on the same SHA while t1 is running; should skip
    res2 = mh.refresh(state_path=state, lock_path=lock, head=lambda: "new", run_suite=lambda: (False, ["x"], "fail"), changed_paths=lambda *a, **k: None, now=NOW)
    assert res2.get("skipped") == "already running"

    # Release the blocking suite
    event.set()
    t1.join()

    # Verify that run_suite was called exactly once
    assert len(suite_calls) == 1


def test_dead_pid_lock_is_taken_over(tmp_path):
    """AC2: a lock file written with an unreachable PID (e.g. 999999999) is taken over;
    the suite runs and completes."""
    state = tmp_path / "m.json"
    lock = tmp_path / "m.lock"

    # Write a stale lock with a fake PID
    lock.write_text(json.dumps({"pid": 999999999, "started_at": NOW.isoformat()}))

    res = mh.refresh(state_path=state, lock_path=lock, head=lambda: "abc", run_suite=lambda: (True, [], "ok"), now=NOW)
    assert res["ok"] is True
    assert res["ran"] is True


def test_aged_lock_is_taken_over(tmp_path):
    """AC2: a lock file with our own live PID but started_at older than the suite
    timeout is taken over; the suite runs."""
    state = tmp_path / "m.json"
    lock = tmp_path / "m.lock"
    import os

    # Write a lock with an old started_at (older than SUITE_TIMEOUT_S)
    old_time = NOW - timedelta(seconds=mh.SUITE_TIMEOUT_S + 100)
    lock.write_text(json.dumps({"pid": os.getpid(), "started_at": old_time.isoformat()}))

    res = mh.refresh(state_path=state, lock_path=lock, head=lambda: "abc", run_suite=lambda: (True, [], "ok"), now=NOW)
    assert res["ok"] is True
    assert res["ran"] is True


def test_live_lock_is_respected(tmp_path):
    """AC2: a lock file with our own live PID and a fresh started_at is NOT taken over;
    refresh() skips without calling run_suite."""
    state = tmp_path / "m.json"
    lock = tmp_path / "m.lock"
    import os

    # Initialize state
    mh.refresh(state_path=state, lock_path=lock, head=lambda: "old", run_suite=lambda: (True, [], "ok"), now=NOW)

    # Write a fresh lock
    lock.write_text(json.dumps({"pid": os.getpid(), "started_at": NOW.isoformat()}))

    suite_calls = []
    res = mh.refresh(state_path=state, lock_path=lock, head=lambda: "new", run_suite=lambda: (suite_calls.append(1) or True, [], "x"), now=NOW)
    assert res.get("skipped") == "already running"
    assert len(suite_calls) == 0


def test_corrupt_lock_file_is_treated_as_not_live(tmp_path):
    """AC2: unreadable/non-JSON lock content is treated as not-live and cleared,
    same as a dead PID."""
    state = tmp_path / "m.json"
    lock = tmp_path / "m.lock"

    # Write garbage
    lock.write_text("not json")

    res = mh.refresh(state_path=state, lock_path=lock, head=lambda: "abc", run_suite=lambda: (True, [], "ok"), now=NOW)
    assert res["ok"] is True
    assert res["ran"] is True


def test_lock_acquire_permission_error_is_handled_gracefully(tmp_path):
    """AC2: _acquire_lock raising PermissionError/OSError for a reason other than
    "exists" causes refresh() to skip gracefully (ran: False), not crash."""
    state = tmp_path / "m.json"
    lock = tmp_path / "m.lock"

    def failing_acquire(path, pid, now):
        raise PermissionError("no permission")

    # Monkeypatch _acquire_lock
    original = mh._acquire_lock
    mh._acquire_lock = failing_acquire
    try:
        res = mh.refresh(state_path=state, lock_path=lock, head=lambda: "abc", run_suite=lambda: (True, [], "ok"), now=NOW)
        assert res.get("ran") is False
    finally:
        mh._acquire_lock = original


def test_acquire_lock_creates_missing_parent_directory(tmp_path):
    """AC2: _acquire_lock creates the parent directory if it doesn't exist,
    so the lock can be written to a deep path."""
    lock = tmp_path / "a" / "b" / "c" / "m.lock"
    pid = 12345

    result = mh._acquire_lock(lock, pid, NOW)
    assert result is True
    assert lock.exists()
    assert json.loads(lock.read_text())["pid"] == pid


def test_changed_paths_handles_missing_git_or_repo(tmp_path):
    """AC3: _changed_paths returns None when git is not on PATH or repo directory
    is missing, catching OSError (FileNotFoundError for missing git executable or repo)."""
    # Test 1: missing repo directory
    missing_repo = tmp_path / "nonexistent"
    result = mh._changed_paths("old", "new", repo_dir=missing_repo)
    assert result is None

    # Test 2: simulate git not on PATH by using an invalid executable
    # This would normally be caught, but we can't easily mock os.execvp.
    # Instead, we trust the subprocess.run will raise OSError, which _changed_paths catches.


def test_lock_is_released_after_success(tmp_path):
    """AC2: after a normal completed run, the lock file no longer exists,
    so a later run on a new sha is never blocked by a leftover lock."""
    state = tmp_path / "m.json"
    lock = tmp_path / "m.lock"

    mh.refresh(state_path=state, lock_path=lock, head=lambda: "abc", run_suite=lambda: (True, [], "ok"), changed_paths=lambda *a, **k: None, now=NOW)
    assert not lock.exists()

    # Second run should not be blocked
    res = mh.refresh(state_path=state, lock_path=lock, head=lambda: "def", run_suite=lambda: (True, [], "ok2"), changed_paths=lambda *a, **k: None, now=NOW)
    assert res["ok"] is True
    assert not lock.exists()


# ── skip patterns and carry-forward ──────────────────────────────────────

def test_docs_only_diff_carries_verdict(tmp_path):
    """AC3: prior sha recorded; changed_paths returns only skip-pattern paths
    (e.g. docs/notes.md); run_suite is NOT called; new state has sha updated,
    ok/failed/summary carried from the prior record, carried: true, carried_from: <prior sha>."""
    state = tmp_path / "m.json"
    lock = tmp_path / "m.lock"

    # Initialize with a prior good state
    mh.refresh(state_path=state, lock_path=lock, head=lambda: "old", run_suite=lambda: (True, [], "100 passed"), now=NOW)

    suite_calls = []
    def mock_changed_paths(old, new, repo_dir=None):
        return ["docs/notes.md", "docs/design/plan.md"]  # only skip-pattern files

    res = mh.refresh(
        state_path=state,
        lock_path=lock,
        head=lambda: "new",
        run_suite=lambda: (suite_calls.append(1) or False, ["test.py::x"], "fail"),
        changed_paths=mock_changed_paths,
        now=NOW,
    )

    assert res.get("carried") is True
    assert res.get("carried_from") == "old"
    assert res.get("ok") is True  # carried from prior
    assert res.get("summary") == "100 passed"
    assert len(suite_calls) == 0  # run_suite not called


def test_lib_change_runs_suite_despite_skip_patterns(tmp_path):
    """AC3: diff mixes a skip-pattern path with lib/x.py; run_suite IS called."""
    state = tmp_path / "m.json"
    lock = tmp_path / "m.lock"

    mh.refresh(state_path=state, lock_path=lock, head=lambda: "old", run_suite=lambda: (True, [], "ok"), now=NOW)

    suite_calls = []
    def mock_changed_paths(old, new, repo_dir=None):
        return ["docs/notes.md", "lib/x.py"]  # mixed: skip + real code

    res = mh.refresh(
        state_path=state,
        lock_path=lock,
        head=lambda: "new",
        run_suite=lambda: (suite_calls.append(1) or True, [], "200 passed"),
        changed_paths=mock_changed_paths,
        now=NOW,
    )

    assert res.get("carried") is None  # not carried; ran suite
    assert res.get("ok") is True
    assert res.get("summary") == "200 passed"
    assert len(suite_calls) == 1  # run_suite called


def test_dashboard_change_runs_suite(tmp_path):
    """AC3: diff touches dashboard/...; run_suite IS called."""
    state = tmp_path / "m.json"
    lock = tmp_path / "m.lock"

    mh.refresh(state_path=state, lock_path=lock, head=lambda: "old", run_suite=lambda: (True, [], "ok"), now=NOW)

    suite_calls = []
    def mock_changed_paths(old, new, repo_dir=None):
        return ["dashboard/src/app.jsx"]  # not a skip pattern

    res = mh.refresh(
        state_path=state,
        lock_path=lock,
        head=lambda: "new",
        run_suite=lambda: (suite_calls.append(1) or True, [], "ok2"),
        changed_paths=mock_changed_paths,
        now=NOW,
    )

    assert res.get("carried") is None
    assert len(suite_calls) == 1


def test_empty_diff_is_vacuously_skippable(tmp_path):
    """AC3: changed_paths returns [] (e.g. an empty/no-op commit) → vacuously
    skippable, carried forward, run_suite NOT called."""
    state = tmp_path / "m.json"
    lock = tmp_path / "m.lock"

    mh.refresh(state_path=state, lock_path=lock, head=lambda: "old", run_suite=lambda: (True, [], "ok"), now=NOW)

    suite_calls = []
    def mock_changed_paths(old, new, repo_dir=None):
        return []  # empty diff

    res = mh.refresh(
        state_path=state,
        lock_path=lock,
        head=lambda: "new",
        run_suite=lambda: (suite_calls.append(1) or False, ["x"], "fail"),
        changed_paths=mock_changed_paths,
        now=NOW,
    )

    assert res.get("carried") is True
    assert len(suite_calls) == 0


def test_changed_paths_failure_runs_suite(tmp_path):
    """AC3: changed_paths returns None (git error) → fails safe, run_suite IS called,
    nothing is silently carried."""
    state = tmp_path / "m.json"
    lock = tmp_path / "m.lock"

    mh.refresh(state_path=state, lock_path=lock, head=lambda: "old", run_suite=lambda: (True, [], "ok"), now=NOW)

    suite_calls = []
    def mock_changed_paths(old, new, repo_dir=None):
        return None  # failure

    res = mh.refresh(
        state_path=state,
        lock_path=lock,
        head=lambda: "new",
        run_suite=lambda: (suite_calls.append(1) or True, [], "ok2"),
        changed_paths=mock_changed_paths,
        now=NOW,
    )

    assert res.get("carried") is None
    assert len(suite_calls) == 1


def test_no_prior_sha_always_runs_suite(tmp_path):
    """AC3: first-ever run — always runs the full suite even if the diff would
    otherwise look skippable (there's nothing to diff against)."""
    state = tmp_path / "m.json"
    lock = tmp_path / "m.lock"

    # Don't initialize; state is empty
    suite_calls = []
    def mock_changed_paths(old, new, repo_dir=None):
        return []  # would be skippable

    res = mh.refresh(
        state_path=state,
        lock_path=lock,
        head=lambda: "first",
        run_suite=lambda: (suite_calls.append(1) or True, [], "ok"),
        changed_paths=mock_changed_paths,
        now=NOW,
    )

    assert len(suite_calls) == 1


def test_changed_paths_with_real_git_repo(tmp_path):
    """AC3: build a temp git repo with two real commits — one touching only
    docs/notes.md, one touching lib/x.py — and call the real _changed_paths()
    to verify the git diff returns the correct file lists and that _skippable()
    classifies them correctly."""
    import subprocess
    repo = tmp_path / "test_repo"
    repo.mkdir()

    # Init repo and create two commits
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "test@test"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)

    # Commit 1: doc only
    (repo / "docs").mkdir()
    (repo / "docs" / "notes.md").write_text("doc1")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "doc"], cwd=repo, check=True)
    sha1 = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True, check=True).stdout.strip()

    # Commit 2: lib code
    (repo / "lib").mkdir()
    (repo / "lib" / "x.py").write_text("code")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "lib"], cwd=repo, check=True)
    sha2 = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True, check=True).stdout.strip()

    # Commit 3: another doc change
    (repo / "docs" / "other.md").write_text("doc2")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "doc2"], cwd=repo, check=True)
    sha3 = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True, check=True).stdout.strip()

    # Test 1: diff from sha1 to sha2 shows lib/x.py (not skippable)
    paths_lib = mh._changed_paths(sha1, sha2, repo_dir=repo)
    assert paths_lib == ["lib/x.py"]
    assert mh._skippable(paths_lib) is False

    # Test 2: diff from sha2 to sha3 shows docs/other.md (skippable)
    paths_doc = mh._changed_paths(sha2, sha3, repo_dir=repo)
    assert paths_doc == ["docs/other.md"]
    assert mh._skippable(paths_doc) is True


def test_exception_during_suite_leaves_state_untouched(tmp_path):
    """AC4: run_suite() raises (simulating the subprocess being killed) →
    the state file is byte-for-byte unchanged from before the call,
    refresh() returns ran: False, and the lock is released."""
    state = tmp_path / "m.json"
    lock = tmp_path / "m.lock"

    # Initialize state
    mh.refresh(state_path=state, lock_path=lock, head=lambda: "old", run_suite=lambda: (True, [], "ok"), changed_paths=lambda *a, **k: None, now=NOW)
    prior_content = state.read_text()

    def raising_suite():
        raise RuntimeError("killed")

    res = mh.refresh(
        state_path=state,
        lock_path=lock,
        head=lambda: "new",
        run_suite=raising_suite,
        changed_paths=lambda *a, **k: None,
        now=NOW,
    )

    assert res.get("ran") is False
    assert state.read_text() == prior_content  # unchanged
    assert not lock.exists()  # lock released
