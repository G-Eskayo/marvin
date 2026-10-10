#!/usr/bin/env python3
"""Tests for revisit parsing: parse_revisit_comment, latest_revisit, is_revisit_due.
Mirrors dashboard/test/revisit.test.js test cases."""
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import ticket_policy as pol  # noqa: E402


def test_parse_revisit_comment_date_only():
    """Revisit by: YYYY-MM-DD"""
    c = {"body": "Revisit by: 2026-10-15"}
    result = pol.parse_revisit_comment(c.get("body"))
    assert result == {"date": "2026-10-15", "condition": None}


def test_parse_revisit_comment_with_dash():
    """Revisit by: YYYY-MM-DD - condition text"""
    c = {"body": "Revisit by: 2026-10-15 - more work needed"}
    result = pol.parse_revisit_comment(c.get("body"))
    assert result == {"date": "2026-10-15", "condition": "more work needed"}


def test_parse_revisit_comment_with_em_dash():
    """Revisit by: YYYY-MM-DD — condition text"""
    c = {"body": "Revisit by: 2026-10-15 — pending review from eng"}
    result = pol.parse_revisit_comment(c.get("body"))
    assert result == {"date": "2026-10-15", "condition": "pending review from eng"}


def test_parse_revisit_comment_case_insensitive():
    """Case-insensitive match"""
    c = {"body": "REVISIT BY: 2026-10-15"}
    result = pol.parse_revisit_comment(c.get("body"))
    assert result == {"date": "2026-10-15", "condition": None}


def test_parse_revisit_comment_with_ref():
    """Condition is a ticket reference #N"""
    c = {"body": "Revisit by: 2026-10-15 — #123 closes"}
    result = pol.parse_revisit_comment(c.get("body"))
    assert result == {"date": "2026-10-15", "condition": "#123 closes"}


def test_parse_revisit_comment_no_match():
    """No revisit line"""
    c = {"body": "This is a regular comment"}
    result = pol.parse_revisit_comment(c.get("body"))
    assert result is None


def test_parse_revisit_comment_malformed_date():
    """Invalid date format"""
    c = {"body": "Revisit by: 2026-13-45"}
    result = pol.parse_revisit_comment(c.get("body"))
    assert result is None


def test_parse_revisit_comment_missing_body():
    """Comment without body"""
    result = pol.parse_revisit_comment(None)
    assert result is None


def test_parse_revisit_comment_extra_whitespace():
    """Leading/trailing whitespace in condition"""
    c = {"body": "Revisit by: 2026-10-15 —   lots of space   "}
    result = pol.parse_revisit_comment(c.get("body"))
    assert result == {"date": "2026-10-15", "condition": "lots of space"}


def test_latest_revisit_single():
    """One comment with revisit"""
    comments = [
        {"body": "Revisit by: 2026-10-15", "createdAt": "2026-10-01T10:00:00Z"}
    ]
    result = pol.latest_revisit(comments)
    assert result == {"date": "2026-10-15", "condition": None}


def test_latest_revisit_multiple_newest_wins():
    """Multiple revisits: newest by createdAt wins"""
    comments = [
        {"body": "Revisit by: 2026-10-10", "createdAt": "2026-10-01T10:00:00Z"},
        {"body": "Revisit by: 2026-10-20", "createdAt": "2026-10-05T10:00:00Z"},
    ]
    result = pol.latest_revisit(comments)
    assert result == {"date": "2026-10-20", "condition": None}


def test_latest_revisit_skip_non_matching():
    """Mixed: only revisit comments count"""
    comments = [
        {"body": "Just a comment", "createdAt": "2026-10-01T10:00:00Z"},
        {"body": "Revisit by: 2026-10-15", "createdAt": "2026-10-05T10:00:00Z"},
    ]
    result = pol.latest_revisit(comments)
    assert result == {"date": "2026-10-15", "condition": None}


def test_latest_revisit_empty():
    """Empty comment list"""
    result = pol.latest_revisit([])
    assert result is None


def test_latest_revisit_all_malformed():
    """All comments have malformed dates"""
    comments = [
        {"body": "Revisit by: 2026-13-45", "createdAt": "invalid"},
    ]
    result = pol.latest_revisit(comments)
    assert result is None


def test_latest_revisit_valid_date_preferred():
    """Valid createdAt preferred over invalid one"""
    comments = [
        {"body": "Revisit by: 2026-10-15", "createdAt": "invalid"},
        {"body": "Revisit by: 2026-10-20", "createdAt": "2026-10-05T10:00:00Z"},
    ]
    result = pol.latest_revisit(comments)
    assert result == {"date": "2026-10-20", "condition": None}


def test_latest_revisit_both_valid():
    """Two valid createdAt: newest wins"""
    comments = [
        {"body": "Revisit by: 2026-10-10", "createdAt": "2026-10-01T10:00:00Z"},
        {"body": "Revisit by: 2026-10-20", "createdAt": "2026-10-05T10:00:00Z"},
    ]
    result = pol.latest_revisit(comments)
    assert result == {"date": "2026-10-20", "condition": None}


def test_latest_revisit_non_array():
    """Not a list"""
    result = pol.latest_revisit("not a list")
    assert result is None


def test_latest_revisit_large_list():
    """Many comments, newest still wins"""
    comments = [
        {"body": f"Comment {i}", "createdAt": f"2026-10-0{i:02d}T10:00:00Z"} for i in range(1, 10)
    ] + [
        {"body": "Revisit by: 2026-10-15", "createdAt": "2026-10-05T10:00:00Z"},
        {"body": "Revisit by: 2026-10-25", "createdAt": "2026-10-10T10:00:00Z"},
    ]
    result = pol.latest_revisit(comments)
    assert result == {"date": "2026-10-25", "condition": None}


def test_is_revisit_due_past_date():
    """Date has passed"""
    now = datetime(2026, 10, 20, tzinfo=timezone.utc)
    revisit = {"date": "2026-10-15", "condition": None}
    assert pol.is_revisit_due(revisit, now) is True


def test_is_revisit_due_today():
    """Today is the date"""
    now = datetime(2026, 10, 15, 12, 0, 0, tzinfo=timezone.utc)
    revisit = {"date": "2026-10-15", "condition": None}
    assert pol.is_revisit_due(revisit, now) is True


def test_is_revisit_due_future_date():
    """Date is in the future"""
    now = datetime(2026, 10, 10, tzinfo=timezone.utc)
    revisit = {"date": "2026-10-15", "condition": None}
    assert pol.is_revisit_due(revisit, now) is False


def test_is_revisit_due_ref_open():
    """Condition #N exists but is open"""
    now = datetime(2026, 10, 10, tzinfo=timezone.utc)
    revisit = {"date": "2026-10-25", "condition": "#123"}
    ref_state = {123: {"state": "OPEN"}}
    assert pol.is_revisit_due(revisit, now, ref_state) is False


def test_is_revisit_due_ref_closed():
    """Condition #N has closed"""
    now = datetime(2026, 10, 10, tzinfo=timezone.utc)
    revisit = {"date": "2026-10-25", "condition": "#123"}
    ref_state = {123: {"state": "CLOSED"}}
    assert pol.is_revisit_due(revisit, now, ref_state) is True


def test_is_revisit_due_no_revisit():
    """No revisit dict"""
    now = datetime(2026, 10, 20, tzinfo=timezone.utc)
    assert pol.is_revisit_due(None, now) is False


def test_is_revisit_due_empty_dict():
    """Empty revisit dict"""
    now = datetime(2026, 10, 20, tzinfo=timezone.utc)
    assert pol.is_revisit_due({}, now) is False


def test_is_revisit_due_malformed_date():
    """Revisit has invalid date"""
    now = datetime(2026, 10, 20, tzinfo=timezone.utc)
    revisit = {"date": "invalid", "condition": None}
    assert pol.is_revisit_due(revisit, now) is False


def test_is_revisit_due_ref_without_state():
    """Condition ref not in ref_states"""
    now = datetime(2026, 10, 10, tzinfo=timezone.utc)
    revisit = {"date": "2026-10-25", "condition": "#999"}
    ref_state = {}
    assert pol.is_revisit_due(revisit, now, ref_state) is False


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
