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
    monkeypatch.setenv("MARVIN_TEST_SLOT_DIR", str(tmp_path / "slot"))   # merges marked here, never the machine's
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


def test_the_watch_ends_when_another_trigger_empties_the_queue(tmp_path):
    """Live on the Mini (2026-10-30) macOS sent the small watcher no pressure note at all, so a finished job's kick
    is what starts the queue. The watcher then must not wait forever: a change to the queue directory wakes it."""
    mg.guard("#1", ["true"], "/tmp", level_reader=_level("warn"), start_watcher=_no_watcher)

    def events():
        assert mg.drain(level_reader=_level("normal"), start=lambda e: None)["what"] == "#1"   # a helper's exit, say
        yield mg.QUEUE_CHANGED
        pytest.fail("read past the queue emptying")
    r = mg.watch(events=events(), level_reader=_level("warn"))
    assert r == {"already": False, "started": []}
    assert not any(json.loads(l).get("event") == "pressure" for l in mg.LOG_PATH.read_text().splitlines())


def test_a_queue_change_alone_starts_nothing_while_pressure_is_high(tmp_path):
    mg.guard("#1", ["true"], "/tmp", level_reader=_level("warn"), start_watcher=_no_watcher)
    mg.guard("#2", ["true"], "/tmp", level_reader=_level("warn"), start_watcher=_no_watcher)
    r = mg.watch(events=iter([mg.QUEUE_CHANGED]), level_reader=_level("warn"))
    assert r["started"] == [] and len(mg.queued()) == 2


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


@pytest.mark.skipif(sys.platform != "darwin", reason="libdispatch sources are macOS only")
def test_the_real_source_reports_a_change_to_the_queue_directory():
    mg.guard("#1", ["true"], "/tmp", level_reader=_level("warn"), start_watcher=_no_watcher)
    src = mg.PressureSource(watch_dir=mg.QUEUE_DIR)
    try:
        assert src.armed
        next(mg.QUEUE_DIR.glob("*.json")).unlink()
        assert src._q.get(timeout=5) == mg.QUEUE_CHANGED
    finally:
        src.close()


# ── marvin#940: merges first. While a merge waits or runs, new helpers wait; nothing running is stopped ─────────────

SLOT = LIB / "test_slot.py"


@pytest.fixture
def merge_running(tmp_path):
    """A real merge marker (what the webhook holds for a merge's whole run), released on exit."""
    p = subprocess.Popen([sys.executable, str(SLOT), "hold-merge"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                         text=True, env={**os.environ, "MARVIN_TEST_SLOT_DIR": str(tmp_path / "slot")})
    assert p.stdout.readline().strip() == "held"
    yield p
    if p.poll() is None:
        p.stdin.close()
        p.wait(5)


def _end(p):
    p.stdin.close()
    assert p.wait(5) == 0


def test_a_helper_waits_while_a_merge_runs_even_at_normal_pressure(merge_running, never_kill, monkeypatch):
    monkeypatch.setattr(mg, "machine_name", lambda: "Mac mini")
    armed = []
    r = mg.guard("Seal Speak: #60", ["true"], "/tmp", level_reader=_level("normal"), start_watcher=lambda: armed.append(1))
    assert r["ok"] is False and r["queued"] is True and r["reason"] == "merge"
    assert r["message"] == ("A merge is running on the Mac mini, so Seal Speak: #60 waits. Nothing was stopped. "
                            "It starts by itself when the merge is done.")
    assert [e["what"] for e in mg.queued()] == ["Seal Speak: #60"] and armed == [1]


def test_a_helper_waits_while_a_merge_waits_for_memory(never_kill):
    mg.guard("PR #238", ["true"], "/tmp", key="merge:https://github.com/o/r/pull/238", level_reader=_level("warn"),
             start_watcher=_no_watcher)
    r = mg.guard("helper", ["true"], "/tmp", level_reader=_level("normal"), start_watcher=_no_watcher)
    assert r["ok"] is False and r["reason"] == "merge"


def test_a_merge_is_never_held_back_for_another_merge(merge_running):
    r = mg.guard("PR #2", ["true"], "/tmp", key="merge:https://github.com/o/r/pull/2", level_reader=_level("normal"),
                 start_watcher=_no_watcher)
    assert r["ok"] is True


def test_a_merge_still_waits_for_memory():
    r = mg.guard("PR #2", ["true"], "/tmp", key="merge:https://github.com/o/r/pull/2", level_reader=_level("warn"),
                 start_watcher=_no_watcher)
    assert r["ok"] is False and r["reason"] == "memory"


def test_drain_starts_a_queued_merge_before_older_helpers():
    mg.guard("helper", ["true"], "/tmp", level_reader=_level("warn"), start_watcher=_no_watcher)
    mg.guard("PR #9", ["true"], "/tmp", key="merge:u9", level_reader=_level("warn"), start_watcher=_no_watcher)
    started = mg.drain(level_reader=_level("normal"), start=lambda e: None)
    assert started["what"] == "PR #9"
    assert [e["what"] for e in mg.queued()] == ["helper"]


def test_drain_starts_no_helper_while_a_merge_runs_and_the_merge_ending_lets_it(merge_running, never_kill):
    mg.guard("helper", ["true"], "/tmp", level_reader=_level("warn"), start_watcher=_no_watcher)
    assert mg.drain(level_reader=_level("normal"), start=lambda e: pytest.fail("a merge is running")) is None
    _end(merge_running)
    assert mg.drain(level_reader=_level("normal"), start=lambda e: None)["what"] == "helper"


# ── marvin#940: the threshold, and forgetting a queued merge that started some other way ─────────────────────────

def test_left_over_swap_alone_never_refuses(never_kill):
    """16:46 on 2026-10-30 read warn with 2.6-3.0 GB of swap. Only the kernel's level counts; swap is for the words."""
    r = mg.guard("PR #238", ["true"], "/tmp", key="merge:u", level_reader=_level("normal"),
                 swap_reader=lambda: pytest.fail("swap is not read at normal"), start_watcher=_no_watcher)
    assert r["ok"] is True


def test_forget_removes_a_queued_merge_once():
    mg.guard("PR #238", ["true"], "/tmp", key="merge:u238", level_reader=_level("warn"), start_watcher=_no_watcher)
    mg.guard("helper", ["true"], "/tmp", level_reader=_level("warn"), start_watcher=_no_watcher)
    assert mg.forget("merge:u238") is True
    assert [e["what"] for e in mg.queued()] == ["helper"]
    assert mg.forget("merge:u238") is False   # already gone (or started): nothing to forget


def test_forget_on_the_command_line_prints_whether_it_was_there(tmp_path):
    mg.guard("PR #1", ["true"], "/tmp", key="merge:u1", level_reader=_level("warn"), start_watcher=_no_watcher)
    assert mg.main(["forget", "--key", "merge:u1"]) == 0
    assert mg.queued() == []
