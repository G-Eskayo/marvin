"""main_health: is the base branch green? Checked on a clean checkout, recorded, and shown in Health."""
import json
import os
import subprocess
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import main_health as mh  # noqa: E402

NOW = datetime(2026, 10, 7, 12, 0, tzinfo=timezone.utc)


def test_a_green_run_is_recorded_with_the_commit_it_checked(tmp_path):
    state = tmp_path / "m.json"
    lock = tmp_path / "lock.json"
    res = mh.refresh(state_path=state, lock_path=lock, head=lambda: "abc1234", run_suite=lambda: (True, [], "1137 passed"), now=NOW)
    assert res == {"sha": "abc1234", "ok": True, "failed": [], "summary": "1137 passed", "checked_at": NOW.isoformat(), "ran": True}
    assert json.loads(state.read_text())["ok"] is True


def test_an_unchanged_commit_is_not_rechecked(tmp_path):
    state = tmp_path / "m.json"
    lock = tmp_path / "lock.json"
    calls = []
    run = lambda: calls.append(1) or (True, [], "ok")
    mh.refresh(state_path=state, lock_path=lock, head=lambda: "abc", run_suite=run, now=NOW)
    again = mh.refresh(state_path=state, lock_path=lock, head=lambda: "abc", run_suite=run, now=NOW + timedelta(hours=1))
    assert len(calls) == 1 and again["ran"] is False


def test_a_new_commit_is_checked_and_a_failure_names_the_tests(tmp_path):
    state = tmp_path / "m.json"
    lock = tmp_path / "lock.json"
    mh.refresh(state_path=state, lock_path=lock, head=lambda: "aaa", run_suite=lambda: (True, [], "ok"), now=NOW)
    res = mh.refresh(state_path=state, lock_path=lock, head=lambda: "bbb", run_suite=lambda: (False, ["tests/test_a.py::test_x"], "1 failed"), now=NOW)
    assert res["ok"] is False and res["failed"] == ["tests/test_a.py::test_x"] and res["sha"] == "bbb"


def test_a_run_that_could_not_happen_keeps_the_last_good_answer(tmp_path):
    state = tmp_path / "m.json"
    lock = tmp_path / "lock.json"
    mh.refresh(state_path=state, lock_path=lock, head=lambda: "aaa", run_suite=lambda: (True, [], "ok"), now=NOW)
    res = mh.refresh(state_path=state, lock_path=lock, head=lambda: None, run_suite=lambda: (False, [], "x"), now=NOW)   # offline: no head
    assert res["sha"] == "aaa" and res["ok"] is True


def test_pytest_failures_are_read_from_the_output():
    out = "FAILED tests/test_a.py::test_x - AssertionError\nFAILED tests/test_b.py::test_y\n2 failed, 10 passed in 3s\n"
    assert mh.failed_ids(out) == ["tests/test_a.py::test_x", "tests/test_b.py::test_y"]


# New tests for locking and carry-forward (test cases 1-15 from the design doc)

def test_lock_single_flight_blocks_concurrent_refresh(tmp_path):
    """Two refreshes started together: only one calls run_suite; the other returns skipped."""
    state = tmp_path / "m.json"
    lock = tmp_path / "lock.json"

    t1_acquired = threading.Event()  # t1 signals when it has the lock
    t1_continue = threading.Event()  # Main signals when t1 can continue
    calls = []

    def blocking_suite():
        calls.append("called")
        t1_acquired.set()
        t1_continue.wait()
        return (True, [], "ok")

    results = [None, None]

    def thread_refresh(idx):
        results[idx] = mh.refresh(state_path=state, lock_path=lock, head=lambda: "sha1", run_suite=blocking_suite, now=NOW)

    # Start t1
    t1 = threading.Thread(target=thread_refresh, args=(0,))
    t1.start()

    # Wait for t1 to acquire and start running suite
    t1_acquired.wait(timeout=1.0)

    # Now start t2 while t1 is still running
    t2 = threading.Thread(target=thread_refresh, args=(1,))
    t2.start()

    # Give t2 time to try acquiring the lock
    time.sleep(0.05)

    # Unblock t1
    t1_continue.set()
    t1.join()
    t2.join()

    # t2 should have gotten "already running" without calling run_suite
    assert len(calls) == 1 and results[1].get("skipped") == "already running"


def test_live_lock_file_is_respected(tmp_path):
    """A live lock with our PID is respected — refresh skips run_suite."""
    state = tmp_path / "m.json"
    lock = tmp_path / "lock.json"

    # Create a prior state so we can compare
    state.write_text(json.dumps({"sha": "old", "ok": True, "failed": [], "summary": "ok", "checked_at": NOW.isoformat()}))

    # Write a live lock file with current process PID and recent timestamp
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.write_text(json.dumps({"pid": os.getpid(), "started_at": NOW.isoformat()}))

    calls = []
    def track_suite():
        calls.append("called")
        return (True, [], "ok")

    res = mh.refresh(state_path=state, lock_path=lock, head=lambda: "new", run_suite=track_suite, now=NOW + timedelta(seconds=10))
    assert len(calls) == 0 and res["skipped"] == "already running"


def test_stale_lock_with_dead_pid_is_taken_over(tmp_path):
    """A stale lock with a dead PID is replaced."""
    state = tmp_path / "m.json"
    lock = tmp_path / "lock.json"
    lock.parent.mkdir(parents=True, exist_ok=True)

    # Create a subprocess and let it exit, capturing its PID
    p = subprocess.Popen(["true"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    dead_pid = p.pid
    p.wait()  # Let it exit

    # Write a lock file with the dead PID
    lock.write_text(json.dumps({"pid": dead_pid, "started_at": NOW.isoformat()}))

    calls = []
    def track_suite():
        calls.append("called")
        return (True, [], "passed")

    res = mh.refresh(state_path=state, lock_path=lock, head=lambda: "sha1", run_suite=track_suite, now=NOW + timedelta(seconds=10))
    assert len(calls) == 1 and res["ran"] is True and res["summary"] == "passed"


def test_stale_lock_with_old_timestamp_is_taken_over(tmp_path):
    """A stale lock with a live PID but old timestamp is replaced."""
    state = tmp_path / "m.json"
    lock = tmp_path / "lock.json"
    lock.parent.mkdir(parents=True, exist_ok=True)

    # Write a lock with a very old timestamp
    old_time = NOW - timedelta(hours=2)
    lock.write_text(json.dumps({"pid": os.getpid(), "started_at": old_time.isoformat()}))

    calls = []
    def track_suite():
        calls.append("called")
        return (True, [], "ok")

    res = mh.refresh(state_path=state, lock_path=lock, head=lambda: "sha1", run_suite=track_suite, now=NOW)
    assert len(calls) == 1 and res["ran"] is True


def test_corrupted_lock_file_is_taken_over(tmp_path):
    """A corrupted (unreadable) lock file is treated as stale."""
    state = tmp_path / "m.json"
    lock = tmp_path / "lock.json"
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.write_text("corrupted json {{{")

    calls = []
    def track_suite():
        calls.append("called")
        return (True, [], "ok")

    res = mh.refresh(state_path=state, lock_path=lock, head=lambda: "sha1", run_suite=track_suite, now=NOW)
    assert len(calls) == 1 and res["ran"] is True


def test_docs_only_commit_carries_prior_verdict(tmp_path):
    """A commit with only docs changes carries the prior test result."""
    state = tmp_path / "m.json"
    lock = tmp_path / "lock.json"

    # Record a prior green result
    state.write_text(json.dumps({
        "sha": "aaa0001", "ok": True, "failed": [], "summary": "100 passed",
        "checked_at": NOW.isoformat()
    }))

    def mock_changed_paths(prior, new):
        return ["docs/README.md", "docs/api/handlers.md"]

    calls = []
    def track_suite():
        calls.append("called")
        return (False, ["x"], "1 failed")  # Would fail if called

    res = mh.refresh(
        state_path=state, lock_path=lock, head=lambda: "aaa0002",
        run_suite=track_suite, changed_paths=mock_changed_paths, now=NOW
    )

    assert len(calls) == 0, "Should not call run_suite"
    assert res["carried"] is True
    assert res["carried_from"] == "aaa0001"
    assert res["ok"] is True  # Verdict carried forward
    assert res["sha"] == "aaa0002"  # New sha recorded
    assert res["checked_at"] == NOW.isoformat()
    # State file should be persisted with the carried verdict
    assert json.loads(state.read_text()) == {
        "sha": "aaa0002", "ok": True, "failed": [], "summary": "100 passed",
        "checked_at": NOW.isoformat(), "carried": True, "carried_from": "aaa0001"
    }


def test_chained_docs_carry_points_to_original_tested_sha(tmp_path):
    """A second docs-only commit keeps carried_from pointing to the original tested sha."""
    state = tmp_path / "m.json"
    lock = tmp_path / "lock.json"

    # Start with a tested sha
    state.write_text(json.dumps({
        "sha": "aaa0001", "ok": True, "failed": [], "summary": "100 passed",
        "checked_at": NOW.isoformat()
    }))

    # First carry: docs-only commit
    def mock_changed_paths_1(prior, new):
        if prior == "aaa0001" and new == "aaa0002":
            return ["docs/file.md"]
        return ["other"]

    res1 = mh.refresh(
        state_path=state, lock_path=lock, head=lambda: "aaa0002",
        run_suite=lambda: (False, [], "x"), changed_paths=mock_changed_paths_1, now=NOW
    )
    assert res1["carried_from"] == "aaa0001"

    # Second carry: another docs-only commit (let first call's persistence drive the second)
    def mock_changed_paths_2(prior, new):
        # Assert that the args match what we expect—the first carry's persistence should drive this
        assert (prior, new) == ("aaa0001", "aaa0003"), "persistence regressed"
        if prior == "aaa0001" and new == "aaa0003":
            return ["docs/other.md"]
        return ["other"]

    res2 = mh.refresh(
        state_path=state, lock_path=lock, head=lambda: "aaa0003",
        run_suite=lambda: (False, [], "x"), changed_paths=mock_changed_paths_2, now=NOW
    )
    assert res2["carried_from"] == "aaa0001", "Should still point to the original tested sha"


def test_mixed_relevant_and_irrelevant_changes_runs_suite(tmp_path):
    """A commit mixing doc files with lib/** changes runs the full suite."""
    state = tmp_path / "m.json"
    lock = tmp_path / "lock.json"

    state.write_text(json.dumps({
        "sha": "aaa0001", "ok": True, "failed": [], "summary": "100 passed",
        "checked_at": NOW.isoformat()
    }))

    def mock_changed_paths(prior, new):
        return ["docs/file.md", "lib/main_health.py"]  # Mix of irrelevant and relevant

    calls = []
    def track_suite():
        calls.append("called")
        return (False, ["test_x"], "1 failed")

    res = mh.refresh(
        state_path=state, lock_path=lock, head=lambda: "aaa0002",
        run_suite=track_suite, changed_paths=mock_changed_paths, now=NOW
    )

    assert len(calls) == 1, "Should call run_suite for mixed changes"
    assert res["ran"] is True
    assert "carried" not in res, "Should not mark as carried"


def test_unreadable_diff_runs_suite_fails_closed(tmp_path):
    """When changed_paths returns None (diff unreadable), run the full suite."""
    state = tmp_path / "m.json"
    lock = tmp_path / "lock.json"

    state.write_text(json.dumps({
        "sha": "aaa0001", "ok": True, "failed": [], "summary": "100 passed",
        "checked_at": NOW.isoformat()
    }))

    calls = []
    def track_suite():
        calls.append("called")
        return (True, [], "100 passed")

    res = mh.refresh(
        state_path=state, lock_path=lock, head=lambda: "aaa0002",
        run_suite=track_suite, changed_paths=lambda p, n: None, now=NOW  # Diff fails
    )

    assert len(calls) == 1, "Should run suite when diff is unreadable"
    assert res["ran"] is True


def test_empty_diff_vacuously_carries(tmp_path):
    """A commit with no changed files (empty merge) is vacuously carried."""
    state = tmp_path / "m.json"
    lock = tmp_path / "lock.json"

    state.write_text(json.dumps({
        "sha": "aaa0001", "ok": True, "failed": [], "summary": "100 passed",
        "checked_at": NOW.isoformat()
    }))

    calls = []
    def track_suite():
        calls.append("called")
        return (False, [], "fail")

    res = mh.refresh(
        state_path=state, lock_path=lock, head=lambda: "aaa0002",
        run_suite=track_suite, changed_paths=lambda p, n: [], now=NOW  # No changed files
    )

    assert len(calls) == 0, "Should not call run_suite for empty diff"
    assert res["carried"] is True


def test_first_run_never_carries(tmp_path):
    """First-ever run (no prior state) always runs the suite."""
    state = tmp_path / "m.json"
    lock = tmp_path / "lock.json"

    # No prior state file
    calls = []
    def track_suite():
        calls.append("called")
        return (True, [], "100 passed")

    res = mh.refresh(
        state_path=state, lock_path=lock, head=lambda: "aaa0001",
        run_suite=track_suite, changed_paths=lambda p, n: [], now=NOW
    )

    assert len(calls) == 1, "First run should always call run_suite"
    assert res["ran"] is True
    assert "carried" not in res


def test_killed_run_leaves_state_unchanged_and_releases_lock(tmp_path):
    """If run_suite raises (simulating a killed process), state is not updated but lock is released."""
    state = tmp_path / "m.json"
    lock = tmp_path / "lock.json"

    original_state = {"sha": "aaa0001", "ok": True, "failed": [], "summary": "ok", "checked_at": NOW.isoformat()}
    state.write_text(json.dumps(original_state))

    def failing_suite():
        raise RuntimeError("Process killed")

    try:
        mh.refresh(
            state_path=state, lock_path=lock, head=lambda: "aaa0002",
            run_suite=failing_suite, now=NOW
        )
    except RuntimeError:
        pass  # Expected

    # State file should be unchanged
    assert json.loads(state.read_text()) == original_state

    # Lock should be released
    assert not lock.exists() or mh._lock_is_stale(lock, now=NOW + timedelta(seconds=1))


def test_sequential_calls_do_not_leak_lock(tmp_path):
    """Two sequential refresh() calls both complete normally without deadlock."""
    state = tmp_path / "m.json"
    lock = tmp_path / "lock.json"

    def mock_suite_1():
        return (True, [], "100 passed")

    def mock_suite_2():
        return (True, [], "150 passed")

    res1 = mh.refresh(
        state_path=state, lock_path=lock, head=lambda: "aaa0001",
        run_suite=mock_suite_1, now=NOW
    )
    assert res1["ran"] is True

    # Lock should be released; second call should succeed
    res2 = mh.refresh(
        state_path=state, lock_path=lock, head=lambda: "aaa0002",
        run_suite=mock_suite_2, now=NOW
    )
    assert res2["ran"] is True


def test_lock_parent_directory_is_created(tmp_path):
    """Lock file's parent directory is created if it doesn't exist."""
    state = tmp_path / "m.json"
    lock = tmp_path / "nonexistent" / "dir" / "lock.json"

    res = mh.refresh(
        state_path=state, lock_path=lock, head=lambda: "aaa0001",
        run_suite=lambda: (True, [], "ok"), now=NOW
    )

    assert res["ran"] is True
    # Lock should have been created and then released
    assert not lock.exists() or mh._lock_is_stale(lock, now=NOW + timedelta(seconds=1))


def test_concurrent_stale_takeover_has_exactly_one_winner(tmp_path):
    """Multiple threads racing to take over a stale lock: exactly one wins."""
    lock = tmp_path / "lock.json"
    lock.parent.mkdir(parents=True, exist_ok=True)

    # Pre-write a stale (dead-PID) lock
    p = subprocess.Popen(["true"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    dead_pid = p.pid
    p.wait()
    lock.write_text(json.dumps({"pid": dead_pid, "started_at": NOW.isoformat()}))

    # Hit _acquire_lock from multiple threads via a Barrier to maximize collision
    results = []
    barrier = threading.Barrier(8)

    def try_acquire():
        barrier.wait()  # Synchronize all threads to start at the same time
        results.append(mh._acquire_lock(lock, now=NOW + timedelta(seconds=10)))

    threads = [threading.Thread(target=try_acquire) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # Exactly one should have won
    assert results.count(True) == 1, f"Expected exactly one True, got {results}"


@pytest.mark.skipif(os.getuid() == 0, reason="Test requires non-root")
def test_lock_with_other_users_pid_is_treated_as_alive(tmp_path):
    """A lock with pid 1 (owned by root) is not treated as dead by a non-root process."""
    lock = tmp_path / "lock.json"
    lock.parent.mkdir(parents=True, exist_ok=True)

    # Write a lock with pid 1 (owned by root). Non-root sending signal 0 raises PermissionError.
    lock.write_text(json.dumps({"pid": 1, "started_at": NOW.isoformat()}))

    # _lock_is_stale should return False: PermissionError means the process is alive
    assert mh._lock_is_stale(lock, now=NOW) is False


def test_malformed_started_at_is_treated_as_stale(tmp_path):
    """A lock with a malformed started_at timestamp is treated as stale."""
    lock = tmp_path / "lock.json"
    lock.parent.mkdir(parents=True, exist_ok=True)

    # Write a lock with started_at missing timezone (will cause fromisoformat to raise)
    lock.write_text(json.dumps({"pid": os.getpid(), "started_at": "2026-10-07T12:00:00"}))

    # _lock_is_stale should return True (malformed), not raise TypeError
    is_stale = mh._lock_is_stale(lock, now=NOW)
    assert is_stale is True


def test_doc_files_read_by_real_tests_are_not_treated_as_irrelevant(tmp_path):
    """Files in TEST_RELEVANT_DOCS are not treated as irrelevant, others are."""
    # These should be treated as relevant (not irrelevant)
    assert mh._is_test_irrelevant("CONTEXT.md") is False
    assert mh._is_test_irrelevant("docs/north-stars.md") is False
    assert mh._is_test_irrelevant("docs/impact.md") is False
    assert mh._is_test_irrelevant("README.md") is False

    # Other doc files should still be treated as irrelevant
    assert mh._is_test_irrelevant("docs/agents/decisions-format.md") is True
    assert mh._is_test_irrelevant("docs/api/handlers.md") is True


def test_carry_bumps_checked_at_so_health_does_not_go_stale(tmp_path):
    """When a carry happens, checked_at is updated to now, not left stale."""
    state = tmp_path / "m.json"
    lock = tmp_path / "lock.json"

    # Record a prior result with an old checked_at timestamp (30 hours old)
    old_checked_at = NOW - timedelta(hours=30)
    state.write_text(json.dumps({
        "sha": "aaa0001", "ok": True, "failed": [], "summary": "100 passed",
        "checked_at": old_checked_at.isoformat()
    }))

    def mock_changed_paths(prior, new):
        return ["docs/file.md"]  # Only docs changes

    res = mh.refresh(
        state_path=state, lock_path=lock, head=lambda: "aaa0002",
        run_suite=lambda: (False, [], "x"), changed_paths=mock_changed_paths, now=NOW
    )

    # checked_at should be bumped to NOW, not left at the old value
    assert res["checked_at"] == NOW.isoformat()
    assert res["checked_at"] != old_checked_at.isoformat()


def test_pattern_matching_for_test_irrelevant_paths():
    """Unit test: each path matches correctly against TEST_IRRELEVANT patterns."""
    assert mh._is_test_irrelevant("docs/x/y.md")
    assert mh._is_test_irrelevant("docs/README.md")
    assert mh._is_test_irrelevant("bench/metrics/foo.json")
    assert mh._is_test_irrelevant("CHANGELOG.md")
    assert mh._is_test_irrelevant("sync-log.md")
    assert mh._is_test_irrelevant("foo.log")

    # Should NOT match:
    assert not mh._is_test_irrelevant("lib/main_health.py")
    assert not mh._is_test_irrelevant("dashboard/src/x.js")
    assert not mh._is_test_irrelevant("bin/foo")
    assert not mh._is_test_irrelevant("")


def test_red_is_never_carried_forward(tmp_path):
    """A red (failed) result is never carried forward, even with test-irrelevant changes."""
    state = tmp_path / "m.json"
    lock = tmp_path / "lock.json"

    # Record a prior red result
    state.write_text(json.dumps({
        "sha": "aaa0001", "ok": False, "failed": ["test_x"], "summary": "1 failed",
        "checked_at": NOW.isoformat()
    }))

    def mock_changed_paths(prior, new):
        return ["docs/file.md"]  # Only docs changes

    calls = []
    def track_suite():
        calls.append("called")
        return (True, [], "100 passed")  # Would pass if called

    res = mh.refresh(
        state_path=state, lock_path=lock, head=lambda: "aaa0002",
        run_suite=track_suite, changed_paths=mock_changed_paths, now=NOW
    )

    assert len(calls) == 1, "Should re-run after red, never carry red forward"
    assert res["ran"] is True
    assert "carried" not in res


def test_lib_tests_changes_always_trigger_rerun(tmp_path):
    """Changes to lib/tests/* always trigger a re-run, never carried."""
    state = tmp_path / "m.json"
    lock = tmp_path / "lock.json"

    # Record a prior green result
    state.write_text(json.dumps({
        "sha": "aaa0001", "ok": True, "failed": [], "summary": "100 passed",
        "checked_at": NOW.isoformat()
    }))

    def mock_changed_paths(prior, new):
        return ["lib/tests/test_x.py"]  # Test file changed

    calls = []
    def track_suite():
        calls.append("called")
        return (False, ["test_y"], "1 failed")

    res = mh.refresh(
        state_path=state, lock_path=lock, head=lambda: "aaa0002",
        run_suite=track_suite, changed_paths=mock_changed_paths, now=NOW
    )

    assert len(calls) == 1, "lib/tests/* changes should not be carried"
    assert res["ran"] is True
    assert "carried" not in res


def test_release_lock_unlinks_only_owned_lock(tmp_path):
    """_release_lock unlinks the lock only if it's owned by the current process."""
    lock = tmp_path / "lock.json"
    lock.parent.mkdir(parents=True, exist_ok=True)

    # Write a lock with our PID
    lock.write_text(json.dumps({"pid": os.getpid(), "started_at": NOW.isoformat()}))

    # Release it
    mh._release_lock(lock)

    # Lock should be gone
    assert not lock.exists()


def test_release_lock_skips_other_process_lock(tmp_path):
    """_release_lock does not unlink locks owned by other processes."""
    lock = tmp_path / "lock.json"
    lock.parent.mkdir(parents=True, exist_ok=True)

    # Write a lock with a different PID
    other_pid = os.getpid() + 99999  # Unlikely to be a real process
    lock.write_text(json.dumps({"pid": other_pid, "started_at": NOW.isoformat()}))

    # Try to release it
    mh._release_lock(lock)

    # Lock should still exist (we don't own it)
    assert lock.exists()
    # Verify the contents are unchanged
    data = json.loads(lock.read_text())
    assert data["pid"] == other_pid
