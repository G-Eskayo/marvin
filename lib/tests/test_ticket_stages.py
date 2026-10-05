"""Tests for ticket_stages.py. Run via:
    ~/.agents/venv/bin/python -m pytest lib/tests/test_ticket_stages.py -v
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

LIB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LIB))

import ticket_stages as ts  # noqa: E402


def test_record_stage_appends_and_returns_the_event(tmp_path, monkeypatch):
    monkeypatch.setattr(ts, "STAGES_DIR", tmp_path)
    event = ts.record_stage(42, "planning", "started", "reading the issue", machine="mac-mini-1")
    assert event["stage"] == "planning"
    assert event["status"] == "started"
    assert event["detail"] == "reading the issue"
    assert event["machine"] == "mac-mini-1"
    assert "timestamp" in event


def test_record_stage_carries_cost_usd_when_given(tmp_path, monkeypatch):
    monkeypatch.setattr(ts, "STAGES_DIR", tmp_path)
    event = ts.record_stage(42, "executing", "passed", cost_usd=0.0108)
    assert event["cost_usd"] == 0.0108


def test_record_stage_cost_usd_defaults_to_none_not_zero(tmp_path, monkeypatch):
    # None, not 0.0 -- a stage with no LLM call (claimed, merging) must be
    # distinguishable from a call that genuinely cost nothing, or a sum
    # over events would silently undercount real usage.
    monkeypatch.setattr(ts, "STAGES_DIR", tmp_path)
    event = ts.record_stage(42, "claimed", "started")
    assert event["cost_usd"] is None


def test_record_stage_defaults_machine_to_registry_id(tmp_path, monkeypatch):
    monkeypatch.setattr(ts, "STAGES_DIR", tmp_path)
    monkeypatch.setattr(ts.machine_profile, "registry_id", lambda: "mac-mini-1")
    event = ts.record_stage(42, "claimed", "started")
    assert event["machine"] == "mac-mini-1"


def test_record_stage_rejects_unknown_stage(tmp_path, monkeypatch):
    monkeypatch.setattr(ts, "STAGES_DIR", tmp_path)
    try:
        ts.record_stage(42, "not-a-real-stage", "started")
        assert False, "expected ValueError"
    except ValueError as e:
        assert "not-a-real-stage" in str(e)


def test_record_stage_rejects_unknown_status(tmp_path, monkeypatch):
    monkeypatch.setattr(ts, "STAGES_DIR", tmp_path)
    try:
        ts.record_stage(42, "claimed", "sideways")
        assert False, "expected ValueError"
    except ValueError as e:
        assert "sideways" in str(e)


def test_read_stages_returns_events_in_append_order(tmp_path, monkeypatch):
    monkeypatch.setattr(ts, "STAGES_DIR", tmp_path)
    ts.record_stage(42, "claimed", "started", machine="m1")
    ts.record_stage(42, "planning", "started", machine="m1")
    ts.record_stage(42, "planning", "passed", machine="m1")
    events = ts.read_stages(42)
    assert [e["stage"] for e in events] == ["claimed", "planning", "planning"]
    assert [e["status"] for e in events] == ["started", "started", "passed"]


def test_read_stages_returns_empty_list_for_an_untracked_ticket(tmp_path, monkeypatch):
    monkeypatch.setattr(ts, "STAGES_DIR", tmp_path)
    assert ts.read_stages(999) == []


def test_read_stages_returns_empty_list_for_a_corrupt_file(tmp_path, monkeypatch):
    monkeypatch.setattr(ts, "STAGES_DIR", tmp_path)
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "42.json").write_text("not json")
    assert ts.read_stages(42) == []


def test_list_tracked_tickets_returns_sorted_numeric_ids(tmp_path, monkeypatch):
    monkeypatch.setattr(ts, "STAGES_DIR", tmp_path)
    ts.record_stage(117, "claimed", "started")
    ts.record_stage(30, "claimed", "started")
    ts.record_stage(94, "claimed", "started")
    assert ts.list_tracked_tickets() == [30, 94, 117]


def test_list_tracked_tickets_empty_when_dir_does_not_exist_yet(tmp_path):
    missing = tmp_path / "does-not-exist"
    import ticket_stages as ts2
    original = ts2.STAGES_DIR
    ts2.STAGES_DIR = missing
    try:
        assert ts2.list_tracked_tickets() == []
    finally:
        ts2.STAGES_DIR = original


# ── tickets of other projects must not collide with marvin's ────────────────

def test_a_ticket_of_another_project_gets_its_own_timeline_even_when_the_number_matches(tmp_path, monkeypatch):
    monkeypatch.setattr(ts, "STAGES_DIR", tmp_path)
    ts.record_stage(7, "claimed", "started", "marvin's", machine="m")
    ts.record_stage(7, "claimed", "started", "clarity's", machine="m", repo="G-Eskayo/clarity-captions")
    assert [e["detail"] for e in ts.read_stages(7)] == ["marvin's"]
    assert [e["detail"] for e in ts.read_stages(7, repo="G-Eskayo/clarity-captions")] == ["clarity's"]
    assert (tmp_path / "7.json").exists() and (tmp_path / "clarity-captions-7.json").exists()


def test_marvin_tickets_keep_their_plain_number_with_or_without_the_repo_given(tmp_path, monkeypatch):
    monkeypatch.setattr(ts, "STAGES_DIR", tmp_path)
    ts.record_stage(9, "claimed", "started", machine="m", repo="G-Eskayo/marvin")
    assert (tmp_path / "9.json").exists()
    assert len(ts.read_stages(9)) == 1


def test_listing_tracked_tickets_is_per_project(tmp_path, monkeypatch):
    monkeypatch.setattr(ts, "STAGES_DIR", tmp_path)
    ts.record_stage(3, "claimed", "started", machine="m")
    ts.record_stage(5, "claimed", "started", machine="m", repo="G-Eskayo/clarity-captions")
    ts.record_stage(8, "claimed", "started", machine="m", repo="G-Eskayo/clarity-captions")
    assert ts.list_tracked_tickets() == [3]
    assert ts.list_tracked_tickets(repo="G-Eskayo/clarity-captions") == [5, 8]
