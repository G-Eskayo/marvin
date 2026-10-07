"""main_health: is the base branch green? Checked on a clean checkout, recorded, and shown in Health."""
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import main_health as mh  # noqa: E402

NOW = datetime(2026, 10, 7, 12, 0, tzinfo=timezone.utc)


def test_a_green_run_is_recorded_with_the_commit_it_checked(tmp_path):
    state = tmp_path / "m.json"
    res = mh.refresh(state_path=state, head=lambda: "abc1234", run_suite=lambda: (True, [], "1137 passed"), now=NOW)
    assert res == {"sha": "abc1234", "ok": True, "failed": [], "summary": "1137 passed", "checked_at": NOW.isoformat(), "ran": True}
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
