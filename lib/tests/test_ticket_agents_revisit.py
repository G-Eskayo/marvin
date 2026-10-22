#!/usr/bin/env python3
"""Tests for revisit ticket agent: plan_revisit, collect_hold_comments, write_revisit_state."""
import json
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import ticket_agents as ta  # noqa: E402


def test_plan_revisit_past_due():
    """Held ticket with past-due revisit date"""
    now = datetime(2026, 10, 20, tzinfo=timezone.utc)
    issues = [
        {"number": 1, "title": "On hold", "labels": [{"name": "hold"}]}
    ]
    hold_comments = {
        1: [{"body": "Revisit by: 2026-10-15", "createdAt": "2026-10-01T10:00:00Z"}]
    }
    result = ta.plan_revisit("test/repo", issues, hold_comments, {}, now)
    assert len(result) == 3  # remove hold, add needs-triage, comment
    assert result[0]["op"] == "remove_label"
    assert result[0]["arg"] == "hold"
    assert result[1]["op"] == "add_label"
    assert result[1]["arg"] == "needs-triage"
    assert result[2]["op"] == "comment"


def test_plan_revisit_future_due():
    """Held ticket with future revisit date"""
    now = datetime(2026, 10, 10, tzinfo=timezone.utc)
    issues = [
        {"number": 1, "title": "On hold", "labels": [{"name": "hold"}]}
    ]
    hold_comments = {
        1: [{"body": "Revisit by: 2026-10-15", "createdAt": "2026-10-01T10:00:00Z"}]
    }
    result = ta.plan_revisit("test/repo", issues, hold_comments, {}, now)
    assert not result  # not due yet


def test_plan_revisit_no_revisit_line():
    """Held ticket with no revisit line: skipped silently"""
    now = datetime(2026, 10, 20, tzinfo=timezone.utc)
    issues = [
        {"number": 1, "title": "On hold", "labels": [{"name": "hold"}]}
    ]
    hold_comments = {1: []}  # no revisit line
    result = ta.plan_revisit("test/repo", issues, hold_comments, {}, now)
    assert not result  # Health will flag this


def test_plan_revisit_pinned():
    """Pinned ticket is never touched"""
    now = datetime(2026, 10, 20, tzinfo=timezone.utc)
    issues = [
        {"number": 1, "title": "On hold", "labels": [{"name": "hold"}, {"name": "pinned"}]}
    ]
    hold_comments = {
        1: [{"body": "Revisit by: 2026-10-15", "createdAt": "2026-10-01T10:00:00Z"}]
    }
    result = ta.plan_revisit("test/repo", issues, hold_comments, {}, now)
    assert not result  # pinned, never touched


def test_plan_revisit_multiple_tickets():
    """Multiple held tickets: each handled independently"""
    now = datetime(2026, 10, 20, tzinfo=timezone.utc)
    issues = [
        {"number": 1, "title": "On hold past due", "labels": [{"name": "hold"}]},
        {"number": 2, "title": "On hold future", "labels": [{"name": "hold"}]},
    ]
    hold_comments = {
        1: [{"body": "Revisit by: 2026-10-15", "createdAt": "2026-10-01T10:00:00Z"}],
        2: [{"body": "Revisit by: 2026-10-25", "createdAt": "2026-10-01T10:00:00Z"}],
    }
    result = ta.plan_revisit("test/repo", issues, hold_comments, {}, now)
    # Only ticket 1 should act (past due)
    assert len(result) == 3
    assert result[0]["number"] == 1


def test_plan_revisit_ref_open():
    """Held ticket with condition #N that is still open"""
    now = datetime(2026, 10, 25, tzinfo=timezone.utc)  # past the date
    issues = [
        {"number": 1, "title": "On hold", "labels": [{"name": "hold"}]}
    ]
    hold_comments = {
        1: [{"body": "Revisit by: 2026-10-20 - #2 closes", "createdAt": "2026-10-01T10:00:00Z"}]
    }
    ref_states = {2: {"state": "OPEN"}}
    result = ta.plan_revisit("test/repo", issues, hold_comments, ref_states, now)
    # Date passed, so acts anyway
    assert len(result) == 3


def test_collect_hold_comments_empty():
    """No held tickets"""
    def mock_gh(args):
        return json.dumps([])
    result = ta.collect_hold_comments("test/repo", set(), mock_gh)
    assert result == {}


def test_collect_hold_comments_gh_error():
    """GitHub call fails: returns empty dict"""
    def mock_gh(args):
        raise Exception("network error")
    result = ta.collect_hold_comments("test/repo", {1}, mock_gh)
    assert result == {}


def test_collect_hold_comments_malformed_json():
    """GitHub returns malformed JSON"""
    def mock_gh(args):
        return "not json"
    result = ta.collect_hold_comments("test/repo", {1}, mock_gh)
    assert result == {}


def test_collect_hold_comments_success():
    """Successful fetch of hold comments"""
    def mock_gh(args):
        return json.dumps([
            {"number": 1, "comments": [{"body": "Revisit by: 2026-10-15"}]},
            {"number": 2, "comments": [{"body": "other comment"}]}
        ])
    result = ta.collect_hold_comments("test/repo", {1, 2}, mock_gh)
    assert 1 in result
    assert 2 in result
    assert len(result[1]) == 1
    assert result[1][0]["body"] == "Revisit by: 2026-10-15"


def test_write_revisit_state_success():
    """Write state file successfully"""
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "revisit.json"
        now = datetime(2026, 10, 10, 12, 0, 0, tzinfo=timezone.utc)
        tickets = [
            {"repo": "test/repo", "number": 1, "title": "No revisit line"}
        ]
        ta.write_revisit_state(tickets, path, now)
        assert path.exists()
        data = json.loads(path.read_text())
        assert data["generated_at"] == "2026-10-10T12:00:00+00:00"
        assert len(data["without_revisit"]) == 1
        assert data["without_revisit"][0]["number"] == 1


def test_write_revisit_state_truncate():
    """Truncate large lists at 50"""
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "revisit.json"
        now = datetime(2026, 10, 10, 12, 0, 0, tzinfo=timezone.utc)
        tickets = [
            {"repo": "test/repo", "number": i, "title": f"No revisit {i}"}
            for i in range(100)
        ]
        ta.write_revisit_state(tickets, path, now)
        data = json.loads(path.read_text())
        assert len(data["without_revisit"]) == 50  # truncated


def test_write_revisit_state_unwritable():
    """Unwritable path: no error"""
    path = Path("/nonexistent/path/revisit.json")
    now = datetime(2026, 10, 10, 12, 0, 0, tzinfo=timezone.utc)
    tickets = [{"repo": "test/repo", "number": 1, "title": "No revisit"}]
    # Should not raise
    ta.write_revisit_state(tickets, path, now)


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))


# ── the whole pass, not just the planner (P6, 2026-10-21) ──────────────────
# A date-only "Revisit by:" line gives condition None, and run() read it with .get("condition", "").startswith,
# which crashed every pass for 12 days ("'NoneType' object has no attribute 'startswith'", 270 of 273 scans).
# The planner tests above never went through run(), so they could not see it.

class _Gh:
    def __init__(self, hold_comments, states=None):
        self.hold_comments, self.states, self.calls = hold_comments, states or {}, []

    def __call__(self, args):
        self.calls.append(args)
        if args[:2] == ["issue", "list"] and "--label" in args:
            return json.dumps([{"number": n, "comments": c} for n, c in self.hold_comments.items()])
        if args[:2] == ["issue", "view"]:
            n = int(args[2])
            if n not in self.states:
                raise RuntimeError("not found")
            return json.dumps({"state": self.states[n]})
        return ""


def _held(n, title="On hold"):
    return {"number": n, "title": title, "labels": [{"name": "hold"}], "body": "", "createdAt": "2026-10-01T00:00:00Z",
            "updatedAt": "2026-10-01T00:00:00Z"}


def _run(tmp_path, issues, gh, now=datetime(2026, 10, 21, tzinfo=timezone.utc)):
    snap = {"G-Eskayo/marvin": {"issues": issues, "prs": []}}
    return ta.run(snap, gh, {"mode": "act", "agents": {"revisit": "act"}}, now, audit_path=tmp_path / "audit.jsonl",
                  proposals_path=tmp_path / "proposals.json", executable={"G-Eskayo/marvin"},
                  project_rules={"projects": {}}, revisit_state_path=tmp_path / "revisit.json")


def test_a_date_only_revisit_line_does_not_crash_the_pass(tmp_path):
    gh = _Gh({1: [{"body": "Revisit by: 2026-10-15", "createdAt": "2026-10-01T10:00:00Z"}]})
    res = _run(tmp_path, [_held(1)], gh)
    assert res["by_agent"]["revisit"]["planned"] == 3 and res["failed"] == 0   # remove hold, add needs-triage, comment
    assert not any(c[:2] == ["issue", "view"] for c in gh.calls)   # no condition, nothing to look up


def test_a_ticket_condition_is_looked_up_once_and_a_closed_one_releases_the_hold(tmp_path):
    gh = _Gh({1: [{"body": "Revisit by: 2026-12-31 — #412 merges", "createdAt": "2026-10-01T10:00:00Z"}]}, {412: "CLOSED"})
    res = _run(tmp_path, [_held(1)], gh)
    assert [c[2] for c in gh.calls if c[:2] == ["issue", "view"]] == ["412"]
    assert res["by_agent"]["revisit"]["planned"] == 3 and res["failed"] == 0


def test_odd_conditions_never_crash_and_never_look_anything_up(tmp_path):
    odd = ["#", "#abc", "  #12x", "after the demo", "", "#" + "9" * 400]
    gh = _Gh({i + 1: [{"body": f"Revisit by: 2026-12-31 — {c}", "createdAt": "2026-10-01T10:00:00Z"}] for i, c in enumerate(odd)})
    res = _run(tmp_path, [_held(i + 1) for i in range(len(odd))], gh)
    assert res["failed"] == 0
    looked_up = [c[2] for c in gh.calls if c[:2] == ["issue", "view"]]
    assert looked_up == ["9" * 400]   # a well-formed (if absurd) ref is looked up, and its failure is tolerated


def test_ref_number_parses_only_a_leading_ticket_ref():
    assert ta._ref_number("#412 merges") == 412
    assert ta._ref_number("#7") == 7
    for bad in (None, "", "#", "#abc", "#12x", "412", "see #5", 5, {"x": 1}):
        assert ta._ref_number(bad) is None, bad


def test_plan_revisit_releases_before_the_date_when_the_condition_ticket_closed():
    now = datetime(2026, 10, 10, tzinfo=timezone.utc)   # well before the date
    issues = [{"number": 1, "title": "On hold", "labels": [{"name": "hold"}]}]
    hold_comments = {1: [{"body": "Revisit by: 2026-12-31 — #2 closes", "createdAt": "2026-10-01T10:00:00Z"}]}
    assert len(ta.plan_revisit("t/r", issues, hold_comments, {2: {"state": "CLOSED"}}, now)) == 3
    assert ta.plan_revisit("t/r", issues, hold_comments, {2: {"state": "OPEN"}}, now) == []
    assert ta.plan_revisit("t/r", issues, hold_comments, {}, now) == []   # unknown state: never guess
