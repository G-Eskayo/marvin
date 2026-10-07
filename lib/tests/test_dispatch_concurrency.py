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
    assert len(alive) == 0 and len(dead) == 2


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
    assert state == {"busy": False}
