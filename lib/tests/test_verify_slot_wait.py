"""marvin#1113: a verify timeout counts only the tests running, never the wait for this machine's test slot. Run via:
    ~/.agents/venv/bin/python -m pytest lib/tests/test_verify_slot_wait.py -v

On 2026-11-04 the Mini's merges held the slot (merges first, #940) and pipeline builds spent their whole 1200 s
verify timeout in line ("timed out after 1200s running test-slot: waiting for pytest ... to finish"), so good tickets
were parked without a test running. These run real child processes that speak the slot's own lines, with timings
in seconds kept small: the run waits longer than its timeout, then runs inside it.
"""
from __future__ import annotations
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

LIB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LIB))

import evidence_capture as ec  # noqa: E402
import failure_breaker as fb  # noqa: E402
import project_profile as pp  # noqa: E402
import purpose_metrics as pm  # noqa: E402
import test_slot as ts  # noqa: E402

WAIT = "test-slot: pytest lib: waiting for a merge to finish (one test run at a time on this machine)"
TOOK = "test-slot: pytest lib: took the slot after 2 s"


def _child(*steps: str) -> list[str]:
    """A child process from steps: 'err:<line>', 'out:<line>', 'raw:<text no newline>', 'sleep:<s>', 'exit:<rc>'."""
    code = ["import sys, time"]
    for s in steps:
        kind, _, arg = s.partition(":")
        if kind in ("err", "out"):
            stream = "sys.stderr" if kind == "err" else "sys.stdout"
            code.append(f"{stream}.write({arg!r} + '\\n'); {stream}.flush()")
        elif kind == "raw":
            code.append(f"sys.stderr.write({arg!r}); sys.stderr.flush()")
        elif kind == "sleep":
            code.append(f"time.sleep({float(arg)})")
        elif kind == "exit":
            code.append(f"sys.exit({int(arg)})")
    return [sys.executable, "-c", "\n".join(code)]


def run(cmd, timeout=1.0, cap=30.0, cwd=None):
    return ec.run_timed(cmd, cwd=cwd, env=None, timeout_s=timeout, slot_wait_cap_s=cap)


# ── the slot's own lines are what the runner reads ──────────────────────────────────────────────────────────────

def test_the_slots_waiting_and_took_lines_match_what_the_runner_looks_for():
    assert ts.WAITING_RE.search(WAIT) and not ts.TOOK_RE.search(WAIT)
    assert ts.TOOK_RE.search(TOOK) and not ts.WAITING_RE.search(TOOK)


def test_a_waiting_slot_says_when_it_took_the_slot(tmp_path, monkeypatch):
    d = tmp_path / "slot"
    monkeypatch.setenv(ts.DIR_ENV, str(d))
    monkeypatch.delenv(ts.HELD_ENV, raising=False)
    env = {k: v for k, v in os.environ.items() if k != ts.HELD_ENV}
    holder = subprocess.Popen([sys.executable, str(LIB / "test_slot.py"), "hold", "--what", "other run"],
                              stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, env={**env, ts.DIR_ENV: str(d)})
    assert holder.stdout.readline().strip() == "held"
    said: list[str] = []
    try:
        import threading
        threading.Timer(0.3, lambda: holder.stdin.close()).start()
        with ts.slot("pytest lib", say=said.append):
            pass
    finally:
        holder.wait(10)
    assert len(said) == 2, said
    assert ts.WAITING_RE.search("test-slot: " + said[0]) and ts.TOOK_RE.search("test-slot: " + said[1])


def test_a_slot_taken_straight_away_says_nothing(tmp_path, monkeypatch):
    monkeypatch.setenv(ts.DIR_ENV, str(tmp_path / "slot"))
    monkeypatch.delenv(ts.HELD_ENV, raising=False)
    said: list[str] = []
    with ts.slot("pytest lib", say=said.append):
        pass
    assert said == []


# ── no wait: exactly as before ───────────────────────────────────────────────────────────────────────────────────

def test_a_quick_run_with_no_wait_returns_its_code_and_output_stdout_first(tmp_path):
    rc, out = run(_child("err:e1", "out:o1", "out:o2", "exit:3"), cwd=tmp_path)
    assert rc == 3
    assert out == "o1\no2\ne1\n"


def test_a_slow_run_with_no_wait_still_times_out_with_its_output(tmp_path):
    t0 = time.monotonic()
    with pytest.raises(ec.TestTimedOut) as e:
        run(_child("out:started", "sleep:30"), timeout=1)
    assert time.monotonic() - t0 < 10
    assert not isinstance(e.value, ec.SlotWaitTimedOut)
    assert "started" in e.value.partial_output
    assert fb.signature(str(e.value)) == "verify-timeout"


def test_a_timeout_kills_the_whole_process_group(tmp_path):
    pidfile = tmp_path / "grandchild.pid"
    cmd = ["/bin/sh", "-c", f"sleep 30 & echo $! > {pidfile}; wait"]
    with pytest.raises(ec.TestTimedOut):
        run(cmd, timeout=0.5)
    pid = int(pidfile.read_text())
    for _ in range(100):
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            break
        time.sleep(0.02)
    else:
        pytest.fail("the grandchild outlived the timeout")


# ── a wait doesn't count ─────────────────────────────────────────────────────────────────────────────────────────

def test_a_wait_longer_than_the_timeout_then_a_quick_run_passes(tmp_path):
    rc, out = run(_child(f"err:{WAIT}", "sleep:1.6", f"err:{TOOK}", "sleep:0.2", "out:3 passed in 0.2s"),
                  timeout=1.0)
    assert rc == 0 and "3 passed" in out


def test_after_a_wait_the_tests_themselves_still_get_only_the_timeout(tmp_path):
    with pytest.raises(ec.TestTimedOut) as e:
        run(_child(f"err:{WAIT}", "sleep:0.6", f"err:{TOOK}", "out:running", "sleep:30"), timeout=0.8)
    assert not isinstance(e.value, ec.SlotWaitTimedOut)
    assert "running" in e.value.partial_output


def test_two_waits_in_one_run_are_both_left_out(tmp_path):
    rc, _ = run(_child(f"err:{WAIT}", "sleep:0.9", f"err:{TOOK}", "sleep:0.2",
                       f"err:{WAIT}", "sleep:0.9", f"err:{TOOK}", "sleep:0.2", "out:done"), timeout=0.8)
    assert rc == 0


def test_lots_of_output_during_the_wait_doesnt_confuse_it(tmp_path):
    spam = [f"out:line {i}" for i in range(300)]
    rc, out = run(_child(f"err:{WAIT}", *spam, "sleep:1.2", *spam, f"err:{TOOK}", "out:done"), timeout=0.8)
    assert rc == 0 and out.count("line 299") == 2


def test_a_wait_line_with_no_newline_still_stops_the_clock(tmp_path):
    rc, _ = run(_child(f"raw:{WAIT}", "sleep:1.3", f"err:", f"err:{TOOK}", "out:done"), timeout=0.8)
    assert rc == 0


# ── what must not stop the clock ─────────────────────────────────────────────────────────────────────────────────

def test_a_tests_own_waiting_for_text_is_not_a_slot_wait(tmp_path):
    with pytest.raises(ec.TestTimedOut):
        run(_child("out:waiting for the server to finish", "err:waiting for a merge to finish", "sleep:30"),
            timeout=0.6)


def test_a_took_line_with_no_wait_before_it_gives_no_extra_time(tmp_path):
    with pytest.raises(ec.TestTimedOut):
        run(_child(f"err:{TOOK}", "sleep:30"), timeout=0.6)


# ── a wait that never ends ───────────────────────────────────────────────────────────────────────────────────────

def test_a_wait_past_the_cap_stops_with_a_slot_error_not_a_test_timeout(tmp_path):
    t0 = time.monotonic()
    with pytest.raises(ec.SlotWaitTimedOut) as e:
        run(_child(f"err:{WAIT}", "sleep:30"), timeout=0.3, cap=1.0)
    assert time.monotonic() - t0 < 10
    assert isinstance(e.value, ec.TestTimedOut)   # still the machine's time, never the ticket's (run_ticket.py)
    msg = str(e.value)
    assert "test slot" in msg
    assert fb.signature(msg) == "slot-busy"


def test_a_run_that_exits_while_waiting_returns_its_code(tmp_path):
    rc, out = run(_child(f"err:{WAIT}", "sleep:0.2", "exit:137"), timeout=0.1)
    assert rc == 137 and WAIT in out


# ── every pipeline path uses it ──────────────────────────────────────────────────────────────────────────────────

def test_capture_test_results_leaves_the_wait_out(tmp_path, monkeypatch):
    monkeypatch.setattr(ec, "SLOT_WAIT_CAP_S", 30)
    result = ec.capture_test_results(
        tmp_path, _child(f"err:{WAIT}", "sleep:1.3", f"err:{TOOK}", "out:4 passed in 0.1s"), timeout_s=0.8)
    assert result["passed"] == 4


def test_the_profile_runner_leaves_the_wait_out(tmp_path):
    rc, out = pp._default_runner(_child(f"err:{WAIT}", "sleep:1.3", f"err:{TOOK}", "out:ok"), tmp_path,
                                 dict(os.environ), 0.8)
    assert rc == 0 and "ok" in out


def test_the_measurer_keeps_a_slot_error_a_slot_error(tmp_path):
    profile = {"repo": "G-Eskayo/x", "verify": [{"id": "t", "label": "Tests", "command": ["true"], "parser": "exit-code",
                                                   "required": True, "requires": []}]}

    def runner(cmd, cwd, env, timeout):
        raise ec.SlotWaitTimedOut(cmd, 7200, "partial")

    m = pp.Measurer(pp._validate(profile, "test"), runner=runner, have=lambda c, e: True)
    import unittest.mock as um
    with um.patch.object(pp, "with_required_checks", lambda p, w: p):
        with pytest.raises(ec.SlotWaitTimedOut):
            m(tmp_path)


# ── the probe ────────────────────────────────────────────────────────────────────────────────────────────────────

def test_the_probe_counts_verify_timeouts_spent_waiting_for_the_slot(tmp_path):
    now = datetime(2026, 11, 4, 18, tzinfo=timezone.utc)
    log = tmp_path / "pipeline-failures.jsonl"
    rows = [
        {"t": (now - timedelta(hours=2)).isoformat(), "kind": "failure", "ticket": 982, "sig": "verify-timeout",
         "reason": "timed out after 1200s running test-slot: waiting for pytest /x to finish (one test run at a time on th"},
        {"t": (now - timedelta(hours=3)).isoformat(), "kind": "failure", "ticket": 983, "sig": "verify-timeout",
         "reason": "timed out after 1200s running ........................"},
        {"t": (now - timedelta(days=9)).isoformat(), "kind": "failure", "ticket": 988, "sig": "verify-timeout",
         "reason": "timed out after 1200s running test-slot: pytest: waiting for a merge to finish"},
        {"t": (now - timedelta(hours=1)).isoformat(), "kind": "failure", "ticket": 989, "sig": "slot-busy",
         "reason": "waited 7200s for the test slot"},
    ]
    log.write_text("\n".join(json.dumps(r) for r in rows) + "\nnot json\n")
    assert pm._slot_wait_timeouts(days=7, path=log, now=now) == 1.0
    assert pm._slot_wait_timeouts(days=7, path=tmp_path / "missing.jsonl", now=now) == 0.0
    assert "verify-timeout-in-slot-wait" in pm.PROBES
