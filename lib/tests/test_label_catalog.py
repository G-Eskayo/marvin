"""Tests for label_catalog.py. Run via:
    ~/.agents/venv/bin/python -m pytest lib/tests/test_label_catalog.py -v
"""
from __future__ import annotations
import json
import sys
import subprocess
from pathlib import Path

LIB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LIB))

import label_catalog as lc  # noqa: E402


# ── Catalog constants and lookups ──────────────────────────────────────

def test_fixed_is_dict_of_label_info():
    """FIXED is a dict with color and description per label."""
    assert isinstance(lc.FIXED, dict)
    assert "bug" in lc.FIXED
    assert lc.FIXED["bug"]["color"] == "d73a4a"
    assert "Bug" in lc.FIXED["bug"]["description"]


def test_core_is_frozenset():
    """CORE is a frozenset containing key labels."""
    assert isinstance(lc.CORE, frozenset)
    assert "bug" in lc.CORE
    assert "needs-triage" in lc.CORE


def test_lookup_finds_catalogued_labels():
    """lookup() returns dict with color and description for catalogued labels."""
    result = lc.lookup("ready-for-agent")
    assert result is not None
    assert isinstance(result, dict)
    assert result["color"] == "90ee90"
    assert "Ready for agent" in result["description"]


def test_lookup_finds_bug():
    """lookup() finds bug label."""
    result = lc.lookup("bug")
    assert result is not None
    assert result["color"] == "d73a4a"


def test_lookup_returns_none_for_unknown_label():
    """lookup() returns None for labels not in FIXED, project:*, or claimed:*."""
    assert lc.lookup("nonexistent-label-xyz") is None


def test_lookup_handles_project_id_in_known_ids():
    """lookup() returns format for project:<id> when id is known."""
    result = lc.lookup("project:marvin")
    assert result is not None
    assert result["color"] == "c5def5"
    assert "marvin" in result["description"]


def test_lookup_handles_project_id_not_known():
    """lookup() returns None for project:<id> when id is not catalogued."""
    result = lc.lookup("project:unknown-project-xyz")
    assert result is None


def test_lookup_handles_claimed_family():
    """lookup() returns format for claimed:<machine> for any machine."""
    result = lc.lookup("claimed:mac-mini")
    assert result is not None
    assert result["color"] == "ededed"
    assert "mac-mini" in result["description"]


def test_all_triage_labels_are_catalogued():
    """lookup() finds all 5 triage labels."""
    for label in lc.TRIAGE_LABELS:
        assert lc.lookup(label) is not None, f"Triage label {label} not found"


# ── Project IDs from registry ──────────────────────────────────────────

def test_known_project_ids_always_includes_marvin():
    """known_project_ids() always includes "marvin" as fallback."""
    result = lc.known_project_ids(Path("/nonexistent/path.json"))
    assert "marvin" in result


def test_known_project_ids_returns_set():
    """known_project_ids() returns a set of strings."""
    result = lc.known_project_ids(Path("/nonexistent.json"))
    assert isinstance(result, set)
    assert all(isinstance(id, str) for id in result)


def test_known_project_ids_extracts_repos_from_config(tmp_path):
    """known_project_ids() reads project IDs from config/project_tags.json format."""
    config = tmp_path / "project_tags.json"
    config.write_text(json.dumps({
        "projects": {
            "seal-speak": {},
            "other-project": {},
        }
    }))
    result = lc.known_project_ids(registry=config)
    # Always includes marvin
    assert "marvin" in result
    # Also includes projects from the config
    assert "seal-speak" in result
    assert "other-project" in result


# ── Label call parsing ────────────────────────────────────────────────

def test_label_call_returns_none_for_non_edit_commands():
    """label_call() returns None for non-create/edit commands."""
    assert lc.label_call(["issue", "list"]) is None
    assert lc.label_call(["pr", "view"]) is None
    assert lc.label_call(["api", "repos/owner/repo"]) is None


def test_label_call_parses_add_label():
    """label_call() parses --add-label for issue/pr edit."""
    result = lc.label_call(["issue", "edit", "123", "--add-label", "bug,enhancement"])
    assert result is not None
    assert result["cmd"] == "issue"
    assert "bug" in result["add"]
    assert "enhancement" in result["add"]


def test_label_call_parses_add_label_equals():
    """label_call() parses --add-label=a,b format."""
    result = lc.label_call(["pr", "edit", "456", "--add-label=bug"])
    assert result is not None
    assert result["cmd"] == "pr"
    assert "bug" in result["add"]


def test_label_call_parses_remove_label():
    """label_call() parses --remove-label."""
    result = lc.label_call(["issue", "edit", "123", "--remove-label", "blocked"])
    assert result is not None
    assert "blocked" in result["remove"]


def test_label_call_parses_label_flag():
    """label_call() parses --label (exact set, treated as add)."""
    result = lc.label_call(["issue", "edit", "789", "--label", "bug,ready-for-agent"])
    assert result is not None
    assert "bug" in result["add"]
    assert "ready-for-agent" in result["add"]


def test_label_call_multiple_add_labels():
    """label_call() handles multiple --add-label flags."""
    result = lc.label_call(["pr", "edit", "456", "--add-label", "bug", "--add-label", "enhancement"])
    assert result is not None
    assert "bug" in result["add"]
    assert "enhancement" in result["add"]


def test_label_call_add_and_remove():
    """label_call() handles both --add-label and --remove-label."""
    result = lc.label_call(["issue", "edit", "123", "--add-label", "bug", "--remove-label", "blocked"])
    assert result is not None
    assert "bug" in result["add"]
    assert "blocked" in result["remove"]


def test_label_call_skips_empty_labels():
    """label_call() skips empty strings from comma-separated labels."""
    result = lc.label_call(["issue", "edit", "123", "--add-label=bug,,enhancement"])
    assert result is not None
    assert "bug" in result["add"]
    assert "enhancement" in result["add"]
    assert "" not in result["add"]


def test_label_call_returns_none_when_no_label_flags():
    """label_call() returns None if no label flags present."""
    assert lc.label_call(["issue", "edit", "123"]) is None
    assert lc.label_call(["pr", "edit", "456", "--title", "foo"]) is None


# ── Label validation ──────────────────────────────────────────────────

def test_failed_label_returns_none_for_no_error():
    """failed_label() returns None when stderr has no 'not found'."""
    result = lc.failed_label("some other error", {"add": ["bug"], "remove": []})
    assert result is None


def test_failed_label_returns_none_if_label_not_in_call():
    """failed_label() returns None if error mentions label not in this call."""
    result = lc.failed_label("'alice' not found", {"add": ["bug"], "remove": []})
    assert result is None


def test_failed_label_identifies_missing_add_label():
    """failed_label() identifies when an --add-label value is missing."""
    result = lc.failed_label("'unknown-label' not found", {"add": ["unknown-label"], "remove": []})
    assert result == ("unknown-label", True)


def test_failed_label_identifies_missing_remove_label():
    """failed_label() identifies when a --remove-label value is missing."""
    result = lc.failed_label("'blocked' not found", {"add": [], "remove": ["blocked"]})
    assert result == ("blocked", False)


def test_failed_label_case_sensitive():
    """failed_label() is case-sensitive when matching against call."""
    result = lc.failed_label("'Bug' not found", {"add": ["bug"], "remove": []})
    assert result is None


# ── Label list manipulation with argv ──────────────────────────────────

def test_without_label_removes_from_remove_flag():
    """without_label() removes label from --remove-label values."""
    argv = ["issue", "edit", "123", "--remove-label", "bug,blocked"]
    result = lc.without_label(argv, "blocked")
    # Should have --remove-label flag
    assert "--remove-label" in result
    # Should have bug in the labels
    idx_flag = result.index("--remove-label")
    assert idx_flag + 1 < len(result)
    # Next item after flag should contain "bug" but not "blocked"
    assert "bug" in result[idx_flag + 1]
    assert "blocked" not in result[idx_flag + 1]


def test_without_label_with_equals():
    """without_label() handles --remove-label=a,b format."""
    argv = ["issue", "edit", "123", "--remove-label=bug,blocked,enhancement"]
    result = lc.without_label(argv, "blocked")
    # bug and enhancement should remain
    assert any(("bug" in arg and "blocked" not in arg) for arg in result if "--remove-label" in arg)


def test_without_label_removes_flag_if_empty():
    """without_label() removes --remove-label flag if no labels remain."""
    argv = ["issue", "edit", "123", "--remove-label", "blocked"]
    result = lc.without_label(argv, "blocked")
    assert "--remove-label" not in result


def test_without_label_does_not_touch_add():
    """without_label() does not modify --add-label flags."""
    argv = ["issue", "edit", "123", "--add-label", "bug", "--remove-label", "blocked"]
    result = lc.without_label(argv, "bug")
    # --add-label and bug should still be in result (unchanged)
    assert "--add-label" in result
    idx_add = result.index("--add-label")
    assert idx_add + 1 < len(result)
    assert result[idx_add + 1] == "bug"


def test_without_label_preserves_order():
    """without_label() preserves argv order."""
    argv = ["issue", "edit", "123", "--title", "foo", "--remove-label", "blocked"]
    result = lc.without_label(argv, "other")
    # Order should be preserved
    idx_title = next(i for i, arg in enumerate(result) if "--title" in arg)
    idx_remove = next(i for i, arg in enumerate(result) if "--remove-label" in arg)
    assert idx_title < idx_remove


# ── Repo detection ────────────────────────────────────────────────────

def test_call_repo_prefers_repo_flag(tmp_path):
    """call_repo() uses --repo flag when present."""
    result = lc.call_repo(["issue", "edit", "123", "--repo", "owner/repo"], {})
    assert result == "owner/repo"


def test_call_repo_recognizes_short_flag(tmp_path):
    """call_repo() recognizes -R flag."""
    result = lc.call_repo(["issue", "edit", "123", "-R", "owner/repo"], {})
    assert result == "owner/repo"


def test_call_repo_parses_equals_format(tmp_path):
    """call_repo() parses --repo=owner/repo format."""
    result = lc.call_repo(["issue", "edit", "123", "--repo=owner/repo"], {})
    assert result == "owner/repo"


def test_call_repo_checks_gh_repo_env(tmp_path):
    """call_repo() checks GH_REPO env var."""
    result = lc.call_repo(["issue", "edit", "123"], {"GH_REPO": "env/repo"})
    assert result == "env/repo"


def test_call_repo_from_git(tmp_path):
    """call_repo() extracts repo from git origin."""
    subprocess.run(["git", "init"], cwd=str(tmp_path), capture_output=True, check=True)
    subprocess.run(["git", "remote", "add", "origin", "https://github.com/owner/repo.git"],
                   cwd=str(tmp_path), capture_output=True, check=True)
    result = lc.call_repo([], {}, cwd=str(tmp_path))
    assert result == "owner/repo"
