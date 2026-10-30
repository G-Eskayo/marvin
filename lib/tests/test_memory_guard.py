"""Tests for memory_guard.py (marvin#845: no new helper while memory pressure is high, never kill to make room). Run via:
    ~/.agents/venv/bin/python -m pytest lib/tests/test_memory_guard.py -v

The queue is real files in tmp_path and queued work is started as a real process, so "dropping pressure starts the
queue" is checked by the work actually running. Only the pressure level and the macOS notification are injected: the
level can't be raised without root (`memory_pressure -S` needs it), and the notification arrives through `events`.
"""
from __future__ import annotations
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

LIB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LIB))

import memory_guard as mg  # noqa: E402


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    """Queue, lock and log in tmp_path; the suite-wide level override (conftest) off, so each test sets its own."""
    monkeypatch.setattr(mg, "STATE_DIR", tmp_path / "mg")
    monkeypatch.setattr(mg, "QUEUE_DIR", tmp_path / "mg" / "queue")
    monkeypatch.setattr(mg, "LOCK_PATH", tmp_path / "mg" / "watch.lock")
    monkeypatch.setattr(mg, "DRAIN_LOCK_PATH", tmp_path / "mg" / "drain.lock")
    monkeypatch.setattr(mg, "LOG_PATH", tmp_path / "logs" / "memory-guard.jsonl")
    monkeypatch.setattr(mg, "STARTED_LOG", tmp_path / "logs" / "memory-guard-started.log")
    monkeypatch.delenv(mg.LEVEL_ENV, raising=False)
    monkeypatch.setenv("HELPER_TAB_QUIET", "1")
    return tmp_path


@pytest.fixture
def never_kill(monkeypatch):
    """Any attempt to stop a process fails the test: the owner's rule is that nothing is ever killed to make room."""
    def boom(*a, **k):
        pytest.fail(f"memory_guard tried to stop a process: {a}")
    for name in ("kill", "killpg"):
        monkeypatch.setattr(os, name, boom)
    for name in ("kill", "terminate", "send_signal"):
        monkeypatch.setattr(subprocess.Popen, name, boom)
    real_run = subprocess.run

    def run(cmd, *a, **k):
        words = cmd if isinstance(cmd, (list, tuple)) else [cmd]
        if any(Path(str(w)).name in ("kill", "pkill", "killall") for w in words[:1]):
            boom(cmd)
        return real_run(cmd, *a, **k)
    monkeypatch.setattr(subprocess, "run", run)


def _level(name):
    return lambda: name


def _no_watcher():
    return None


# ── reading pressure and swap ───────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("raw,level", [("1\n", "normal"), ("2\n", "warn"), ("4\n", "critical")])
def test_reads_the_kernel_pressure_level(raw, level):
    run = lambda cmd, **k: subprocess.CompletedProcess(cmd, 0, stdout=raw)  # noqa: E731
    assert mg.read_level(run=run) == level


def test_an_unreadable_level_is_none_so_it_never_blocks():
    run = lambda cmd, **k: subprocess.CompletedProcess(cmd, 1, stdout="")  # noqa: E731
    assert mg.read_level(run=run) is None
    assert mg.check("#1", level=None)["ok"] is True


def test_the_level_override_wins_over_the_kernel(monkeypatch):
    monkeypatch.setenv(mg.LEVEL_ENV, "warn")
    assert mg.read_level(run=lambda *a, **k: pytest.fail("override set: no sysctl")) == "warn"


def test_reads_swap_in_use():
    out = "vm.swapusage: total = 4096.00M  used = 2552.44M  free = 1543.56M  (encrypted)\n"
    run = lambda cmd, **k: subprocess.CompletedProcess(cmd, 0, stdout=out)  # noqa: E731
    assert mg.read_swap_used(run=run) == int(2552.44 * 2**20)


def test_the_real_readers_answer_on_this_mac():
    """Real sysctl, no injection: whatever the level is right now, it is one of the three (or None off macOS)."""
    os.environ.pop(mg.LEVEL_ENV, None)
    assert mg.read_level() in ("normal", "warn", "critical", None)


# ── normal pressure starts ──────────────────────────────────────────────────────────────────────────────────────

def test_normal_pressure_starts_and_queues_nothing(never_kill):
    r = mg.guard("#60", ["true"], "/tmp", level_reader=_level("normal"), start_watcher=lambda: pytest.fail("no wait"))
    assert r["ok"] is True and r.get("queued") is not True
    assert mg.queued() == []


# ── warn or critical refuses and queues ─────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("level", ["warn", "critical"])
def test_warn_or_critical_refuses_with_a_plain_message_and_queues(level, never_kill, capsys):
    watchers = []
    r = mg.guard("#845", ["echo", "hi"], "/tmp", level_reader=_level(level), swap_reader=lambda: 3 * 2**30,
                 start_watcher=lambda: watchers.append(1))
    assert r["ok"] is False and r["queued"] is True
    assert "memory is under pressure, so #845 waits" in r["message"]
    assert "Nothing was stopped" in r["message"]
    q = mg.queued()
    assert [(e["what"], e["argv"], e["cwd"]) for e in q] == [("#845", ["echo", "hi"], "/tmp")]
    assert watchers == [1], "the notification wait is armed once, not polled"
    events = [json.loads(l) for l in mg.LOG_PATH.read_text().splitlines()]
    assert events[-1]["event"] == "refused" and events[-1]["level"] == level and events[-1]["what"] == "#845"


def test_the_message_names_this_mac(monkeypatch):
    monkeypatch.setattr(mg, "machine_name", lambda: "Mac mini")
    r = mg.check("#7", level="warn", swap=None)
    assert r["message"].startswith("The Mac mini's memory is under pressure, so #7 waits.")


def test_refusing_without_a_command_queues_nothing():
    r = mg.guard("merge check", None, None, level_reader=_level("warn"), start_watcher=_no_watcher)
    assert r["ok"] is False and r["queued"] is False and mg.queued() == []


def test_the_same_key_is_queued_once_and_the_owner_told_once():
    told = []
    for _ in range(3):
        mg.guard("ticket scan", ["true"], "/tmp", key="ticket-pipeline", level_reader=_level("warn"),
                 start_watcher=_no_watcher, tell=lambda t, m: told.append(m))
    assert len(mg.queued()) == 1 and len(told) == 1


def test_queue_order_is_first_in_first_out():
    for n in (1, 2, 3):
        mg.guard(f"#{n}", ["true"], "/tmp", level_reader=_level("warn"), start_watcher=_no_watcher)
    assert [e["what"] for e in mg.queued()] == ["#1", "#2", "#3"]


def test_with_work_waiting_a_passing_check_rearms_the_wait():
    """After a restart nothing is waiting on the notification; the next start re-arms it so the queue isn't stranded."""
    mg.guard("#1", ["true"], "/tmp", level_reader=_level("warn"), start_watcher=_no_watcher)
    armed = []
    r = mg.guard("#2", ["true"], "/tmp", level_reader=_level("normal"), start_watcher=lambda: armed.append(1))
    assert r["ok"] is True and armed == [1]


# ── dropping pressure starts the queue ──────────────────────────────────────────────────────────────────────────

def test_drain_starts_the_oldest_queued_work_when_pressure_is_normal(tmp_path, never_kill):
    out = tmp_path / "ran"
    mg.guard("#1", ["sh", "-c", f"echo one >> {out}"], str(tmp_path), level_reader=_level("warn"), start_watcher=_no_watcher)
    mg.guard("#2", ["sh", "-c", f"echo two >> {out}"], str(tmp_path), level_reader=_level("warn"), start_watcher=_no_watcher)
    started = mg.drain(level_reader=_level("normal"))
    assert started["what"] == "#1"
    _wait_for(lambda: out.exists())
    assert out.read_text() == "one\n"
    assert [e["what"] for e in mg.queued()] == ["#2"], "one start per trigger, so the next one sees the new pressure"


def test_drain_starts_nothing_while_pressure_is_still_high():
    mg.guard("#1", ["true"], "/tmp", level_reader=_level("warn"), start_watcher=_no_watcher)
    assert mg.drain(level_reader=_level("warn"), start=lambda e: pytest.fail("still under pressure")) is None
    assert len(mg.queued()) == 1


def test_drain_with_an_empty_queue_is_a_no_op():
    assert mg.drain(level_reader=_level("normal"), start=lambda e: pytest.fail("nothing queued")) is None


def test_the_watch_drains_on_the_normal_notification_and_ends_with_the_queue(tmp_path, never_kill):
    out = tmp_path / "ran"
    mg.guard("#1", ["sh", "-c", f"echo a >> {out}"], str(tmp_path), level_reader=_level("warn"), start_watcher=_no_watcher)
    mg.guard("#2", ["sh", "-c", f"echo b >> {out}"], str(tmp_path), level_reader=_level("warn"), start_watcher=_no_watcher)
    levels = {"now": "warn"}
    notifications = iter(["critical", "warn", "normal", "warn", "normal"])

    def events():
        for lvl in notifications:
            levels["now"] = lvl
            yield lvl
    r = mg.watch(events=events(), level_reader=lambda: levels["now"])
    assert r["started"] == ["#1", "#2"] and mg.queued() == []
    assert next(notifications, None) is None, "it read the notifications it needed and no more"
    _wait_for(lambda: out.exists() and len(out.read_text().split()) == 2)


def test_the_watch_drains_at_once_when_pressure_already_dropped_before_it_armed():
    mg.guard("#1", ["true"], "/tmp", level_reader=_level("warn"), start_watcher=_no_watcher)
    r = mg.watch(events=iter(()), level_reader=_level("normal"))
    assert r["started"] == ["#1"]


def test_the_watch_never_polls_it_only_reads_notifications(monkeypatch):
    mg.guard("#1", ["true"], "/tmp", level_reader=_level("warn"), start_watcher=_no_watcher)
    monkeypatch.setattr(time, "sleep", lambda s: pytest.fail("the watch must not sleep-poll"))
    r = mg.watch(events=iter(["warn"]), level_reader=_level("warn"))
    assert r["started"] == [] and len(mg.queued()) == 1


def test_only_one_watch_runs_at_a_time():
    mg.guard("#1", ["true"], "/tmp", level_reader=_level("warn"), start_watcher=_no_watcher)
    mg.STATE_DIR.mkdir(parents=True, exist_ok=True)
    import fcntl
    with open(mg.LOCK_PATH, "w") as held:
        fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
        r = mg.watch(events=iter(["normal"]), level_reader=_level("normal"))
    assert r["already"] is True and len(mg.queued()) == 1


def test_a_finished_job_kicks_a_drain_only_when_work_is_waiting(monkeypatch):
    spawned = []
    monkeypatch.setattr(mg, "_spawn_detached", lambda argv: spawned.append(argv))
    mg.kick()
    assert spawned == [], "nothing queued: no process started"
    mg.guard("#1", ["true"], "/tmp", level_reader=_level("warn"), start_watcher=_no_watcher)
    mg.kick()
    assert len(spawned) == 1 and spawned[0][-1] == "drain"


# ── nothing is ever killed ──────────────────────────────────────────────────────────────────────────────────────

def test_the_module_has_no_way_to_stop_a_process():
    src = (LIB / "memory_guard.py").read_text()
    for word in ("os.kill", "killpg", ".terminate(", ".send_signal(", "pkill", "killall", "SIGTERM", "SIGKILL",
                 "memorystatus_kill", "purge"):
        assert word not in src, f"memory_guard.py must never stop anything ({word})"


def test_full_cycle_under_pressure_kills_nothing(tmp_path, never_kill):
    sleeper = subprocess.Popen(["sleep", "3"])   # stands in for a helper already running when pressure rises
    out = tmp_path / "ran"
    mg.guard("#9", ["sh", "-c", f"echo ok > {out}"], str(tmp_path), level_reader=_level("critical"),
             start_watcher=_no_watcher)
    mg.watch(events=iter(["critical", "normal"]), level_reader=_level("normal"))
    _wait_for(lambda: out.exists())
    assert sleeper.poll() is None, "the running helper is untouched"
    assert sleeper.wait(timeout=10) == 0, "it ended on its own, with no signal"


# ── the macOS notification itself ───────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("mask,level", [(1, "normal"), (2, "warn"), (4, "critical"), (6, "critical"), (0, None)])
def test_the_dispatch_event_mask_maps_to_a_level(mask, level):
    assert mg.level_from_mask(mask) == level


@pytest.mark.skipif(sys.platform != "darwin", reason="libdispatch memory-pressure source is macOS only")
def test_the_real_dispatch_source_arms_and_cancels():
    src = mg.PressureSource()
    try:
        assert src.armed
    finally:
        src.close()


# ── Health (Vitals) and the phone read this ─────────────────────────────────────────────────────────────────────

def test_status_reports_level_swap_and_what_waits():
    mg.guard("#3", ["true"], "/tmp", level_reader=_level("warn"), start_watcher=_no_watcher)
    s = mg.status(level_reader=_level("warn"), swap_reader=lambda: 2**30)
    assert s["level"] == "warn" and s["swap_used"] == 2**30 and s["waiting"] == ["#3"]


def _wait_for(cond, timeout=10.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:     # test-side wait for a real child process, not part of the guard
        if cond():
            return
        time.sleep(0.05)
    raise AssertionError("condition not met in time")
