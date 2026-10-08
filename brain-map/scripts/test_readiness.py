#!/usr/bin/env python3
"""Tests for readiness.py — onboarding plan readiness assessment."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from readiness import project_readiness  # noqa: E402


def test_ok_plan_with_no_missing_pieces():
    plan = {"pieces": {
        "profile": {"state": "ok", "reason": ""},
        "stack": {"state": "ok", "reason": ""},
        "test_command": {"state": "ok", "reason": ""},
    }}
    result = project_readiness(plan)
    assert result == {"ready": True, "gaps": []}


def test_plan_with_missing_pieces():
    plan = {"pieces": {
        "profile": {"state": "ok", "reason": ""},
        "stack": {"state": "missing", "reason": ""},
        "test_command": {"state": "ok", "reason": ""},
        "ci": {"state": "needs-human", "reason": ""},
    }}
    result = project_readiness(plan)
    assert result["ready"] is False
    assert "stack info" in result["gaps"]
    assert "CI" in result["gaps"]
    assert len(result["gaps"]) == 2


def test_none_plan_is_not_ready():
    result = project_readiness(None)
    assert result == {"ready": False, "gaps": ["not onboarded yet"]}


def test_empty_pieces_is_ready():
    plan = {"pieces": {}}
    result = project_readiness(plan)
    assert result == {"ready": True, "gaps": []}


def test_unknown_piece_key_falls_back_to_key_with_underscores_replaced():
    plan = {"pieces": {
        "unknown_piece_name": {"state": "missing", "reason": ""},
    }}
    result = project_readiness(plan)
    assert "unknown piece name" in result["gaps"]


def test_only_missing_and_needs_human_count_as_gaps():
    plan = {"pieces": {
        "profile": {"state": "ok", "reason": ""},
        "stack": {"state": "skipped", "reason": ""},
        "test_command": {"state": "missing", "reason": ""},
    }}
    result = project_readiness(plan)
    assert result["ready"] is False
    assert result["gaps"] == ["a test command"]
