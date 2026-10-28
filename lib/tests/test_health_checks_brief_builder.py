"""Tests for health_checks.py's check_brief_builder() function. Run via:
    ~/.agents/venv/bin/python -m pytest lib/tests/test_health_checks_brief_builder.py -v
"""
from datetime import datetime

import health_checks as hc


def test_check_brief_builder_green_waiting_before_primary_deadline(monkeypatch):
    """check_brief_builder() shows green while waiting for primary to build."""
    # Before primary deadline (09:15 local): primary hasn't reached deadline yet
    # Use local time: before 09:15
    now = datetime(2026, 10, 25, 8, 0).astimezone()
    monkeypatch.setattr("health_checks.morning_brief.builder_of", lambda x: None)

    result = hc.check_brief_builder(now)
    assert result["severity"] == "green"
    assert "primary has until 10:15 to build" in result["detail"]


def test_check_brief_builder_yellow_during_primary_grace(monkeypatch):
    """check_brief_builder() shows yellow during primary grace period."""
    # After primary deadline (09:15 + 60min grace = 10:15), but before fallback deadline
    # Use local time: somewhere between 10:15 and 11:15
    now = datetime(2026, 10, 25, 10, 45).astimezone()
    monkeypatch.setattr("health_checks.morning_brief.builder_of", lambda x: None)

    result = hc.check_brief_builder(now)
    assert result["severity"] == "yellow"
    assert "primary missed deadline; fallback building" in result["detail"]


def test_check_brief_builder_red_after_both_deadlines(monkeypatch):
    """check_brief_builder() shows red after both primary and fallback deadlines pass."""
    # After both deadlines: 09:15 + 2*60min grace = 11:15
    # Use local time: after 11:15
    now = datetime(2026, 10, 25, 11, 30).astimezone()
    monkeypatch.setattr("health_checks.morning_brief.builder_of", lambda x: None)

    result = hc.check_brief_builder(now)
    assert result["severity"] == "red"
    assert "primary missed 10:15 deadline" in result["detail"]
    assert "fallback missed 11:15" in result["detail"]


def test_check_brief_builder_green_when_built(monkeypatch):
    """check_brief_builder() shows green when brief was built by a machine."""
    now = datetime(2026, 10, 25, 12, 0).astimezone()
    monkeypatch.setattr("health_checks.morning_brief.builder_of", lambda x: "mac-mini-1")

    result = hc.check_brief_builder(now)
    assert result["severity"] == "green"
    assert "mac-mini-1" in result["detail"]
    assert "built by mac-mini-1" in result["detail"]
