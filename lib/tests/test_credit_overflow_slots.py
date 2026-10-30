"""Plan first, credit for overflow (marvin #849): a Mac's normal slots bill the plan; `credit_slots` open on top of
them only while that Mac's API credit is ready. Run via:
    ~/.agents/venv/bin/python -m pytest lib/tests/test_credit_overflow_slots.py -v
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

LIB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LIB))

import dispatch_concurrency as dc  # noqa: E402

SETTINGS = {"parallel": True, "max_total": 3, "max_per_project": 3,
            "machine_slots": {"mac-mini-1": 2, "macbook-pro-1": 1}, "credit_slots": {"mac-mini-1": 2},
            "guards": {"min_disk_gb": 15, "min_github_budget_pct": 20}}


def _can(used, credit_ready, machine="mac-mini-1", settings=None):
    return dc.can_start_another(machine, settings or dc.validate(SETTINGS)[0], slots_in_use=lambda m: used,
                                disk_free_gb=lambda m: 500, github_budget_pct=lambda: 90, breaker_tripped=lambda: [],
                                missing_tools=lambda m: [], credit_ready=credit_ready)


def test_credit_slots_are_validated_and_default_to_none():
    clean, problems = dc.validate({**SETTINGS, "credit_slots": {"mac-mini-1": 2, "macbook-pro-1": 0, "x": 99}})
    assert clean["credit_slots"] == {"mac-mini-1": 2, "macbook-pro-1": 0}
    assert problems and "credit_slots.x" in problems[0]
    assert dc.validate({})[0]["credit_slots"] == {}


def test_without_credit_the_limit_is_the_plans_slots():
    s = dc.validate(SETTINGS)[0]
    assert dc.effective_limit(s, "mac-mini-1") == 2
    assert dc.effective_limit(s, "mac-mini-1", credit_ready=True) == 4
    assert dc.effective_limit(s, "macbook-pro-1", credit_ready=True) == 1   # no credit slots on the laptop


def test_the_credit_slots_sit_above_max_total():
    """max_total caps the plan's slots; the credit's are extra on top, or a cap of 3 would eat the Mini's overflow."""
    s = dc.validate({**SETTINGS, "max_total": 2})[0]
    assert dc.effective_limit(s, "mac-mini-1", credit_ready=True) == 4


def test_parallel_off_is_one_at_a_time_credit_or_not():
    s = dc.validate({**SETTINGS, "parallel": False})[0]
    assert dc.effective_limit(s, "mac-mini-1", credit_ready=True) == 1


def test_a_third_build_on_the_mini_waits_without_credit_and_starts_with_it():
    assert _can(2, lambda m: False)[0] is False
    assert _can(2, lambda m: True) == (True, None)
    assert _can(3, lambda m: True) == (True, None)
    ok, why = _can(4, lambda m: True)
    assert ok is False and "4 of 4" in why


def test_an_unreadable_credit_state_means_the_plans_slots_only():
    def boom(m):
        raise OSError("ssh down")
    assert _can(2, boom)[0] is False
    assert _can(1, boom) == (True, None)
    assert _can(2, None)[0] is False   # callers that don't pass a reader: today's behaviour


def _home(tmp_path, key="sk-ant-x", state=None):
    (tmp_path / ".claude" / "dispatch").mkdir(parents=True)
    if key is not None:
        (tmp_path / ".claude" / ".anthropic-api-key").write_text(key)
    if state is not None:
        (tmp_path / ".claude" / "dispatch" / "credit-state.json").write_text(json.dumps(state))
    return tmp_path


NOW = datetime(2026, 10, 30, 12, 0, tzinfo=timezone.utc)


def _at(hours_ago):
    return (NOW - timedelta(hours=hours_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")


def test_credit_is_ready_with_a_key_and_no_recent_failure(tmp_path):
    assert dc.credit_ready_local(_home(tmp_path), now=NOW) is True
    assert dc.credit_ready_local(_home(tmp_path / "ok", state={"ok": True, "why": "credit-ok", "at": _at(1)}), now=NOW) is True


def test_no_key_or_a_blank_key_or_a_paused_key_is_not_ready(tmp_path):
    assert dc.credit_ready_local(_home(tmp_path / "a", key=None), now=NOW) is False
    assert dc.credit_ready_local(_home(tmp_path / "b", key="  \n"), now=NOW) is False
    h = _home(tmp_path / "c", key=None)
    (h / ".claude" / ".anthropic-api-key.paused").write_text("sk-ant-x")
    assert dc.credit_ready_local(h, now=NOW) is False


def test_a_failed_check_closes_the_extra_slots_for_six_hours_then_retries(tmp_path):
    fail = {"ok": False, "why": "credit-exhausted"}
    assert dc.credit_ready_local(_home(tmp_path / "a", state={**fail, "at": _at(5.9)}), now=NOW) is False
    assert dc.credit_ready_local(_home(tmp_path / "b", state={**fail, "at": _at(6.1)}), now=NOW) is True


def test_a_garbled_or_future_dated_state_does_not_keep_the_slots_shut_forever(tmp_path):
    h = _home(tmp_path / "a")
    (h / ".claude" / "dispatch" / "credit-state.json").write_text("{not json")
    assert dc.credit_ready_local(h, now=NOW) is True   # the key decides; the next check rewrites the state
    future = {"ok": False, "why": "credit-exhausted", "at": (NOW + timedelta(days=3)).strftime("%Y-%m-%dT%H:%M:%SZ")}
    assert dc.credit_ready_local(_home(tmp_path / "b", state=future), now=NOW) is False
    assert dc.credit_ready_local(_home(tmp_path / "c", state={**future, "at": "garbage"}), now=NOW) is True


def test_others_running_excludes_this_build(tmp_path):
    records = [{"task_id": "me", "pid": 1}, {"task_id": "a", "pid": 2}, {"task_id": "b", "pid": 3}]
    assert dc.others_running("me", reader=lambda: records) == 2
    assert dc.others_running("zzz", reader=lambda: records) == 3


def test_credit_ready_remote_reads_true_false_and_failure(tmp_path):
    class P:
        def __init__(self, rc, out):
            self.returncode, self.stdout = rc, out
    assert dc.credit_ready_remote("mini", run=lambda *a, **k: P(0, "true\n")) is True
    assert dc.credit_ready_remote("mini", run=lambda *a, **k: P(0, "false\n")) is False
    assert dc.credit_ready_remote("mini", run=lambda *a, **k: P(255, "")) is None
