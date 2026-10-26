"""Tests for disk_ledger.py. Run via:
    ~/.agents/venv/bin/python -m pytest lib/tests/test_disk_ledger.py -v
"""
from __future__ import annotations
import json
import os
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

LIB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LIB))

import disk_ledger as dl  # noqa: E402


DU_SAMPLE = """\
100	/path/to/npm_cacache
200	/path/to/pnpm
150	/path/to/pip_cache
80	/path/to/brew_cache
"""


@pytest.fixture
def ledger_path(tmp_path):
    return tmp_path / "disk-ledger.jsonl"


@pytest.fixture
def mock_du():
    """Fake du callable that returns KB for known paths."""
    def _mock_du(path):
        known = {
            "/path/to/npm_cacache": 100,
            "/path/to/pnpm": 200,
            "/path/to/pip_cache": 150,
            "/path/to/brew_cache": 80,
        }
        return known.get(str(path), 0)
    return _mock_du


def test_measure_categories_basic(mock_du, monkeypatch):
    """Categorize disk usage from provided paths."""
    monkeypatch.setattr(dl, "_default_du_kb", mock_du)

    result = dl.measure_categories(du=mock_du)

    assert isinstance(result, dict)
    assert all(cat in result for cat in [
        "rebuildable_caches", "build_output", "worktrees", "models",
        "icloud_cache", "docker", "user_files", "other"
    ])
    assert all(isinstance(v, int) and v >= 0 for v in result.values())


def test_append_entry_creates_ledger(ledger_path, tmp_path, monkeypatch):
    """append_entry writes a JSON line with categories and free space."""
    monkeypatch.setattr(dl, "LEDGER_PATH", ledger_path)
    monkeypatch.setattr("machine_profile.registry_id", lambda: "mac-mini")

    categories = {
        "rebuildable_caches": 1000,
        "build_output": 2000,
        "worktrees": 5000,
        "models": 3000,
        "icloud_cache": 500,
        "docker": 1500,
        "user_files": 10000,
        "other": 2000,
    }

    dl.append_entry(categories, free_kb=20000, total_kb=100000, device=None, now=None, path=ledger_path)

    assert ledger_path.exists()
    lines = ledger_path.read_text().strip().split("\n")
    assert len(lines) == 1

    entry = json.loads(lines[0])
    assert entry["free_kb"] == 20000
    assert entry["total_kb"] == 100000
    assert entry["categories"]["worktrees"] == 5000


def test_append_entry_idempotent_same_day(ledger_path, monkeypatch):
    """Same-day runs overwrite, never duplicate."""
    monkeypatch.setattr(dl, "LEDGER_PATH", ledger_path)
    monkeypatch.setattr("machine_profile.registry_id", lambda: "mac-mini")

    now = datetime(2026, 10, 8, 10, 0, 0, tzinfo=timezone.utc)
    categories = {"rebuildable_caches": 1000, "build_output": 2000, "worktrees": 5000,
                  "models": 3000, "icloud_cache": 500, "docker": 1500, "user_files": 10000, "other": 2000}

    dl.append_entry(categories, free_kb=20000, total_kb=100000, device=None, now=now, path=ledger_path)
    dl.append_entry(categories, free_kb=21000, total_kb=100000, device=None, now=now, path=ledger_path)

    lines = ledger_path.read_text().strip().split("\n")
    assert len(lines) == 1, "Same-day entries should overwrite"
    assert json.loads(lines[0])["free_kb"] == 21000


def test_append_entry_different_days_appends(ledger_path, monkeypatch):
    """Different days append, creating multiple lines."""
    monkeypatch.setattr(dl, "LEDGER_PATH", ledger_path)
    monkeypatch.setattr("machine_profile.registry_id", lambda: "mac-mini")

    now1 = datetime(2026, 10, 8, 10, 0, 0, tzinfo=timezone.utc)
    now2 = datetime(2026, 10, 9, 10, 0, 0, tzinfo=timezone.utc)
    categories = {"rebuildable_caches": 1000, "build_output": 2000, "worktrees": 5000,
                  "models": 3000, "icloud_cache": 500, "docker": 1500, "user_files": 10000, "other": 2000}

    dl.append_entry(categories, free_kb=20000, total_kb=100000, device=None, now=now1, path=ledger_path)
    dl.append_entry(categories, free_kb=19000, total_kb=100000, device=None, now=now2, path=ledger_path)

    lines = ledger_path.read_text().strip().split("\n")
    assert len(lines) == 2


def test_run_daily_ledger_returns_summary(tmp_path, monkeypatch):
    """run_daily_ledger returns a summary dict with expected keys."""
    ledger_path = tmp_path / "disk-ledger.jsonl"
    monkeypatch.setattr(dl, "LEDGER_PATH", ledger_path)
    monkeypatch.setattr("machine_profile.registry_id", lambda: "mac-mini")
    # Never the real du: on the Mini, du on ~/Documents blocks forever under launchd (iCloud/TCC). This test ran it on
    # every category of the real home and was the hang behind the merge gate's 20-minute cuts (2026-10-21).
    measured = []
    monkeypatch.setattr(dl, "_default_du_kb", lambda p: measured.append(p) or 1)

    result = dl.run_daily_ledger()

    assert isinstance(result, dict)
    assert "timestamp" in result
    assert "categories" in result or "free_kb" in result
    assert ledger_path.exists()
    assert measured, "the ledger measured nothing: the stub was bypassed"


def test_xcode_and_app_data_are_measured(monkeypatch, tmp_path):
    """18 GB of simulators, wallpapers and app data grew on the Mini without showing anywhere (2026-10-14)."""
    monkeypatch.setattr(dl, "HOME", tmp_path)
    lib = tmp_path / "Library"
    sizes = {lib / "Developer": 33_000_000, lib / "Application Support": 15_000_000,
             lib / "Containers": 30_000_000, lib / "Group Containers": 3_000_000}
    result = dl.measure_categories(du=lambda p: sizes.get(Path(p), 0))
    assert result["xcode"] == 33_000_000
    assert result["app_support"] == 48_000_000


def test_messages_and_photos_are_found_where_macos_keeps_them(monkeypatch, tmp_path):
    """The ledger looked for ~/Messages, which doesn't exist: 53 GB of ~/Library/Messages went uncounted."""
    monkeypatch.setattr(dl, "HOME", tmp_path)
    lib = tmp_path / "Library"
    sizes = {lib / "Messages": 53_000_000, lib / "Photos": 28_000_000, tmp_path / "Messages": 999}
    assert dl.measure_categories(du=lambda p: sizes.get(Path(p), 0))["user_files"] == 81_000_000


def test_all_of_library_caches_counts_as_rebuildable_once(monkeypatch, tmp_path):
    """Caches are rebuildable by definition. Counting the folder and its Homebrew/Electron/SwiftPM parts would double."""
    monkeypatch.setattr(dl, "HOME", tmp_path)
    caches = tmp_path / "Library" / "Caches"
    sizes = {caches: 10_000_000, caches / "Homebrew": 1_000, caches / "Electron": 1_000, caches / "SwiftPM": 1_000}
    assert dl.measure_categories(du=lambda p: sizes.get(Path(p), 0))["rebuildable_caches"] == 10_000_000


def test_other_is_whatever_the_named_categories_do_not_explain():
    """"other" was always 0, so space outside the named folders was invisible."""
    cats = {"models": 100, "worktrees": 50, "other": 0}
    assert dl.with_other(cats, used_kb=400)["other"] == 250


def test_other_never_goes_negative_when_categories_overlap_or_round():
    assert dl.with_other({"models": 500, "other": 0}, used_kb=400)["other"] == 0


def test_every_measured_category_is_known_to_the_dashboard():
    """category_details drops any category missing from CATEGORY_INFO, which would hide it again."""
    import disk_categories as dc
    assert set(dl.measure_categories(du=lambda p: 0)) <= set(dc.CATEGORY_INFO)


def _script(tmp_path, name, body):
    """A stand-in for du or the readability probe: a real executable, so the real spawn, alarm and kill paths run."""
    f = tmp_path / name
    f.write_text("#!/bin/sh\n" + body + "\n")
    f.chmod(0o755)
    return str(f)


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def _wait_dead(pid: int, within: float) -> bool:
    end = time.monotonic() + within
    while time.monotonic() < end:
        if not _alive(pid):
            return True
        time.sleep(0.05)
    return not _alive(pid)


def test_du_keeps_the_total_when_some_folders_are_unreadable(monkeypatch, tmp_path):
    """du exits 1 when one subfolder is off-limits but still prints the total: ~/Library/Developer read as 0, not 33 GB."""
    du = _script(tmp_path, "du", 'echo "du: $2/x: Operation not permitted" >&2; printf "34603008\\t%s\\n" "$2"; exit 1')
    monkeypatch.setattr(dl, "DU_CMD", [du, "-sk"])
    assert dl._default_du_kb(tmp_path) == 34603008


def test_du_gets_long_enough_for_a_big_folder():
    """5 seconds wasn't enough for a 50 GB folder, and a timeout read as 0. The sweep runs at night: give it minutes."""
    assert dl.DU_TIMEOUT_S >= 300


def test_missing_folder_is_zero_without_spawning_anything(monkeypatch, tmp_path):
    marker = tmp_path / "ran"
    monkeypatch.setattr(dl, "DU_CMD", [_script(tmp_path, "du", f"touch {marker}"), "-sk"])
    assert dl._default_du_kb(tmp_path / "nope") == 0
    assert not marker.exists()


# --- #586: du hung for hours on TCC-protected folders, piled up and outlived its parent ---------------------------

def test_a_du_that_never_returns_is_killed_and_reported_not_measured(monkeypatch, tmp_path):
    """The simulated hang: du blocks forever (as on ~/Library/Containers under launchd). The walk must give up on time,
    say so, and leave no du behind."""
    pidfile = tmp_path / "pid"
    monkeypatch.setattr(dl, "DU_CMD", [_script(tmp_path, "du", f"echo $$ > {pidfile}; exec sleep 3600"), "-sk"])
    monkeypatch.setattr(dl, "DU_TIMEOUT_S", 1)
    t0 = time.monotonic()
    got = dl._default_du_kb(tmp_path)
    assert time.monotonic() - t0 < 10
    assert got == dl.NOT_MEASURED_TIMED_OUT
    assert _wait_dead(int(pidfile.read_text()), 2), "the hung du is still running"


def test_the_du_dies_on_its_own_even_when_its_parent_is_killed(tmp_path):
    """How the orphans happened: the Python that started du was killed (a test timeout cut the worker), so nothing was
    left to kill du, and it sat under launchd for 15 hours. The time limit must live in du itself."""
    pidfile = tmp_path / "pid"
    du = _script(tmp_path, "du", f"echo $$ > {pidfile}; exec sleep 3600")
    code = (f"import sys; sys.path.insert(0, {str(LIB)!r}); import disk_ledger as dl; dl.DU_CMD = [{du!r}, '-sk']; "
            f"dl.DU_TIMEOUT_S = 2; dl._default_du_kb(__import__('pathlib').Path({str(tmp_path)!r}))")
    parent = subprocess.Popen([sys.executable, "-c", code], env={**os.environ, "HOME": str(tmp_path)})
    end = time.monotonic() + 10
    while not (pidfile.exists() and pidfile.read_text().strip()) and time.monotonic() < end:
        time.sleep(0.05)
    du_pid = int(pidfile.read_text())
    parent.kill()  # SIGKILL: no cleanup code in the parent runs
    parent.wait()
    assert _alive(du_pid), "precondition: du outlived its parent"
    assert _wait_dead(du_pid, 8), "the orphaned du kept running after its time limit"


def test_a_folder_this_job_may_not_read_is_reported_protected_and_never_walked(monkeypatch, tmp_path):
    marker = tmp_path / "walked"
    monkeypatch.setattr(dl, "DU_CMD", [_script(tmp_path, "du", f"touch {marker}"), "-sk"])
    monkeypatch.setattr(dl, "PROBE_CMD", [_script(tmp_path, "ls", 'echo "ls: $1: Operation not permitted" >&2; exit 1')])
    assert dl._default_du_kb(tmp_path) == dl.NOT_MEASURED_PROTECTED
    assert not marker.exists()


def test_a_probe_that_blocks_on_a_privacy_prompt_counts_as_protected(monkeypatch, tmp_path):
    """TCC does not always refuse: under launchd the read can just block. The probe must give up in seconds."""
    pidfile = tmp_path / "pid"
    monkeypatch.setattr(dl, "PROBE_CMD", [_script(tmp_path, "ls", f"echo $$ > {pidfile}; exec sleep 3600")])
    monkeypatch.setattr(dl, "PROBE_TIMEOUT_S", 1)
    t0 = time.monotonic()
    assert dl._default_du_kb(tmp_path) == dl.NOT_MEASURED_PROTECTED
    assert time.monotonic() - t0 < 8
    assert _wait_dead(int(pidfile.read_text()), 2)


NICE_CAP = 19  # the most a process can raise its own nice value on macOS and Linux (os.nice stops here)


def _du_nice_under(monkeypatch, tmp_path, parent_nice: int) -> int:
    """The nice value du runs at when the caller itself already runs at parent_nice. Forks so the suite's own
    priority is untouched; main-health runs the whole suite niced (#457)."""
    out = tmp_path / "nice"
    monkeypatch.setattr(dl, "DU_CMD", [_script(tmp_path, "du", f'ps -o nice= -p $$ > {out}; printf "1\\t%s\\n" "$2"'), "-sk"])
    pid = os.fork()
    if pid == 0:
        try:
            os.nice(max(0, parent_nice - os.nice(0)))
            os._exit(0 if dl._default_du_kb(tmp_path) == 1 else 1)
        except BaseException:
            os._exit(2)
    _, status = os.waitpid(pid, 0)
    assert os.waitstatus_to_exitcode(status) == 0
    return int(out.read_text().strip())


@pytest.mark.parametrize("parent_nice", [0, 5, 9, 10, 15, 19])
def test_du_runs_at_low_priority(monkeypatch, tmp_path, parent_nice):
    # du goes 10 lower than its caller, or as low as the kernel allows. An already-niced caller (main-health) must
    # not make this look red: the cap made main falsely red on 2026-10-26 (assert 19 >= 20).
    start = max(parent_nice, os.nice(0))
    assert _du_nice_under(monkeypatch, tmp_path, parent_nice) == min(start + 10, NICE_CAP)


def test_garbage_du_output_is_not_measured_not_a_crash(monkeypatch, tmp_path):
    monkeypatch.setattr(dl, "DU_CMD", [_script(tmp_path, "du", "echo lots of bytes"), "-sk"])
    assert dl._default_du_kb(tmp_path) == 0


def test_a_du_that_cannot_start_is_not_measured(monkeypatch, tmp_path):
    monkeypatch.setattr(dl, "DU_CMD", [str(tmp_path / "no-such-du"), "-sk"])
    assert isinstance(dl._default_du_kb(tmp_path), str)


def test_unmeasured_folders_are_listed_not_counted_as_zero_bytes(monkeypatch, tmp_path):
    monkeypatch.setattr(dl, "HOME", tmp_path)
    lib = tmp_path / "Library"
    sizes = {lib / "Developer": 5, lib / "Containers": dl.NOT_MEASURED_PROTECTED,
             tmp_path / "Documents": dl.NOT_MEASURED_TIMED_OUT}
    skipped = []
    result = dl.measure_categories(du=lambda p: sizes.get(Path(p), 0), not_measured=skipped)
    assert result["xcode"] == 5 and result["app_support"] == 0 and result["user_files"] == 0
    assert {"path": str(lib / "Containers"), "reason": dl.NOT_MEASURED_PROTECTED} in skipped
    assert {"path": str(tmp_path / "Documents"), "reason": dl.NOT_MEASURED_TIMED_OUT} in skipped


def test_the_ledger_entry_says_what_it_could_not_measure(monkeypatch, tmp_path):
    ledger = tmp_path / "disk-ledger.jsonl"
    monkeypatch.setattr(dl, "LEDGER_PATH", ledger)
    monkeypatch.setattr(dl, "HOME", tmp_path)
    monkeypatch.setattr("machine_profile.registry_id", lambda: "mac-mini")
    protected = tmp_path / "Library" / "Containers"
    monkeypatch.setattr(dl, "_default_du_kb", lambda p: dl.NOT_MEASURED_PROTECTED if Path(p) == protected else 1)
    summary = dl.run_daily_ledger()
    row = json.loads(ledger.read_text().splitlines()[-1])
    assert row["not_measured"] == [{"path": str(protected), "reason": dl.NOT_MEASURED_PROTECTED}]
    assert summary["not_measured"] == row["not_measured"]


def test_two_overlapping_runs_the_second_returns_at_once_and_writes_nothing(monkeypatch, tmp_path):
    """A stuck run must not have the next one pile up behind it (as #457 did for main-health)."""
    ledger = tmp_path / "disk-ledger.jsonl"
    monkeypatch.setattr(dl, "LEDGER_PATH", ledger)
    monkeypatch.setattr(dl, "HOME", tmp_path)
    monkeypatch.setattr("machine_profile.registry_id", lambda: "mac-mini")
    entered, release = threading.Event(), threading.Event()
    calls = []

    def slow_du(p):
        calls.append(p)
        entered.set()
        release.wait(10)
        return 1
    monkeypatch.setattr(dl, "_default_du_kb", slow_du)
    first = {}
    t = threading.Thread(target=lambda: first.update(dl.run_daily_ledger()))
    t.start()
    assert entered.wait(5)
    t0 = time.monotonic()
    second = dl.run_daily_ledger()
    assert time.monotonic() - t0 < 2
    assert second.get("busy") is True
    assert not ledger.exists(), "the second run wrote while the first was still measuring"
    n = len(calls)
    release.set()
    t.join(10)
    assert first.get("categories") and len(ledger.read_text().splitlines()) == 1
    assert n == 1, "the second run started measuring"


def test_a_run_that_crashed_does_not_leave_the_lock_held(monkeypatch, tmp_path):
    monkeypatch.setattr(dl, "LEDGER_PATH", tmp_path / "disk-ledger.jsonl")
    monkeypatch.setattr(dl, "HOME", tmp_path)
    monkeypatch.setattr("machine_profile.registry_id", lambda: "mac-mini")

    def boom(p):
        raise RuntimeError("disk vanished")
    monkeypatch.setattr(dl, "_default_du_kb", boom)
    with pytest.raises(RuntimeError):
        dl.run_daily_ledger()
    monkeypatch.setattr(dl, "_default_du_kb", lambda p: 1)
    assert not dl.run_daily_ledger().get("busy")


def test_the_lock_is_held_across_processes(monkeypatch, tmp_path):
    """The real overlap is two launchd runs, two processes: a lock held by another process means busy."""
    ledger = tmp_path / "disk-ledger.jsonl"
    monkeypatch.setattr(dl, "LEDGER_PATH", ledger)
    lock = ledger.with_suffix(".lock")
    holder = subprocess.Popen([sys.executable, "-c",
                               f"import fcntl,time; f=open({str(lock)!r},'a'); fcntl.flock(f, fcntl.LOCK_EX); "
                               f"print('held', flush=True); time.sleep(30)"], stdout=subprocess.PIPE, text=True)
    try:
        assert holder.stdout.readline().strip() == "held"
        monkeypatch.setattr(dl, "_default_du_kb", lambda p: pytest.fail("measured while another run held the lock"))
        assert dl.run_daily_ledger().get("busy") is True
    finally:
        holder.kill()
        holder.wait()
