"""Tests for job_events.py. Run via:
    ~/.agents/venv/bin/python -m pytest lib/tests/test_job_events.py -v
"""
from __future__ import annotations
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

LIB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LIB))

import job_events as je  # noqa: E402

T0 = datetime(2026, 10, 5, 12, tzinfo=timezone.utc)


def read(tmp_path, job="demo"):
    return json.loads((tmp_path / f"{job}.json").read_text())


def test_a_run_records_each_step_as_it_happens(tmp_path):
    with je.job_run("demo", directory=tmp_path) as run:
        run.step("fetching", "18 repos")
        doc = read(tmp_path)  # visible mid-run, so the dashboard can show progress
        assert doc["runs"][-1]["status"] == "running"
        assert doc["runs"][-1]["steps"][-1]["step"] == "fetching"
        run.step("writing")
    last = read(tmp_path)["runs"][-1]
    assert last["status"] == "passed" and last["finished_at"]
    assert [s["step"] for s in last["steps"]] == ["fetching", "writing"]


def test_a_summary_can_be_attached_to_the_run(tmp_path):
    with je.job_run("demo", directory=tmp_path) as run:
        run.summary("30 projects")
    assert read(tmp_path)["runs"][-1]["summary"] == "30 projects"


def test_an_exception_marks_the_run_failed_with_the_error_and_still_raises(tmp_path):
    try:
        with je.job_run("demo", directory=tmp_path) as run:
            run.step("fetching")
            raise RuntimeError("offline")
    except RuntimeError:
        pass
    else:
        raise AssertionError("must re-raise")
    last = read(tmp_path)["runs"][-1]
    assert last["status"] == "failed" and "offline" in last["error"]
    assert last["steps"][-1]["step"] == "fetching"


def test_history_keeps_only_the_most_recent_runs(tmp_path):
    for i in range(je.KEEP_RUNS + 5):
        with je.job_run("demo", directory=tmp_path) as run:
            run.summary(f"run {i}")
    runs = read(tmp_path)["runs"]
    assert len(runs) == je.KEEP_RUNS
    assert runs[-1]["summary"] == f"run {je.KEEP_RUNS + 4}"


def test_recording_never_breaks_the_job_it_observes(tmp_path):
    blocker = tmp_path / "blocked"
    blocker.write_text("a file where the directory should be")
    with je.job_run("demo", directory=blocker / "sub") as run:  # cannot be created
        run.step("still works")
    # no exception escaped


def test_a_corrupt_history_file_is_replaced_not_fatal(tmp_path):
    (tmp_path / "demo.json").write_text("{nope")
    with je.job_run("demo", directory=tmp_path):
        pass
    assert read(tmp_path)["runs"][-1]["status"] == "passed"


def test_status_of_distinguishes_running_idle_failed_and_crashed():
    def doc(status, started_ago_min, finished=True):
        s = T0 - timedelta(minutes=started_ago_min)
        return {"job": "x", "runs": [{"status": status, "started_at": s.isoformat(), "finished_at": (s.isoformat() if finished else None), "steps": []}]}

    assert je.status_of(doc("running", 1, finished=False), T0) == "running"
    assert je.status_of(doc("running", 120, finished=False), T0) == "crashed"  # started long ago, never finished
    assert je.status_of(doc("passed", 5), T0) == "idle"
    assert je.status_of(doc("failed", 5), T0) == "failed"
    assert je.status_of({"job": "x", "runs": []}, T0) == "never"


def test_a_job_can_mark_its_run_failed_without_raising(tmp_path):
    with je.job_run("demo", directory=tmp_path) as run:
        run.fail("rate limited; kept last good")
    last = read(tmp_path)["runs"][-1]
    assert last["status"] == "failed" and last["error"] == "rate limited; kept last good"


def test_reporting_the_same_step_again_updates_it_instead_of_adding_a_duplicate(tmp_path):
    with je.job_run("demo", directory=tmp_path) as run:
        run.step("GitHub repos")
        run.step("GitHub repos", "18 found")
        run.step("Local folders")
    steps = read(tmp_path)["runs"][-1]["steps"]
    assert [(s["step"], s["detail"]) for s in steps] == [("GitHub repos", "18 found"), ("Local folders", "")]
