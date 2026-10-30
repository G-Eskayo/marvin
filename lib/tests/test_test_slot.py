"""Tests for test_slot.py (marvin#940: one test run at a time on a machine, merges first). Run via:
    ~/.agents/venv/bin/python -m pytest lib/tests/test_test_slot.py -v

Contention is checked with real processes on real locks in tmp_path: each run writes when it starts and ends, and the
test reads the order back. Free memory is injected (it can't be set), the lock files are not.
"""
from __future__ import annotations
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

LIB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LIB))

import test_slot as ts  # noqa: E402

SCRIPT = LIB / "test_slot.py"


@pytest.fixture
def slot_dir(tmp_path, monkeypatch):
    d = tmp_path / "slot"
    monkeypatch.setenv(ts.DIR_ENV, str(d))
    monkeypatch.delenv(ts.HELD_ENV, raising=False)
    return d


def _env(slot_dir):
    env = {k: v for k, v in os.environ.items() if k != ts.HELD_ENV}
    return {**env, ts.DIR_ENV: str(slot_dir)}


def _run(slot_dir, log, name, secs, merge=False):
    """A test run through the slot that logs '<name> start' and '<name> end' around a sleep."""
    body = f"echo '{name} start' >> {log}; sleep {secs}; echo '{name} end' >> {log}"
    return subprocess.Popen([sys.executable, str(SCRIPT), "run", "--what", name, *(["--merge"] if merge else []),
                             "--", "/bin/sh", "-c", body], env=_env(slot_dir))


def _wait_for(pred, timeout=10.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:   # test-side wait for a real process to reach a state, bounded
        if pred():
            return True
        time.sleep(0.02)
    return False


def _lines(log):
    return log.read_text().split("\n")[:-1] if log.exists() else []


def test_two_runs_at_once_never_overlap(slot_dir, tmp_path):
    log = tmp_path / "order.log"
    a = _run(slot_dir, log, "a", 0.6)
    assert _wait_for(lambda: "a start" in _lines(log))
    b = _run(slot_dir, log, "b", 0.1)
    assert a.wait(10) == 0 and b.wait(10) == 0
    assert _lines(log) == ["a start", "a end", "b start", "b end"]


def test_a_waiting_merge_goes_before_a_helper_that_was_waiting_first(slot_dir, tmp_path):
    log = tmp_path / "order.log"
    first = _run(slot_dir, log, "suite", 0.8)
    assert _wait_for(lambda: "suite start" in _lines(log))
    helper = _run(slot_dir, log, "helper", 0.1)
    time.sleep(0.2)   # the helper is queued first
    merge = _run(slot_dir, log, "merge", 0.1, merge=True)
    for p in (first, helper, merge):
        assert p.wait(15) == 0
    assert _lines(log) == ["suite start", "suite end", "merge start", "merge end", "helper start", "helper end"]


def test_a_helper_run_waits_while_a_merge_is_running_even_with_the_slot_free(slot_dir, tmp_path):
    log = tmp_path / "order.log"
    hold = subprocess.Popen([sys.executable, str(SCRIPT), "hold-merge"], env=_env(slot_dir),
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    assert hold.stdout.readline().strip() == "held"
    assert ts.merge_pending(slot_dir)
    helper = _run(slot_dir, log, "helper", 0.1)
    time.sleep(0.4)
    assert _lines(log) == []   # still waiting for the merge
    hold.stdin.close()         # the merge ends (or its webhook dies): EOF releases it
    assert hold.wait(5) == 0
    assert helper.wait(10) == 0
    assert _lines(log) == ["helper start", "helper end"]
    assert not ts.merge_pending(slot_dir)


def test_a_run_inside_a_held_slot_does_not_wait_for_itself(slot_dir, tmp_path):
    """The gate holds the slot and runs pytest, whose conftest asks again: it must pass straight through."""
    out = subprocess.run([sys.executable, str(SCRIPT), "run", "--what", "outer", "--", sys.executable, str(SCRIPT),
                          "run", "--what", "inner", "--", "/bin/sh", "-c", f'echo "${ts.HELD_ENV}"'],
                         env=_env(slot_dir), capture_output=True, text=True, timeout=10)
    assert out.returncode == 0
    assert out.stdout.strip() == "outer"


def test_the_exit_code_is_the_commands(slot_dir):
    r = subprocess.run([sys.executable, str(SCRIPT), "run", "--what", "x", "--", "/bin/sh", "-c", "exit 7"],
                       env=_env(slot_dir), timeout=10)
    assert r.returncode == 7


def test_a_holder_that_dies_frees_the_slot(slot_dir, tmp_path):
    log = tmp_path / "order.log"
    a = _run(slot_dir, log, "a", 3)
    assert _wait_for(lambda: "a start" in _lines(log))
    a.kill()   # our own test process, nobody else's
    a.wait(5)
    b = _run(slot_dir, log, "b", 0.1)
    assert b.wait(10) == 0
    assert _lines(log)[-2:] == ["b start", "b end"]


def test_the_in_process_slot_marks_the_environment_and_restores_it(slot_dir):
    with ts.slot("pytest lib/tests"):
        assert os.environ[ts.HELD_ENV] == "pytest lib/tests"
        with ts.slot("nested"):   # no wait for itself
            pass
    assert ts.HELD_ENV not in os.environ


# ── workers sized to free memory, not cores ──────────────────────────────────────────────────────────────────────

GB = 2**30


@pytest.mark.parametrize("free,cores,want", [
    (3 * GB, 10, 4),        # (3 GB - 1 GB reserve) / 0.5 GB = 4, fewer than the 10 cores
    (0.5 * GB, 10, 1),      # under the reserve: still one worker, never zero
    (64 * GB, 10, 10),      # plenty of memory: the cores are the limit
    (None, 8, 2),           # free memory unknown: a small safe number
])
def test_workers_follow_free_memory(free, cores, want):
    assert ts.workers(free_bytes=free, cores=cores, per_worker=GB // 2, reserve=GB) == want


def test_free_memory_from_vm_stat():
    out = ("Mach Virtual Memory Statistics: (page size of 16384 bytes)\n"
           "Pages free:                                5000.\nPages active:                             100000.\n"
           "Pages inactive:                            60000.\nPages speculative:                          1000.\n"
           "Pages purgeable:                            4000.\n")
    assert ts.parse_vm_stat(out) == (5000 + 60000 + 1000 + 4000) * 16384


def test_free_memory_from_proc_meminfo():
    assert ts.parse_meminfo("MemTotal: 8000000 kB\nMemFree: 100 kB\nMemAvailable:  2000000 kB\n") == 2000000 * 1024


def test_unreadable_memory_is_none():
    assert ts.parse_vm_stat("garbage") is None
    assert ts.parse_meminfo("") is None


def test_the_workers_command_prints_one_number(slot_dir):
    out = subprocess.run([sys.executable, str(SCRIPT), "workers"], env=_env(slot_dir), capture_output=True, text=True,
                         timeout=20)
    assert out.returncode == 0 and int(out.stdout.strip()) >= 1


# ── which runs take the slot (pytest conftest) ───────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("args,parallel,heavy", [
    (["lib/tests"], False, True),                                   # the whole suite
    ([], False, True),                                              # no args: everything under the rootdir
    (["lib/tests/test_x.py"], False, False),                        # one file: small, never queued
    (["lib/tests/test_x.py::test_y"], False, False),
    (["lib/tests/test_x.py"], True, True),                          # any -n run is heavy
])
def test_heavy_runs_are_whole_suites_or_parallel(args, parallel, heavy, tmp_path):
    (tmp_path / "lib" / "tests").mkdir(parents=True)
    (tmp_path / "lib" / "tests" / "test_x.py").write_text("")
    assert ts.is_heavy(args, parallel, cwd=tmp_path) is heavy


def test_hold_keeps_the_slot_until_stdin_closes(slot_dir, tmp_path):
    """The webhook (Node has no flock) holds the slot through this for the gate's whole test stage."""
    log = tmp_path / "order.log"
    hold = subprocess.Popen([sys.executable, str(SCRIPT), "hold", "--merge", "--what", "merge gate: PR #1"],
                            env=_env(slot_dir), stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    assert hold.stdout.readline().strip() == "held"
    assert ts.holder(slot_dir)["what"] == "merge gate: PR #1"
    other = _run(slot_dir, log, "helper", 0.1)
    time.sleep(0.3)
    assert _lines(log) == []
    hold.stdin.close()
    assert hold.wait(5) == 0 and other.wait(10) == 0
    assert _lines(log) == ["helper start", "helper end"]


@pytest.mark.timeout(90)
def test_a_whole_suite_pytest_waits_for_the_slot_and_one_file_does_not(slot_dir):
    """The repo conftest takes the slot for a heavy run before collecting anything (real pytest, real conftest)."""
    root = LIB.parent
    hold = subprocess.Popen([sys.executable, str(SCRIPT), "hold", "--what", "someone else's suite"], env=_env(slot_dir),
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    assert hold.stdout.readline().strip() == "held"
    small = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "--co",
                            "lib/tests/test_test_slot.py"], cwd=root, env=_env(slot_dir), capture_output=True,
                           text=True, timeout=60)
    assert small.returncode == 0, small.stdout + small.stderr
    whole = subprocess.Popen([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "--co", "lib/tests",
                              "-k", "no_test_has_this_name"], cwd=root, env=_env(slot_dir),
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    time.sleep(2)
    assert whole.poll() is None   # waiting
    hold.stdin.close()
    hold.wait(5)
    out, err = whole.communicate(timeout=60)
    assert "waiting for someone else's suite" in err
    assert whole.returncode in (0, 5), out + err   # 5 = nothing selected


@pytest.mark.timeout(120)
def test_a_real_merge_on_the_machine_never_reaches_the_tests_inside_a_parallel_run(slot_dir):
    """2026-10-30: a merge marked on the machine while a parallel suite ran made 20 helper/pipeline tests see "a merge
    is running". Every test process, xdist workers included, reads a slot folder of its own."""
    root = LIB.parent
    hold = subprocess.Popen([sys.executable, str(SCRIPT), "hold-merge"], env=_env(slot_dir),
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    assert hold.stdout.readline().strip() == "held"
    try:
        r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-n", "2",
                            "lib/tests/test_helper_tab.py", "-k", "goes_ahead or skipped_on_purpose"],
                           # already in the slot (as the gate is, or a suite a merge arrived during): no wait
                           cwd=root, env={**_env(slot_dir), ts.HELD_ENV: "a suite already running"},
                           capture_output=True, text=True, timeout=100)
    finally:
        hold.stdin.close()
        hold.wait(5)
    assert r.returncode == 0, r.stdout[-2000:] + r.stderr[-1000:]


def test_checks_running_at_the_same_moment_never_see_each_other_as_a_merge(slot_dir):
    """Found 2026-10-30: two "is a merge running?" checks at once each saw the other's momentary lock as a merge, and
    a helper was refused with no merge anywhere. Four processes check in a tight loop: never a merge, until one is."""
    loop = ("import sys, test_slot as ts\n"
            "hits = sum(ts.merge_pending() for _ in range(3000))\n"
            "print(hits)\n")
    env = {**_env(slot_dir), "PYTHONPATH": str(LIB)}
    ps = [subprocess.Popen([sys.executable, "-c", loop], env=env, stdout=subprocess.PIPE, text=True) for _ in range(4)]
    assert [int(p.communicate(timeout=60)[0]) for p in ps] == [0, 0, 0, 0]
    hold = subprocess.Popen([sys.executable, str(SCRIPT), "hold-merge"], env=_env(slot_dir),
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    assert hold.stdout.readline().strip() == "held"
    ps = [subprocess.Popen([sys.executable, "-c", loop], env=env, stdout=subprocess.PIPE, text=True) for _ in range(4)]
    assert [int(p.communicate(timeout=60)[0]) for p in ps] == [3000] * 4
    hold.stdin.close()
    hold.wait(5)
