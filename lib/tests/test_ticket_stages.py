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


# ── stage files are keyed by owner + repo + number (#216) ───────────────────

CLARITY = "G-Eskayo/clarity-captions"


def test_two_projects_with_ticket_158_keep_separate_histories(tmp_path, monkeypatch):
    monkeypatch.setattr(ts, "STAGES_DIR", tmp_path)
    ts.record_stage(158, "claimed", "started", "marvin's", machine="m")
    ts.record_stage(158, "claimed", "started", "clarity's", machine="m", repo=CLARITY)
    assert [e["detail"] for e in ts.read_stages(158)] == ["marvin's"]
    assert [e["detail"] for e in ts.read_stages(158, repo=CLARITY)] == ["clarity's"]
    assert (tmp_path / "g-eskayo__marvin-158.json").exists()
    assert (tmp_path / "g-eskayo__clarity-captions-158.json").exists()


def test_marvin_is_keyed_the_same_with_or_without_the_repo_given(tmp_path, monkeypatch):
    monkeypatch.setattr(ts, "STAGES_DIR", tmp_path)
    ts.record_stage(9, "claimed", "started", machine="m", repo="G-Eskayo/marvin")
    ts.record_stage(9, "planning", "started", machine="m")
    assert [p.name for p in tmp_path.iterdir()] == ["g-eskayo__marvin-9.json"]
    assert len(ts.read_stages(9)) == 2


def test_marvin_reads_fall_back_to_the_old_bare_number_file(tmp_path, monkeypatch):
    monkeypatch.setattr(ts, "STAGES_DIR", tmp_path)
    (tmp_path / "158.json").write_text(json.dumps([{"stage": "claimed", "status": "started", "detail": "old"}]))
    assert [e["detail"] for e in ts.read_stages(158)] == ["old"]


def test_another_project_never_reads_marvins_bare_number_file(tmp_path, monkeypatch):
    monkeypatch.setattr(ts, "STAGES_DIR", tmp_path)
    (tmp_path / "158.json").write_text(json.dumps([{"stage": "claimed", "status": "started", "detail": "marvin's"}]))
    assert ts.read_stages(158, repo=CLARITY) == []


def test_writing_a_marvin_ticket_moves_its_old_bare_file_to_the_new_key(tmp_path, monkeypatch):
    monkeypatch.setattr(ts, "STAGES_DIR", tmp_path)
    (tmp_path / "158.json").write_text(json.dumps([{"stage": "claimed", "status": "started", "detail": "old"}]))
    ts.record_stage(158, "planning", "started", "new", machine="m")
    assert not (tmp_path / "158.json").exists()
    assert [e["detail"] for e in ts.read_stages(158)] == ["old", "new"]


def test_listing_tracked_tickets_is_per_project_and_includes_marvins_old_files(tmp_path, monkeypatch):
    monkeypatch.setattr(ts, "STAGES_DIR", tmp_path)
    (tmp_path / "2.json").write_text("[]")
    ts.record_stage(3, "claimed", "started", machine="m")
    ts.record_stage(5, "claimed", "started", machine="m", repo=CLARITY)
    ts.record_stage(8, "claimed", "started", machine="m", repo=CLARITY)
    assert ts.list_tracked_tickets() == [2, 3]
    assert ts.list_tracked_tickets(repo=CLARITY) == [5, 8]


def test_stage_key_round_trips_an_owner_with_a_hyphen(tmp_path):
    assert ts.stage_key("G-Eskayo/clarity-captions", 7) == "g-eskayo__clarity-captions-7"
    assert ts.parse_stage_key("g-eskayo__clarity-captions-7") == ("G-Eskayo/clarity-captions", 7)
    assert ts.parse_stage_key("g-eskayo__marvin-7") == ("G-Eskayo/marvin", 7)
    assert ts.parse_stage_key("7") == ("G-Eskayo/marvin", 7)
    assert ts.parse_stage_key("clarity-captions-7") is None


def test_record_stage_stores_run_id_when_given(tmp_path, monkeypatch):
    monkeypatch.setattr(ts, "STAGES_DIR", tmp_path)
    event = ts.record_stage(42, "claimed", "started", run_id="abc123")
    assert event["run_id"] == "abc123"
    events = ts.read_stages(42)
    assert events[0]["run_id"] == "abc123"


def test_record_stage_stores_none_for_run_id_by_default(tmp_path, monkeypatch):
    monkeypatch.setattr(ts, "STAGES_DIR", tmp_path)
    event = ts.record_stage(42, "claimed", "started")
    assert event["run_id"] is None


def test_claim_owner_returns_the_most_recent_claimed_events_run_id(tmp_path, monkeypatch):
    monkeypatch.setattr(ts, "STAGES_DIR", tmp_path)
    ts.record_stage(42, "claimed", "started", run_id="run1")
    ts.record_stage(42, "planning", "started")
    ts.record_stage(42, "claimed", "started", run_id="run2")
    assert ts.claim_owner(42) == "run2"


def test_claim_owner_returns_none_when_no_claimed_event_exists(tmp_path, monkeypatch):
    monkeypatch.setattr(ts, "STAGES_DIR", tmp_path)
    ts.record_stage(42, "planning", "started")
    assert ts.claim_owner(42) is None


def test_claim_owner_returns_none_for_untracked_tickets(tmp_path, monkeypatch):
    monkeypatch.setattr(ts, "STAGES_DIR", tmp_path)
    assert ts.claim_owner(999) is None


def test_claim_owner_is_per_project(tmp_path, monkeypatch):
    monkeypatch.setattr(ts, "STAGES_DIR", tmp_path)
    clarity = "G-Eskayo/clarity-captions"
    ts.record_stage(7, "claimed", "started", run_id="marvin-run", repo=None)
    ts.record_stage(7, "claimed", "started", run_id="clarity-run", repo=clarity)
    assert ts.claim_owner(7, repo=None) == "marvin-run"
    assert ts.claim_owner(7, repo=clarity) == "clarity-run"
