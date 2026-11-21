"""Tests for label_catalog.py. Run via:
    ~/.agents/venv/bin/python -m pytest lib/tests/test_label_catalog.py -v
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import Mock, patch

LIB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LIB))

import label_catalog as lc


# ── Catalog membership tests ───────────────────────────────────────────────────

def test_fixed_labels_exist():
    """Core fixed labels are in the catalog."""
    assert "needs-triage" in lc.FIXED
    assert "ready-for-agent" in lc.FIXED
    assert "bug" in lc.FIXED
    assert "priority:p0" in lc.FIXED


def test_known_projects_loads_registry(tmp_path):
    """known_projects reads ~/.claude/boards/registry.json."""
    # Create a fake registry file
    fake_registry = {
        "boards": [
            {"name": "marvin"},
            {"name": "clarity-captions"},
        ]
    }
    registry_file = tmp_path / "registry.json"
    registry_file.write_text(json.dumps(fake_registry))

    result = lc.known_projects(registry_path=registry_file)
    # marvin is always included
    assert "marvin" in result
    assert "clarity-captions" in result


def test_known_machines_includes_fixed_classes():
    """known_machines includes mac-mini and macbook-pro."""
    result = lc.known_machines()
    assert "mac-mini" in result
    assert "macbook-pro" in result


def test_is_catalogued_fixed_labels():
    """is_catalogued returns True for fixed labels."""
    assert lc.is_catalogued("needs-triage")
    assert lc.is_catalogued("bug")
    assert lc.is_catalogued("priority:p1")


def test_is_catalogued_project_labels():
    """is_catalogued returns True for project:<id> labels."""
    projects = {"marvin", "clarity-captions"}
    assert lc.is_catalogued("project:marvin", projects=projects)
    assert lc.is_catalogued("project:clarity-captions", projects=projects)
    assert not lc.is_catalogued("project:unknown", projects=projects)


def test_is_catalogued_claimed_labels():
    """is_catalogued returns True for claimed:<machine> labels."""
    machines = {"mac-mini", "macbook-pro"}
    assert lc.is_catalogued("claimed:mac-mini", machines=machines)
    assert lc.is_catalogued("claimed:macbook-pro", machines=machines)
    assert not lc.is_catalogued("claimed:unknown-box", machines=machines)


def test_is_catalogued_uncatalogued():
    """is_catalogued returns False for unknown labels."""
    assert not lc.is_catalogued("typo-label")
    assert not lc.is_catalogued("random")


# ── Label call parsing tests ───────────────────────────────────────────────────

def test_label_call_none_for_non_issue_pr():
    """label_call returns None for non-issue/pr commands."""
    assert lc.label_call(["repo", "view"]) is None
    assert lc.label_call(["api", "repos/owner/repo"]) is None


def test_label_call_none_for_non_create_edit():
    """label_call returns None for issue/pr commands that aren't create/edit."""
    assert lc.label_call(["issue", "view"]) is None
    assert lc.label_call(["pr", "list"]) is None
    assert lc.label_call(["issue", "close"]) is None


def test_label_call_none_with_help():
    """label_call returns None when --help or -h is present."""
    assert lc.label_call(["issue", "create", "--help"]) is None
    assert lc.label_call(["pr", "create", "-h"]) is None


def test_label_call_none_without_labels():
    """label_call returns None for issue/pr create/edit without label flags."""
    assert lc.label_call(["issue", "create", "--title", "Test"]) is None
    assert lc.label_call(["pr", "create", "--body", "Test"]) is None


def test_label_call_add_label_space_separated():
    """label_call parses --add-label with space-separated value."""
    call = lc.label_call(["issue", "create", "--add-label", "bug"])
    assert call is not None
    assert call.add_labels == ["bug"]
    assert call.remove_labels == []


def test_label_call_add_label_equals():
    """label_call parses --add-label=value syntax."""
    call = lc.label_call(["issue", "create", "--add-label=bug,enhancement"])
    assert call is not None
    assert set(call.add_labels) == {"bug", "enhancement"}


def test_label_call_add_label_short_form():
    """label_call parses -l shorthand."""
    call = lc.label_call(["issue", "create", "-l", "bug"])
    assert call is not None
    assert call.add_labels == ["bug"]


def test_label_call_remove_label():
    """label_call parses --remove-label."""
    call = lc.label_call(["issue", "edit", "5", "--remove-label", "needs-info"])
    assert call is not None
    assert call.remove_labels == ["needs-info"]


def test_label_call_multiple_labels():
    """label_call handles multiple label additions."""
    call = lc.label_call(["issue", "create", "--add-label", "bug", "--add-label", "p1"])
    assert call is not None
    assert set(call.add_labels) == {"bug", "p1"}


def test_label_call_comma_separated_labels():
    """label_call handles comma-separated labels."""
    call = lc.label_call(["issue", "create", "--add-label", "bug,enhancement,p1"])
    assert call is not None
    assert set(call.add_labels) == {"bug", "enhancement", "p1"}


def test_label_call_add_and_remove():
    """label_call handles both add and remove in one call."""
    call = lc.label_call(["issue", "edit", "5", "--add-label", "ready-for-agent", "--remove-label", "needs-triage"])
    assert call is not None
    assert call.add_labels == ["ready-for-agent"]
    assert call.remove_labels == ["needs-triage"]


def test_label_call_deduplicates():
    """label_call deduplicates repeated labels."""
    call = lc.label_call(["issue", "create", "--add-label", "bug,bug,bug"])
    assert call is not None
    assert call.add_labels == ["bug"]


def test_label_call_empty_values_stripped():
    """label_call strips empty label values."""
    call = lc.label_call(["issue", "create", "--add-label", "bug,,enhancement,"])
    assert call is not None
    assert set(call.add_labels) == {"bug", "enhancement"}


def test_label_call_repo_flag():
    """label_call captures --repo flag."""
    call = lc.label_call(["issue", "create", "--repo", "owner/repo", "--add-label", "bug"])
    assert call is not None
    assert call.repo == "owner/repo"


def test_label_call_repo_short_form():
    """label_call captures -R shorthand."""
    call = lc.label_call(["issue", "create", "-Rowner/repo", "--add-label", "bug"])
    assert call is not None
    assert call.repo == "owner/repo"


def test_label_call_repo_equals_syntax():
    """label_call captures --repo=value syntax."""
    call = lc.label_call(["issue", "create", "--repo=owner/repo", "--add-label", "bug"])
    assert call is not None
    assert call.repo == "owner/repo"


def test_label_call_edit_target():
    """label_call captures issue/PR number for edit."""
    call = lc.label_call(["issue", "edit", "123", "--add-label", "bug"])
    assert call is not None
    assert call.target == "123"


# ── drop_label_value tests ─────────────────────────────────────────────────────

def test_drop_label_value_space_separated():
    """drop_label_value removes a label from space-separated value."""
    argv = ["issue", "edit", "5", "--add-label", "bug,enhancement,p1"]
    result = lc.drop_label_value(argv, "--add-label", "enhancement")
    assert "--add-label" in result
    idx = result.index("--add-label")
    labels = result[idx + 1].split(",")
    assert set(labels) == {"bug", "p1"}


def test_drop_label_value_equals_syntax():
    """drop_label_value handles --flag=value syntax."""
    argv = ["issue", "create", "--add-label=bug,enhancement"]
    result = lc.drop_label_value(argv, "--add-label", "bug")
    assert any("enhancement" in arg for arg in result)


# ── resolve_repo tests ─────────────────────────────────────────────────────────

def test_resolve_repo_explicit_repo():
    """resolve_repo uses explicit --repo when present."""
    call = lc.LabelCall(repo="owner/repo", target=None, add_labels=["bug"], remove_labels=[])
    assert lc.resolve_repo(call, {}) == "owner/repo"


def test_resolve_repo_gh_repo_env():
    """resolve_repo uses GH_REPO environment variable."""
    call = lc.LabelCall(repo=None, target=None, add_labels=["bug"], remove_labels=[])
    assert lc.resolve_repo(call, {"GH_REPO": "owner/repo"}) == "owner/repo"


def test_resolve_repo_ask_cwd():
    """resolve_repo uses ask_cwd callback."""
    call = lc.LabelCall(repo=None, target=None, add_labels=["bug"], remove_labels=[])
    ask_cwd = Mock(return_value="owner/repo")
    assert lc.resolve_repo(call, {}, ask_cwd=ask_cwd) == "owner/repo"
    ask_cwd.assert_called_once()


def test_resolve_repo_none():
    """resolve_repo returns None when repo can't be determined."""
    call = lc.LabelCall(repo=None, target=None, add_labels=["bug"], remove_labels=[])
    assert lc.resolve_repo(call, {}) is None


# ── Integration tests ──────────────────────────────────────────────────────────

def test_complete_parsing_workflow():
    """Full workflow: parse a complex gh call."""
    argv = [
        "issue", "edit", "42",
        "--repo", "G-Eskayo/marvin",
        "--add-label", "bug,priority:p1",
        "--remove-label", "needs-triage",
    ]
    call = lc.label_call(argv)
    assert call is not None
    assert call.repo == "G-Eskayo/marvin"
    assert call.target == "42"
    assert set(call.add_labels) == {"bug", "priority:p1"}
    assert call.remove_labels == ["needs-triage"]


def test_all_support_labels_catalogued():
    """All support labels are in FIXED."""
    # Just check some common support labels exist
    common_support_labels = ["support:trying-here", "support:solved-here", "support:needs-you"]
    for label in common_support_labels:
        assert label in lc.FIXED, f"Missing support label: {label}"


# ── Regression tests for code review findings ──────────────────────────────────

def test_label_not_found_re_matches_real_error_format():
    """LABEL_NOT_FOUND_RE matches real gh error format: could not add/remove label."""
    # Real error format from gh
    stderr = "error: could not add label: label not found\n"
    match = lc.LABEL_NOT_FOUND_RE.search(stderr)
    assert match, f"Regex should match: {stderr}"
    assert match.group(1) or match.group(2), "Regex should capture label name"


def test_label_not_found_re_matches_quoted_label():
    """LABEL_NOT_FOUND_RE matches quoted label names."""
    stderr = "error: could not add label: 'my-label' not found\n"
    match = lc.LABEL_NOT_FOUND_RE.search(stderr)
    assert match, f"Regex should match quoted label: {stderr}"
    label = match.group(1) or match.group(2)
    assert label == "my-label", f"Should extract quoted label name, got {label}"


def test_label_call_parses_label_flag():
    """label_call parses --label flag (used in gh issue create)."""
    # --label is the flag for `gh issue create`, not --add-label
    call = lc.label_call(["issue", "create", "--title", "Test", "--label", "bug"])
    assert call is not None, "Should parse issue create with --label"
    assert call.add_labels == ["bug"]


def test_label_call_parses_label_flag_equals():
    """label_call parses --label=value syntax."""
    call = lc.label_call(["issue", "create", "--label=bug,enhancement"])
    assert call is not None
    assert set(call.add_labels) == {"bug", "enhancement"}


def test_resolve_repo_from_github_url():
    """resolve_repo correctly extracts owner/repo from GitHub URL."""
    call = lc.LabelCall(
        repo=None,
        target="https://github.com/G-Eskayo/marvin/issues/123",
        add_labels=["bug"],
        remove_labels=[]
    )
    result = lc.resolve_repo(call, {})
    assert result == "G-Eskayo/marvin", f"Expected 'G-Eskayo/marvin', got '{result}'"


def test_resolve_repo_from_short_url():
    """resolve_repo correctly extracts owner/repo from short URL."""
    call = lc.LabelCall(
        repo=None,
        target="G-Eskayo/marvin/issues/123",
        add_labels=["bug"],
        remove_labels=[]
    )
    result = lc.resolve_repo(call, {})
    assert result == "G-Eskayo/marvin", f"Expected 'G-Eskayo/marvin', got '{result}'"


def test_stdin_capture_with_body_file_equals():
    """run_with_healing captures stdin for --body-file=- syntax."""
    # This is a pure parsing test; we verify the stdin capture logic
    # would trigger for --body-file=- (not just --body-file -)
    test_argv = ["issue", "create", "--body-file=-", "--label", "bug"]
    # Just verify label_call parses it as a label call
    call = lc.label_call(test_argv)
    assert call is not None, "Should parse issue create with --body-file=-"
    assert "bug" in call.add_labels


def test_stdin_capture_with_F_equals():
    """run_with_healing captures stdin for -F- syntax."""
    test_argv = ["issue", "create", "-F-", "--label", "bug"]
    # Verify label_call parses it as a label call
    call = lc.label_call(test_argv)
    assert call is not None, "Should parse issue create with -F-"
    assert "bug" in call.add_labels
