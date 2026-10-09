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
    assert len(result) == 0  # not due yet


def test_plan_revisit_no_revisit_line():
    """Held ticket with no revisit line: skipped silently"""
    now = datetime(2026, 10, 20, tzinfo=timezone.utc)
    issues = [
        {"number": 1, "title": "On hold", "labels": [{"name": "hold"}]}
    ]
    hold_comments = {1: []}  # no revisit line
    result = ta.plan_revisit("test/repo", issues, hold_comments, {}, now)
    assert len(result) == 0  # Health will flag this


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
    assert len(result) == 0  # pinned, never touched


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
