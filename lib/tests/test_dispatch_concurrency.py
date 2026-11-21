"""dispatch_concurrency: the parallel-dispatch settings and the guard rails (ADR 0052, ticket #194).
Also tests task record tracking, reaping, and dispatch-state summary updates (AC 0193)."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import dispatch_concurrency as dc  # noqa: E402

ON = {**dc.DEFAULTS, "parallel": True}


def ok_readers(**over):
    r = dict(slots_in_use=lambda m: 0, disk_free_gb=lambda m: 100, github_budget_pct=lambda: 90,
             breaker_tripped=lambda: [], missing_tools=lambda m: [])
    r.update(over)
    return r


# --- settings ---

def test_defaults_are_off_one_per_project_mini_two_macbook_one():
    assert dc.DEFAULTS["parallel"] is False and dc.DEFAULTS["max_per_project"] == 1
    assert dc.DEFAULTS["machine_slots"] == {"mac-mini-1": 2, "macbook-pro-1": 1}


def test_missing_or_broken_file_falls_back_to_the_defaults(tmp_path):
    assert dc.load(tmp_path / "nope.json") == dc.DEFAULTS
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    assert dc.load(bad) == dc.DEFAULTS


def test_invalid_values_fall_back_field_by_field_not_wholesale(tmp_path):
    p = tmp_path / "d.json"
    p.write_text(json.dumps({"parallel": True, "max_total": -3, "max_per_project": "x", "machine_slots": {"mac-mini-1": 4}}))
    s = dc.load(p)
    assert s["parallel"] is True and s["max_total"] == dc.DEFAULTS["max_total"] and s["max_per_project"] == 1
    assert s["machine_slots"]["mac-mini-1"] == 4 and s["machine_slots"]["macbook-pro-1"] == 1


def test_validate_names_each_problem_and_save_refuses_invalid(tmp_path):
    assert dc.validate({**ON, "max_total": 0})[1] == ["max_total must be a whole number from 1 to 8"]
    assert dc.validate({**ON, "max_per_project": 99})[1] == ["max_per_project must be a whole number from 1 to 8"]
    with pytest.raises(ValueError, match="max_total"):
        dc.save({**ON, "max_total": 0}, tmp_path / "d.json")
    assert not (tmp_path / "d.json").exists()


def test_save_then_load_round_trips(tmp_path):
    p = tmp_path / "d.json"
    dc.save({**ON, "max_total": 3}, p)
    assert dc.load(p)["max_total"] == 3 and dc.load(p)["parallel"] is True


# --- limits ---

def test_off_means_exactly_one_per_machine_whatever_else_says():
    off = {**dc.DEFAULTS, "max_total": 8}
    assert dc.effective_limit(off, "mac-mini-1") == 1 and dc.effective_limit(off, "macbook-pro-1") == 1


def test_on_is_the_smaller_of_machine_slots_and_max_total():
    assert dc.effective_limit({**ON, "max_total": 5}, "mac-mini-1") == 2
    assert dc.effective_limit({**ON, "max_total": 1}, "mac-mini-1") == 1
    assert dc.effective_limit(ON, "macbook-pro-1") == 1


def test_a_machine_nobody_listed_gets_one_slot():
    assert dc.effective_limit(ON, "node-3") == 1


# --- guard rails ---

def test_starts_when_a_slot_is_free_and_every_guard_passes():
    assert dc.can_start_another("mac-mini-1", ON, **ok_readers()) == (True, None)


def test_refuses_when_the_machine_is_full():
    ok, why = dc.can_start_another("mac-mini-1", ON, **ok_readers(slots_in_use=lambda m: 2))
    assert not ok and why == "mac-mini-1 is full: 2 of 2 slots in use"


def test_off_still_allows_exactly_one_and_ignores_guards():
    off = dc.DEFAULTS
    assert dc.can_start_another("mac-mini-1", off, **ok_readers(disk_free_gb=lambda m: 1)) == (True, None)
    ok, why = dc.can_start_another("mac-mini-1", off, **ok_readers(slots_in_use=lambda m: 1))
    assert not ok and "1 of 1" in why


def test_low_disk_names_the_numbers():
    ok, why = dc.can_start_another("mac-mini-1", ON, **ok_readers(disk_free_gb=lambda m: 9, slots_in_use=lambda m: 1))
    assert not ok and why == "disk 9 GB free on mac-mini-1, minimum 15"


def test_low_github_budget_names_the_numbers():
    ok, why = dc.can_start_another("mac-mini-1", ON, **ok_readers(github_budget_pct=lambda: 12, slots_in_use=lambda m: 1))
    assert not ok and why == "GitHub request budget 12% left, minimum 20%"


def test_a_tripped_circuit_breaker_pauses_new_starts():
    trip = [{"project": "o/clarity", "signature": "xcode missing"}]
    ok, why = dc.can_start_another("mac-mini-1", ON, **ok_readers(breaker_tripped=lambda: trip, slots_in_use=lambda m: 1))
    assert not ok and "circuit breaker" in why and "clarity" in why


def test_missing_required_tools_name_them():
    ok, why = dc.can_start_another("macbook-pro-1", ON, **ok_readers(missing_tools=lambda m: ["xcodebuild", "swift"]))
    assert not ok and why == "macbook-pro-1 lacks tools the project needs: xcodebuild, swift"


def test_an_unreadable_guard_never_blocks_starting():
    boom = lambda *a: (_ for _ in ()).throw(RuntimeError("gh down"))
    assert dc.can_start_another("mac-mini-1", ON, **ok_readers(github_budget_pct=boom, disk_free_gb=lambda m: None)) == (True, None)


def test_cli_get_prints_settings_and_set_refuses_invalid(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(dc, "PATH", tmp_path / "d.json")
    assert dc._cli(["get"]) == 0 and json.loads(capsys.readouterr().out)["parallel"] is False
    assert dc._cli(["set", json.dumps({**ON, "max_total": 3})]) == 0
    assert dc.load()["max_total"] == 3
    assert dc._cli(["set", json.dumps({**ON, "max_total": 0})]) == 1
    assert "max_total" in capsys.readouterr().err and dc.load()["max_total"] == 3
    assert dc._cli(["set", "{not json"]) == 1


# --- task record tracking ---

def test_partition_alive_separates_alive_and_dead_processes():
    records = [
        {"task_id": "a", "pid": 1, "machine": "m1"},  # init, always alive
        {"task_id": "b", "pid": 999999, "machine": "m1"},  # very unlikely to exist
    ]
    def is_alive(pid):
        return pid == 1
    alive, dead = dc.partition_alive(records, is_alive)
    assert [r["task_id"] for r in alive] == ["a"]
    assert [r["task_id"] for r in dead] == ["b"]


def test_partition_alive_handles_missing_pid():
    records = [
        {"task_id": "a", "machine": "m1"},  # no pid key
        {"task_id": "b", "pid": None, "machine": "m1"},
    ]
    def is_alive(pid):
        return True  # should never be called
    alive, dead = dc.partition_alive(records, is_alive)
    assert not alive and len(dead) == 2


def test_read_task_records_globs_json_files_and_skips_malformed():
    tmp = Path(__import__("tempfile").mkdtemp())
    try:
        (tmp / "task1.json").write_text('{"task_id": "t1", "pid": 123}')
        (tmp / "task2.json").write_text('{"task_id": "t2", "pid": 456}')
        (tmp / "broken.json").write_text('{not json}')
        records = dc._read_task_records(tmp)
        assert len(records) == 2
        assert {r["task_id"] for r in records} == {"t1", "t2"}
    finally:
        import shutil
        shutil.rmtree(tmp)


def test_reap_unlinks_dead_record_files():
    tmp = Path(__import__("tempfile").mkdtemp())
    try:
        (tmp / "t1.json").write_text('{"task_id": "t1"}')
        (tmp / "t2.json").write_text('{"task_id": "t2"}')
        dead = [{"task_id": "t1"}, {"task_id": "t2"}]
        dc._reap(dead, tmp)
        assert not (tmp / "t1.json").exists()
        assert not (tmp / "t2.json").exists()
    finally:
        import shutil
        shutil.rmtree(tmp)


def test_slots_in_use_reads_and_reaps_dead_and_filters_by_machine():
    tmp = Path(__import__("tempfile").mkdtemp())
    try:
        records = [
            {"task_id": "a", "pid": 1, "machine": "m1"},
            {"task_id": "b", "pid": 999999, "machine": "m1"},
            {"task_id": "c", "pid": 1, "machine": "m2"},
        ]
        for r in records:
            (tmp / f"{r['task_id']}.json").write_text(json.dumps(r))

        def fake_is_alive(pid):
            return pid == 1

        alive = dc.slots_in_use("m1", is_alive=fake_is_alive, tasks_dir=tmp)
        assert [r["task_id"] for r in alive] == ["a"]

        assert not (tmp / "b.json").exists()  # reaped
        assert (tmp / "a.json").exists()
        assert (tmp / "c.json").exists()  # filtered out, not reaped
    finally:
        import shutil
        shutil.rmtree(tmp)


def test_refresh_dispatch_state_summary_busy_when_records_exist(tmp_path, monkeypatch):
    monkeypatch.setattr(dc, "DISPATCH_STATE_PATH", tmp_path / "state.json")
    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir()

    records = [
        {"task_id": "t1", "task": "task one", "started_at": "2026-10-07T10:00:00Z", "pid": 100},
        {"task_id": "t2", "task": "task two", "started_at": "2026-10-07T10:05:00Z", "pid": 100},
    ]
    for r in records:
        (tasks_dir / f"{r['task_id']}.json").write_text(json.dumps(r))

    def fake_is_alive(pid):
        return True  # all PIDs are alive for this test

    monkeypatch.setattr(dc, "_pid_alive", fake_is_alive)
    dc.refresh_dispatch_state_summary(tasks_dir)
    state = json.loads((tmp_path / "state.json").read_text())
    assert state["busy"] is True
    assert state["task_id"] == "t1"  # earliest
    assert state["started_at"] == "2026-10-07T10:00:00Z"


def test_refresh_dispatch_state_summary_idle_when_no_records(tmp_path, monkeypatch):
    monkeypatch.setattr(dc, "DISPATCH_STATE_PATH", tmp_path / "state.json")
    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir()

    dc.refresh_dispatch_state_summary(tasks_dir)
    state = json.loads((tmp_path / "state.json").read_text())
    import stamped
    assert {k: v for k, v in state.items() if k not in stamped.STAMP_KEYS} == {"busy": False}
    assert state["tolerance_s"] == dc.DISPATCH_TOLERANCE_S and state["alive_at"]  # stamped (marvin#1223)


def test_the_shipped_dispatch_config_is_valid_and_turns_box_builds_on():
    """config/dispatch.json asked for 2 box slots while BOX_MAX_SLOTS is 1, so validate() dropped the value and the
    default 0 turned box builds off for weeks without anyone seeing it (found live 2026-11-12). Every field of the
    shipped file must survive validation."""
    import json
    from pathlib import Path
    raw = json.loads((Path(__file__).resolve().parents[2] / "config" / "dispatch.json").read_text())
    clean, problems = dc.validate(raw)
    assert problems == []
    assert dc.box_slots(clean) >= 1


# --- process start time and reuse checking ---

def test_etime_to_seconds_parses_elapsed_time():
    assert dc._etime_to_seconds("1:30") == 90
    assert dc._etime_to_seconds("1:00:30") == 3630
    assert dc._etime_to_seconds("1-02:30:45") == 95445  # 1 day + 2h 30m 45s
    assert dc._etime_to_seconds("0:00:05") == 5


def test_etime_to_seconds_handles_invalid_input():
    assert dc._etime_to_seconds("") is None
    assert dc._etime_to_seconds("invalid") is None
    assert dc._etime_to_seconds(None) is None


def test_partition_alive_with_reuse_check_detects_pid_reuse():
    from datetime import datetime, timezone, timedelta
    now = datetime.now(timezone.utc)
    # Task a: record says started 400s ago
    t_a_record = now - timedelta(seconds=400)
    # Task b: record says started 600s ago (much longer ago)
    t_b_record = now - timedelta(seconds=600)

    records = [
        {"task_id": "a", "pid": 1, "machine": "m1", "started_at": t_a_record.isoformat()},
        {"task_id": "b", "pid": 999999, "machine": "m1", "started_at": t_b_record.isoformat()},
    ]
    def is_alive(pid):
        return pid in (1, 999999)

    # PID 1 process actually started when the record says (400s ago) - same process
    # PID 999999 process actually started 100s ago, but record says 600s ago - PID was reused (500s diff > 300s)
    def fake_process_start(pid):
        if pid == 1:
            return t_a_record  # matches its record
        elif pid == 999999:
            return now - timedelta(seconds=100)  # 500s diff from record > REUSE_SLACK_S=300s
        return None

    alive, dead = dc.partition_alive(records, is_alive, process_started_at=fake_process_start)
    assert [r["task_id"] for r in alive] == ["a"]  # only PID 1 matches its record
    assert [r["task_id"] for r in dead] == ["b"]  # PID 999999 was reused


def test_partition_alive_with_reuse_check_keeps_young_processes():
    from datetime import datetime, timezone, timedelta
    records = [
        {"task_id": "a", "pid": 1, "machine": "m1"},  # init, always alive
    ]
    def is_alive(pid):
        return pid == 1

    # process_started_at returns a time 100 seconds ago (< REUSE_SLACK_S)
    young_start = datetime.now(timezone.utc) - timedelta(seconds=100)
    def young_process_start(pid):
        return young_start if pid == 1 else None

    alive, dead = dc.partition_alive(records, is_alive, process_started_at=young_process_start)
    assert [r["task_id"] for r in alive] == ["a"]  # young process is kept
    assert len(dead) == 0


def test_quarantine_stale_moves_file_to_stale_records():
    tmp = Path(__import__("tempfile").mkdtemp())
    try:
        tasks_dir = tmp / "tasks"
        tasks_dir.mkdir()
        stale_dir = tmp / "stale-records"

        bad_file = tasks_dir / "bad.json"
        bad_file.write_text("{malformed}")

        dc._quarantine_stale(bad_file, tasks_dir, "test reason")

        assert not bad_file.exists()
        assert (stale_dir / "bad.json").exists()
    finally:
        import shutil
        shutil.rmtree(tmp)


def test_refresh_dispatch_state_summary_with_process_started_at(tmp_path, monkeypatch):
    from datetime import datetime, timezone, timedelta

    monkeypatch.setattr(dc, "DISPATCH_STATE_PATH", tmp_path / "state.json")
    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir()

    # Create two task records
    now = datetime.now(timezone.utc)
    # t1: process still matches its record (not reused)
    # t2: PID reused (process start time doesn't match record)
    t1_record_start = now - timedelta(seconds=50)
    t2_record_start = now - timedelta(seconds=400)

    records = [
        {"task_id": "t1", "task": "matching task", "started_at": t1_record_start.isoformat(), "pid": 100},
        {"task_id": "t2", "task": "reused pid task", "started_at": t2_record_start.isoformat(), "pid": 101},
    ]
    for r in records:
        (tasks_dir / f"{r['task_id']}.json").write_text(json.dumps(r))

    def fake_is_alive(pid):
        return True

    def fake_process_started_at(pid):
        if pid == 100:
            # Actual start time matches the record
            return t1_record_start
        elif pid == 101:
            # Actual start time is now (doesn't match record which is 400s old)
            return now
        return None

    monkeypatch.setattr(dc, "_pid_alive", fake_is_alive)

    dc.refresh_dispatch_state_summary(tasks_dir, process_started_at=fake_process_started_at)
    state = json.loads((tmp_path / "state.json").read_text())

    # Only t1 should remain (t2 detected as reused PID and reaped)
    assert state["busy"] is True
    assert state["task_id"] == "t1"


def test_cli_refresh_summary_with_process_started_at(tmp_path, monkeypatch, capsys):
    from datetime import datetime, timezone
    monkeypatch.setattr(dc, "DISPATCH_STATE_PATH", tmp_path / "state.json")
    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir()
    monkeypatch.setattr(dc, "TASKS_DIR", tasks_dir)

    # Create a task record with a start time that matches the fake process
    now = datetime.now(timezone.utc)
    record_start = now.isoformat()
    (tasks_dir / "t1.json").write_text(json.dumps({"task_id": "t1", "task": "test", "started_at": record_start, "pid": 1}))

    def fake_is_alive(pid):
        return pid == 1

    def fake_process_start(pid):
        return now if pid == 1 else None

    monkeypatch.setattr(dc, "_pid_alive", fake_is_alive)
    monkeypatch.setattr(dc, "_process_start_time", fake_process_start)

    # Call the refresh-summary CLI command
    assert dc._cli(["refresh-summary"]) == 0
    state = json.loads((tmp_path / "state.json").read_text())
    # Task record should still be there because process start matches record start
    assert state.get("busy") is True
    assert state.get("task_id") == "t1"


def test_cli_count_in_use_prints_count(tmp_path, monkeypatch, capsys):
    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir()

    # Create some task records
    for i in range(3):
        (tasks_dir / f"t{i}.json").write_text(json.dumps({"task_id": f"t{i}", "pid": 1}))

    def fake_is_alive(pid):
        return pid == 1

    monkeypatch.setattr(dc, "_pid_alive", fake_is_alive)
    monkeypatch.setattr(dc, "TASKS_DIR", tasks_dir)

    # Call count-in-use
    assert dc._cli(["count-in-use"]) == 0
    output = capsys.readouterr().out.strip()
    assert output == "3"


def test_partition_alive_with_mismatched_start_times_detects_reuse():
    """Core bug fix: reuse check should compare start times, not elapsed time."""
    from datetime import datetime, timezone, timedelta
    now = datetime.now(timezone.utc)
    record_started = now - timedelta(seconds=400)

    records = [
        {"task_id": "a", "pid": 1, "machine": "m1", "started_at": record_started.isoformat()},
    ]
    def is_alive(pid):
        return pid == 1

    # Process is alive but started at a different time than the record claims
    # (time difference > REUSE_SLACK_S), so it's a reused PID
    def process_start_time(pid):
        if pid == 1:
            return now - timedelta(seconds=750)  # 350 seconds off from record (> REUSE_SLACK_S=300)
        return None

    alive, dead = dc.partition_alive(records, is_alive, process_started_at=process_start_time)
    assert len(alive) == 0
    assert len(dead) == 1
    assert dead[0]["task_id"] == "a"


def test_partition_alive_with_matching_start_times_keeps_process():
    """Reuse check: if start times match (within tolerance), process is not reused."""
    from datetime import datetime, timezone, timedelta
    now = datetime.now(timezone.utc)
    record_started = now - timedelta(seconds=400)

    records = [
        {"task_id": "a", "pid": 1, "machine": "m1", "started_at": record_started.isoformat()},
    ]
    def is_alive(pid):
        return pid == 1

    # Process start time matches the record (within tolerance)
    def process_start_time(pid):
        if pid == 1:
            return record_started + timedelta(seconds=1)  # Only 1 second off
        return None

    alive, dead = dc.partition_alive(records, is_alive, process_started_at=process_start_time)
    assert len(alive) == 1
    assert alive[0]["task_id"] == "a"
    assert len(dead) == 0


def test_partition_alive_with_unparseable_started_at_marks_dead():
    """Reuse check: if started_at is unparseable, treat record as stale."""
    from datetime import datetime, timezone, timedelta
    records = [
        {"task_id": "a", "pid": 1, "machine": "m1", "started_at": "not-a-valid-timestamp"},
    ]
    def is_alive(pid):
        return pid == 1

    def process_start_time(pid):
        if pid == 1:
            return datetime.now(timezone.utc)
        return None

    alive, dead = dc.partition_alive(records, is_alive, process_started_at=process_start_time)
    assert len(alive) == 0
    assert len(dead) == 1


def test_partition_alive_without_started_at_keeps_process():
    """Reuse check: if started_at is missing, don't use the reuse check (backward compat)."""
    from datetime import datetime, timezone
    records = [
        {"task_id": "a", "pid": 1, "machine": "m1"},  # no started_at
    ]
    def is_alive(pid):
        return pid == 1

    def process_start_time(pid):
        if pid == 1:
            return datetime.now(timezone.utc)
        return None

    alive, dead = dc.partition_alive(records, is_alive, process_started_at=process_start_time)
    # Without started_at, we can't compare, so the process is kept if it's alive
    assert len(alive) == 1
    assert len(dead) == 0
