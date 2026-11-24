"""Fixtures for morning brief tests."""
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

import morning_brief as mb


@pytest.fixture
def mock_mb_sources(monkeypatch):
    """Mock all helper functions used by item builders."""
    # Mock _open_prs
    monkeypatch.setattr(mb, "_open_prs", lambda: [
        {"number": 308, "title": "MARVIN launcher", "repo": "marvin", "waiting_on_marvin": False, "question": False},
    ])

    # Mock _red_checks
    monkeypatch.setattr(mb, "_red_checks", lambda: [
        {"label": "Missed purpose", "detail": "#277 Allow read-only tools: missed"},
    ])

    # Mock _human_tickets
    monkeypatch.setattr(mb, "_human_tickets", lambda: [
        {"number": 14, "title": "Enroll in the Apple developer program", "repo": "marvin"},
    ])

    # Mock _deadlines
    monkeypatch.setattr(mb, "_deadlines", lambda now: [
        {"project": "clarity-captions", "date": "2026-10-25", "hard": True},
    ])

    # Mock _top_tickets
    monkeypatch.setattr(mb, "_top_tickets", lambda: [
        {"repo": "clarity-captions", "number": 31, "title": "Live captions view", "priority": "p0"},
    ])

    # Mock _auto_merge_report
    monkeypatch.setattr(mb, "_auto_merge_report", lambda: None)

    # Mock _regressions
    monkeypatch.setattr(mb, "_regressions", lambda now: [])

    # Mock _digest_idea
    monkeypatch.setattr(mb, "_digest_idea", lambda now: "Wire the outcome check into the brief.")

    # Mock _research_idea
    monkeypatch.setattr(mb, "_research_idea", lambda now: "A paper on cheaper planning with smaller models.")
