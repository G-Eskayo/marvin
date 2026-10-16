"""main_health: is the base branch green? Checked on a clean checkout, recorded, and shown in Health."""
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import main_health as mh  # noqa: E402

NOW = datetime(2026, 10, 7, 12, 0, tzinfo=timezone.utc)


def test_a_green_run_is_recorded_with_the_commit_it_checked(tmp_path):
    state = tmp_path / "m.json"
    res = mh.refresh(state_path=state, head=lambda: "abc1234", run_suite=lambda: (True, [], "1137 passed"), now=NOW)
    assert res == {"sha": "abc1234", "tested_sha": "abc1234", "ok": True, "failed": [], "summary": "1137 passed", "checked_at": NOW.isoformat(), "ran": True}
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


# ── skip-path logic ──────────────────────────────────────────────────────────

def test_is_skippable_for_docs_files():
    assert mh._is_skippable("docs/something.txt") is True
    assert mh._is_skippable("docs/adr/0050.md") is True


def test_is_skippable_for_bench_metrics():
    assert mh._is_skippable("bench/metrics/run_1.json") is True
    assert mh._is_skippable("bench/metrics/summary.md") is True


def test_is_skippable_for_markdown_files():
    assert mh._is_skippable("README.md") is True
    assert mh._is_skippable("lib/something.md") is True
    assert mh._is_skippable("CONTEXT.md") is True


def test_is_not_skippable_for_code_files():
    assert mh._is_skippable("lib/main_health.py") is False
    assert mh._is_skippable("lib/tests/test_x.py") is False
    assert mh._is_skippable("dashboard/src/app.jsx") is False


# ── single-flight lock logic ────────────────────────────────────────────────

def test_acquire_lock_succeeds_when_none_exists(tmp_path):
    lock = tmp_path / "lock"
    assert mh._acquire_lock(lock) is True
    assert lock.exists()


def test_acquire_lock_fails_when_held_by_live_pid(tmp_path):
    import os
    lock = tmp_path / "lock"
    lock.write_text(f"{os.getpid()}\n{datetime.now(timezone.utc).timestamp()}")
    assert mh._acquire_lock(lock) is False


def test_acquire_lock_takes_over_when_pid_is_dead(tmp_path):
    lock = tmp_path / "lock"
    dead_pid = 999999  # Assume this PID is not running.
    lock.write_text(f"{dead_pid}\n{datetime.now(timezone.utc).timestamp()}")
    assert mh._acquire_lock(lock) is True
    content = lock.read_text()
    assert str(os.getpid()) in content


def test_acquire_lock_takes_over_when_stale(tmp_path):
    import time
    lock = tmp_path / "lock"
    # Lock is stale if it's older than SUITE_TIMEOUT_S + WORKTREE_SETUP_S
    old_time = (datetime.now(timezone.utc).timestamp()) - (mh.SUITE_TIMEOUT_S + mh.WORKTREE_SETUP_S + 60)
    lock.write_text(f"{os.getpid()}\n{old_time}")
    assert mh._acquire_lock(lock) is True
    assert lock.exists()


def test_release_lock_deletes_file(tmp_path):
    lock = tmp_path / "lock"
    lock.write_text(f"{os.getpid()}\n{datetime.now(timezone.utc).timestamp()}")
    mh._release_lock(lock)
    assert not lock.exists()


def test_release_lock_never_raises_on_missing_file(tmp_path):
    lock = tmp_path / "lock"
    mh._release_lock(lock)  # Should not raise.


# ── carry logic (skip suite run when only skippable files changed) ──────────

def test_carry_when_only_docs_changed(tmp_path):
    state = tmp_path / "m.json"
    def mock_changed_paths(repo_dir, old_sha, new_sha):
        return ["docs/adr/0050.md", "docs/design/x.md"]

    # Set up prior state with tested_sha.
    mh.refresh(state_path=state, head=lambda: "aaa", run_suite=lambda: (True, [], "ok"), now=NOW)

    # Refresh to a new SHA with only docs changed.
    res = mh.refresh(
        state_path=state,
        head=lambda: "bbb",
        run_suite=lambda: (False, ["bad"], "fail"),  # Should NOT be called.
        now=NOW + timedelta(hours=1),
        changed_paths=mock_changed_paths
    )
    # Suite should not have run (carried result).
    assert res["ran"] is True
    assert res["ok"] is True  # Carried from prior.
    assert res["carried"] is True
    assert res["tested_sha"] == "aaa"
    assert res["sha"] == "bbb"  # Updated sha, carried tested_sha
    # Verify explicit sha and tested_sha are written to state file
    stored = json.loads(state.read_text())
    assert stored["sha"] == "bbb"
    assert stored["tested_sha"] == "aaa"


def test_carry_when_all_md_and_docs_changed(tmp_path):
    state = tmp_path / "m.json"
    def mock_changed_paths(repo_dir, old_sha, new_sha):
        return ["README.md", "docs/x.md", "bench/metrics/run.json", "CONTEXT.md"]

    mh.refresh(state_path=state, head=lambda: "aaa", run_suite=lambda: (True, [], "passed"), now=NOW)

    res = mh.refresh(
        state_path=state,
        head=lambda: "bbb",
        run_suite=lambda: (False, ["test"], "fail"),  # Should NOT be called.
        now=NOW,
        changed_paths=mock_changed_paths
    )
    assert res["carried"] is True
    assert res["ok"] is True
    assert res["sha"] == "bbb"
    assert res["tested_sha"] == "aaa"
    # Verify stored state has explicit sha and tested_sha
    stored = json.loads(state.read_text())
    assert stored["sha"] == "bbb"
    assert stored["tested_sha"] == "aaa"


def test_no_carry_when_code_changed(tmp_path):
    state = tmp_path / "m.json"
    calls = []
    def mock_changed_paths(repo_dir, old_sha, new_sha):
        return ["lib/main_health.py", "docs/x.md"]  # Mixed: one code, one doc.

    def run_suite_that_tracks():
        calls.append(1)
        return (True, [], "ok")

    mh.refresh(state_path=state, head=lambda: "aaa", run_suite=run_suite_that_tracks, now=NOW)

    res = mh.refresh(
        state_path=state,
        head=lambda: "bbb",
        run_suite=run_suite_that_tracks,
        now=NOW,
        changed_paths=mock_changed_paths
    )
    # Should have run the suite (no carry).
    assert len(calls) == 2
    assert "carried" not in res or res.get("carried") is False


def test_carry_fails_if_git_diff_fails(tmp_path):
    state = tmp_path / "m.json"
    calls = []
    def mock_changed_paths_fails(repo_dir, old_sha, new_sha):
        return None  # Simulates git diff failure.

    def run_suite_that_tracks():
        calls.append(1)
        return (True, [], "ok")

    mh.refresh(state_path=state, head=lambda: "aaa", run_suite=run_suite_that_tracks, now=NOW)

    res = mh.refresh(
        state_path=state,
        head=lambda: "bbb",
        run_suite=run_suite_that_tracks,
        now=NOW,
        changed_paths=mock_changed_paths_fails
    )
    # Should have run the suite (no carry on diff failure).
    assert len(calls) == 2
    assert res["ok"] is True


# ── lock contention and concurrency ──────────────────────────────────────────

def test_lock_prevents_concurrent_runs(tmp_path):
    import threading
    state = tmp_path / "m.json"
    lock = tmp_path / "lock"
    calls = []
    release_event = threading.Event()

    def slow_suite():
        calls.append(1)
        release_event.wait(timeout=5)  # Wait for signal to finish.
        return (True, [], "ok")

    def t1():
        mh.refresh(state_path=state, head=lambda: "aaa", run_suite=slow_suite, now=NOW, lock_path=lock)

    def t2():
        import time
        time.sleep(0.2)  # Let t1 acquire lock and start suite.
        mh.refresh(state_path=state, head=lambda: "bbb", run_suite=slow_suite, now=NOW, lock_path=lock)

    th1 = threading.Thread(target=t1)
    th2 = threading.Thread(target=t2)
    th1.start()
    th2.start()

    import time
    time.sleep(0.5)  # Let t2 try to acquire lock and fail.
    release_event.set()  # Let t1 finish.

    th1.join()
    th2.join()

    # Only one should have called the suite (t1).
    assert len(calls) == 1


def test_lock_survives_killed_run(tmp_path):
    """When run_suite raises (simulating killed run), lock is released and prior state is returned."""
    state = tmp_path / "m.json"
    lock = tmp_path / "lock"

    # Set up prior good state
    mh.refresh(state_path=state, head=lambda: "aaa", run_suite=lambda: (True, [], "ok"), now=NOW, lock_path=lock)

    # Simulate a killed/timing-out run: suite raises
    def failing_suite():
        raise RuntimeError("timeout or killed")

    res = mh.refresh(
        state_path=state,
        head=lambda: "bbb",
        run_suite=failing_suite,
        now=NOW,
        lock_path=lock,
        changed_paths=lambda *_: ["lib/x.py"]
    )
    # Should return prior state, not a fresh run
    assert res["sha"] == "aaa"
    assert res["ok"] is True
    assert res["ran"] is False
    # Lock should be released
    assert not lock.exists()


def test_tested_sha_is_stored_on_run(tmp_path):
    state = tmp_path / "m.json"
    res = mh.refresh(
        state_path=state,
        head=lambda: "abc1234",
        run_suite=lambda: (True, [], "ok"),
        now=NOW
    )
    assert res["tested_sha"] == "abc1234"
    stored = json.loads(state.read_text())
    assert stored["tested_sha"] == "abc1234"


def test_old_format_state_without_tested_sha_works(tmp_path):
    state = tmp_path / "m.json"
    # Old state file without tested_sha field.
    state.write_text(json.dumps({"sha": "old123", "ok": True, "summary": "x", "checked_at": NOW.isoformat()}))

    def mock_changed_paths(repo_dir, old_sha, new_sha):
        return ["docs/x.md"]

    res = mh.refresh(
        state_path=state,
        head=lambda: "new456",
        run_suite=lambda: (False, [], "x"),
        now=NOW,
        changed_paths=mock_changed_paths
    )
    # Should use sha as tested_sha if tested_sha is missing.
    assert res["ok"] is True  # Carried.
    assert res["carried"] is True


def test_cannot_acquire_lock_returns_prior(tmp_path):
    """When lock is held by another live process, return prior state without running suite."""
    state = tmp_path / "m.json"
    lock = tmp_path / "lock"
    state.write_text(json.dumps({"sha": "old", "ok": True, "summary": "ok", "tested_sha": "old", "checked_at": NOW.isoformat()}))

    # Pre-populate lock with current process (so we can't acquire it).
    lock.write_text(f"{os.getpid()}\n{datetime.now(timezone.utc).timestamp()}")

    res = mh.refresh(
        state_path=state,
        head=lambda: "new",
        run_suite=lambda: (True, [], "ok"),
        now=NOW,
        lock_path=lock,
        changed_paths=lambda *_: ["lib/x.py"]
    )
    # Should return prior state (could not acquire lock).
    assert res["sha"] == "old"
    assert res["ran"] is False


def test_multiple_refreshes_with_same_commit_only_run_once(tmp_path):
    state = tmp_path / "m.json"
    lock = tmp_path / "lock"
    calls = []
    def suite_tracker():
        calls.append(1)
        return (True, [], "ok")

    mh.refresh(state_path=state, head=lambda: "abc", run_suite=suite_tracker, now=NOW, lock_path=lock)
    mh.refresh(state_path=state, head=lambda: "abc", run_suite=suite_tracker, now=NOW + timedelta(hours=1), lock_path=lock)
    mh.refresh(state_path=state, head=lambda: "abc", run_suite=suite_tracker, now=NOW + timedelta(hours=2), lock_path=lock)

    assert len(calls) == 1


# ── lock path and state behavior ──────────────────────────────────────────────

def test_lock_path_defaults_to_state_parent_directory(tmp_path):
    """Lock path defaults to the parent of state_path, not a global constant."""
    state = tmp_path / "subdir" / "state.json"
    state.parent.mkdir(parents=True, exist_ok=True)

    res = mh.refresh(
        state_path=state,
        head=lambda: "aaa",
        run_suite=lambda: (True, [], "ok"),
        now=NOW
        # Note: no lock_path arg, should default to state.parent
    )
    assert res["ran"] is True
    # Verify state file was written (lock path was correct)
    assert state.exists()
    assert json.loads(state.read_text())["sha"] == "aaa"


# ── exception handling in run_suite ───────────────────────────────────────────

def test_run_suite_exception_returns_prior(tmp_path):
    """If run_suite raises an exception, return prior state with ran=False."""
    state = tmp_path / "m.json"
    lock = tmp_path / "lock"

    # Set up prior state
    mh.refresh(state_path=state, head=lambda: "aaa", run_suite=lambda: (True, [], "ok"), now=NOW, lock_path=lock)

    # Now call refresh with run_suite that raises
    def failing_suite():
        raise RuntimeError("suite crash")

    res = mh.refresh(
        state_path=state,
        head=lambda: "bbb",
        run_suite=failing_suite,
        now=NOW,
        lock_path=lock,
        changed_paths=lambda *_: ["lib/x.py"]
    )
    # Should return prior state, not crash
    assert res["sha"] == "aaa"
    assert res["ok"] is True
    assert res["ran"] is False
    # Lock should be released
    assert not lock.exists()


def test_run_suite_exception_releases_lock(tmp_path):
    """Lock is released even if run_suite raises an exception."""
    state = tmp_path / "m.json"
    lock = tmp_path / "lock"

    mh.refresh(state_path=state, head=lambda: "aaa", run_suite=lambda: (True, [], "ok"), now=NOW, lock_path=lock)

    def failing_suite():
        raise ValueError("broken")

    mh.refresh(state_path=state, head=lambda: "bbb", run_suite=failing_suite, now=NOW, lock_path=lock, changed_paths=lambda *_: ["lib/x.py"])

    # Lock should be released (deleted)
    assert not lock.exists()


# ── atomic lock takeover ──────────────────────────────────────────────────────

def test_acquire_lock_atomic_takeover_via_temp_file(tmp_path):
    """Lock takeover unlinks stale lock and retries atomic create."""
    lock = tmp_path / "lock"

    # Pre-populate lock as stale
    old_ts = (datetime.now(timezone.utc).timestamp()) - (mh.SUITE_TIMEOUT_S + mh.WORKTREE_SETUP_S + 1)
    lock.write_text(f"99999\n{old_ts}")

    # Acquire should succeed and replace the file
    assert mh._acquire_lock(lock) is True
    new_content = lock.read_text()

    # PID should have changed
    assert str(os.getpid()) in new_content
    assert "99999" not in new_content


def test_acquire_lock_race_two_callers_one_stale_lock(tmp_path):
    """Two interleaved _acquire_lock() calls against one stale lock: exactly one wins."""
    import threading
    lock = tmp_path / "lock"
    old_ts = (datetime.now(timezone.utc).timestamp()) - (mh.SUITE_TIMEOUT_S + mh.WORKTREE_SETUP_S + 1)
    lock.write_text(f"99999\n{old_ts}")

    results = []
    barrier = threading.Barrier(2)  # Synchronize threads to increase race likelihood.

    def t1():
        barrier.wait()
        results.append(("t1", mh._acquire_lock(lock)))

    def t2():
        barrier.wait()
        results.append(("t2", mh._acquire_lock(lock)))

    th1 = threading.Thread(target=t1)
    th2 = threading.Thread(target=t2)
    th1.start()
    th2.start()
    th1.join()
    th2.join()

    # Exactly one should have succeeded.
    successes = [r for r in results if r[1] is True]
    assert len(successes) == 1
    # Lock should exist and contain one of the two thread's PIDs (both are this process, so just check it's valid).
    assert lock.exists()
    content = lock.read_text().strip().split("\n")
    assert str(os.getpid()) in content[0]


# ── _pid_alive with PermissionError ──────────────────────────────────────────

def test_pid_alive_returns_true_for_permission_error(tmp_path):
    """_pid_alive returns True for PermissionError (process exists, different owner)."""
    import unittest.mock as mock

    # Monkeypatch os.kill to raise PermissionError
    with mock.patch("os.kill", side_effect=PermissionError("Operation not permitted")):
        assert mh._pid_alive(os.getpid()) is True


# ── _release_lock checks PID ─────────────────────────────────────────────────

def test_release_lock_only_unlinks_if_pid_matches(tmp_path):
    """_release_lock only unlinks the lock if its PID matches current process."""
    lock = tmp_path / "lock"

    # Write lock with a different PID
    lock.write_text(f"99999\n{datetime.now(timezone.utc).timestamp()}")

    # Try to release; should not unlink because PID doesn't match
    mh._release_lock(lock)
    assert lock.exists()  # Should still exist

    # Write lock with current PID
    lock.write_text(f"{os.getpid()}\n{datetime.now(timezone.utc).timestamp()}")

    # Now release should unlink
    mh._release_lock(lock)
    assert not lock.exists()


def test_release_lock_handles_corrupted_lock(tmp_path):
    """_release_lock never raises, even on corrupted lock file."""
    lock = tmp_path / "lock"
    lock.write_text("corrupted data")

    mh._release_lock(lock)  # Should not raise


# ── two-dot git diff (old_sha, new_sha instead of old_sha...new_sha) ─────────

def test_changed_paths_uses_two_dot_diff(tmp_path):
    """_changed_paths uses git diff old_sha new_sha (two-dot), not three-dot.
    Demonstrated via orphan commit: two-dot succeeds where three-dot fails."""
    import subprocess

    # Create a real git repo
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True, capture_output=True)

    # Make initial commit
    (repo / "file1.txt").write_text("content1")
    subprocess.run(["git", "add", "file1.txt"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "commit1"], cwd=repo, check=True, capture_output=True)
    sha_main = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, check=True, capture_output=True, text=True).stdout.strip()

    # Create orphan commit (no parent)
    subprocess.run(["git", "checkout", "--orphan", "orphan"], cwd=repo, check=True, capture_output=True)
    (repo / "orphan_file.txt").write_text("orphan_content")
    subprocess.run(["git", "add", "orphan_file.txt"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "orphan_commit"], cwd=repo, check=True, capture_output=True)
    sha_orphan = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, check=True, capture_output=True, text=True).stdout.strip()

    # Two-dot diff: sha_main..sha_orphan (files changed from sha_main to sha_orphan)
    # Should succeed because two-dot works even with no merge-base
    two_dot_paths = mh._changed_paths(repo, sha_main, sha_orphan)
    assert "orphan_file.txt" in two_dot_paths

    # Three-dot diff fails with orphan commits (no merge-base)
    three_dot_result = subprocess.run(
        ["git", "diff", "--name-only", f"{sha_main}...{sha_orphan}"],
        cwd=repo,
        capture_output=True,
        text=True
    )
    # Three-dot fails (returns non-zero) because there's no merge-base
    assert three_dot_result.returncode != 0
    # But two-dot succeeds
    assert mh._changed_paths(repo, sha_main, sha_orphan) is not None


# ── _is_stale with widened timeout ───────────────────────────────────────────

def test_is_stale_includes_worktree_setup_timeout(tmp_path):
    """_is_stale checks SUITE_TIMEOUT_S + WORKTREE_SETUP_S, not just SUITE_TIMEOUT_S."""
    fixed_now = datetime(2026, 10, 7, 12, 0, tzinfo=timezone.utc)
    now_ts = fixed_now.timestamp()

    # Just before the total timeout
    before_total = now_ts - (mh.SUITE_TIMEOUT_S + mh.WORKTREE_SETUP_S - 1)
    assert mh._is_stale(before_total, now=fixed_now) is False

    # Just after the total timeout
    after_total = now_ts - (mh.SUITE_TIMEOUT_S + mh.WORKTREE_SETUP_S + 1)
    assert mh._is_stale(after_total, now=fixed_now) is True

    # Exactly at the total timeout (inclusive)
    at_total = now_ts - (mh.SUITE_TIMEOUT_S + mh.WORKTREE_SETUP_S)
    assert mh._is_stale(at_total, now=fixed_now) is True
