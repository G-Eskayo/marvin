"""Tests for label_catalog.py. Run via:
    ~/.agents/venv/bin/python -m pytest lib/tests/test_label_catalog.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

LIB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LIB))

import label_catalog as lc  # noqa: E402


# ── Catalog data tests ──────────────────────────────────────────────────────

def test_core_triage_labels_exist():
    expected = {"needs-triage", "needs-info", "ready-for-agent", "ready-for-human", "wontfix"}
    assert set(lc.CORE.keys()) == expected


def test_core_labels_have_colors_and_descriptions():
    for name, data in lc.CORE.items():
        assert "color" in data
        assert "description" in data
        assert isinstance(data["color"], str)
        assert isinstance(data["description"], str)


def test_fixed_labels_are_strings():
    assert isinstance(lc.FIXED, set)
    assert all(isinstance(label, str) for label in lc.FIXED)
    assert "needs-reengagement" in lc.FIXED
    assert "owner-decisions" in lc.FIXED
    assert "bug" in lc.FIXED


# ── is_catalogued tests ─────────────────────────────────────────────────────

def test_core_labels_are_catalogued():
    assert lc.is_catalogued("needs-triage")
    assert lc.is_catalogued("ready-for-agent")
    assert lc.is_catalogued("wontfix")


def test_fixed_labels_are_catalogued():
    assert lc.is_catalogued("needs-reengagement")
    assert lc.is_catalogued("bug")
    assert lc.is_catalogued("priority:p0")


def test_unknown_labels_are_not_catalogued():
    assert not lc.is_catalogued("random-label")
    assert not lc.is_catalogued("bad-label-name")


def test_project_labels_are_catalogued_when_in_registry():
    projects = {"marvin", "portfolio-website-updater"}
    assert lc.is_catalogued("project:marvin", project_tags=projects)
    assert lc.is_catalogued("project:portfolio-website-updater", project_tags=projects)
    assert not lc.is_catalogued("project:nonexistent", project_tags=projects)


def test_claimed_labels_are_catalogued_when_in_registry():
    devices = {"mac-mini", "macbook"}
    assert lc.is_catalogued("claimed:mac-mini", devices=devices)
    assert lc.is_catalogued("claimed:macbook", devices=devices)
    assert not lc.is_catalogued("claimed:nonexistent", devices=devices)


# ── parse_label_call tests ──────────────────────────────────────────────────

def test_parse_issue_create_with_label():
    argv = ["issue", "create", "-l", "bug", "--title", "test"]
    result = lc.parse_label_call(argv)
    assert result is not None
    assert result["cmd"] == "issue"
    assert result["add"] == ["bug"]


def test_parse_pr_create_with_add_label():
    argv = ["pr", "create", "--add-label", "bug,needs-info", "--base", "main"]
    result = lc.parse_label_call(argv)
    assert result is not None
    assert result["cmd"] == "pr"
    assert set(result["add"]) == {"bug", "needs-info"}


def test_parse_pr_edit_with_remove_label():
    argv = ["pr", "edit", "123", "--remove-label", "needs-triage"]
    result = lc.parse_label_call(argv)
    assert result is not None
    assert result["cmd"] == "pr"
    assert result["remove"] == ["needs-triage"]


def test_parse_issue_create_with_repo():
    argv = ["issue", "create", "--repo", "owner/repo", "-l", "bug"]
    result = lc.parse_label_call(argv)
    assert result is not None
    assert result["repo"] == "owner/repo"


def test_parse_issue_create_with_long_label():
    argv = ["issue", "create", "--label", "bug", "--title", "test"]
    result = lc.parse_label_call(argv)
    assert result is not None
    assert result["cmd"] == "issue"
    assert result["add"] == ["bug"]


def test_parse_issue_create_with_long_label_equals():
    argv = ["issue", "create", "--label=bug,needs-info", "--title", "test"]
    result = lc.parse_label_call(argv)
    assert result is not None
    assert set(result["add"]) == {"bug", "needs-info"}


def test_parse_non_label_call_returns_none():
    assert lc.parse_label_call(["issue", "list"]) is None
    assert lc.parse_label_call(["pr", "view", "123"]) is None
    assert lc.parse_label_call(["api", "repos/owner/repo"]) is None


def test_parse_with_help_returns_none():
    assert lc.parse_label_call(["issue", "create", "--help", "-l", "bug"]) is None
    assert lc.parse_label_call(["pr", "edit", "123", "-h"]) is None


def test_parse_comma_separated_labels():
    argv = ["issue", "create", "--add-label=bug,regression,needs-info"]
    result = lc.parse_label_call(argv)
    assert set(result["add"]) == {"bug", "regression", "needs-info"}


def test_parse_target_positional_arg():
    argv = ["pr", "edit", "123", "-l", "bug"]
    result = lc.parse_label_call(argv)
    assert result["target"] == "123"


# ── missing_label tests ─────────────────────────────────────────────────────

def test_missing_label_extracts_name():
    stderr = "Error: label 'bug' not found"
    assert lc.missing_label(stderr) == "bug"


def test_missing_label_case_insensitive():
    stderr = "ERROR: Label 'needs-triage' Not Found"
    assert lc.missing_label(stderr) == "needs-triage"


def test_missing_label_ignores_other_errors():
    assert lc.missing_label("Error: assignee 'user' not found") is None
    assert lc.missing_label("Error: milestone 'v1.0' not found") is None
    assert lc.missing_label("unknown error") is None


def test_missing_label_matches_could_not_add_format():
    stderr = "Error: could not add label: 'bug' not found"
    assert lc.missing_label(stderr) == "bug"


def test_missing_label_matches_could_not_remove_format():
    stderr = "Error: could not remove label: 'needs-triage' not found"
    assert lc.missing_label(stderr) == "needs-triage"


def test_missing_label_with_error_prefix():
    # Real gh output includes "Error: " prefix
    stderr = "Error: could not add label: 'bug' not found"
    assert lc.missing_label(stderr) == "bug"


# ── heal_step tests ─────────────────────────────────────────────────────────

def test_heal_remove_missing_label():
    call = {"cmd": "pr", "repo": "owner/repo", "target": None, "add": [], "remove": ["nonexistent"]}
    result = lc.heal_step(call, "nonexistent", lambda n, r: None)
    assert result["action"] == "retry"
    assert result["argv_patch"] == ["--remove-label", "nonexistent"]


def test_heal_add_catalogued_label():
    call = {"cmd": "issue", "repo": "owner/repo", "target": None, "add": ["bug"], "remove": []}
    result = lc.heal_step(call, "bug", lambda n, r: None)
    assert result["action"] == "create-then-retry"
    assert result["argv_patch"] is None


def test_heal_add_uncatalogued_label():
    call = {"cmd": "pr", "repo": "owner/repo", "target": None, "add": ["random-label"], "remove": []}
    result = lc.heal_step(call, "random-label", lambda n, r: None)
    assert result["action"] == "stop"
    assert "not catalogued" in result["hint"].lower()


def test_heal_missing_label_not_in_call():
    call = {"cmd": "issue", "repo": "owner/repo", "target": None, "add": ["bug"], "remove": []}
    result = lc.heal_step(call, "other-label", lambda n, r: None)
    assert result["action"] == "stop"


def test_heal_respects_project_tags():
    call = {"cmd": "issue", "repo": "owner/repo", "target": None, "add": ["project:marvin"], "remove": []}
    result = lc.heal_step(call, "project:marvin", lambda n, r: None, project_tags={"marvin"})
    assert result["action"] == "create-then-retry"


def test_heal_respects_device_names():
    call = {"cmd": "pr", "repo": "owner/repo", "target": None, "add": ["claimed:macbook"], "remove": []}
    result = lc.heal_step(call, "claimed:macbook", lambda n, r: None, devices={"macbook"})
    assert result["action"] == "create-then-retry"


# ── resolve_repo tests ──────────────────────────────────────────────────────

def test_resolve_repo_from_repo_flag():
    call = {"cmd": "issue", "repo": "owner/repo", "target": None, "add": [], "remove": []}
    result = lc.resolve_repo(call, {})
    assert result == "owner/repo"


def test_resolve_repo_from_target_url():
    call = {"cmd": "pr", "repo": None, "target": "https://github.com/owner/repo/pull/123", "add": [], "remove": []}
    result = lc.resolve_repo(call, {})
    assert result == "owner/repo"


def test_resolve_repo_from_env():
    call = {"cmd": "issue", "repo": None, "target": None, "add": [], "remove": []}
    result = lc.resolve_repo(call, {"GH_REPO": "owner/repo"})
    assert result == "owner/repo"


def test_resolve_repo_falls_back_to_repo_here(monkeypatch):
    # When no explicit source (--repo, target URL, or GH_REPO), falls back to current git repo via pr_ticket_check.repo_here()
    # Mock the imported pr_ticket_check module to return a fixed repo
    import sys
    from unittest.mock import MagicMock

    mock_pr_ticket_check = MagicMock()
    mock_pr_ticket_check.repo_here.return_value = "owner/repo"
    monkeypatch.setitem(sys.modules, "pr_ticket_check", mock_pr_ticket_check)

    call = {"cmd": "issue", "repo": None, "target": None, "add": [], "remove": []}
    result = lc.resolve_repo(call, {})
    assert result == "owner/repo"
