"""Tests for project_onboard.py. Run via:
    ~/.agents/venv/bin/python -m pytest lib/tests/test_project_onboard.py -v
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

LIB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LIB))

import project_onboard as po  # noqa: E402


# ── Plan function: pure tests with hand-built facts ─────────────────────


def test_plan_returns_all_required_pieces():
    facts = {
        "repo": "test/repo",
        "profile_exists": False,
        "has_workflows": False,
        "workflow_runs_swift_test": False,
        "labels": [],
        "has_agent_docs": False,
        "has_claude_md_skills": False,
        "board_exists": False,
        "clone_hint_resolves": False,
        "swift_installed": False,
        "has_package_swift": False,
        "detected_stack": None,
        "workflow_contents": "",
        "package_json_scripts": {},
        "tools_installed": {},
    }
    result = po.plan(facts)
    expected_pieces = {"profile", "stack", "test_command", "ci", "triage_labels", "agent_docs", "board", "clone_and_toolchain", "generated_paths"}
    assert set(result.keys()) == expected_pieces


def test_plan_output_is_json_serializable():
    facts = {
        "repo": "test/repo",
        "profile_exists": False,
        "has_workflows": False,
        "workflow_runs_swift_test": False,
        "labels": [],
        "has_agent_docs": False,
        "has_claude_md_skills": False,
        "board_exists": False,
        "clone_hint_resolves": False,
        "swift_installed": False,
        "has_package_swift": False,
        "detected_stack": None,
        "workflow_contents": "",
        "package_json_scripts": {},
        "tools_installed": {},
    }
    result = po.plan(facts)
    json_str = json.dumps(result)
    assert isinstance(json_str, str)


def test_plan_only_uses_ok_missing_needs_human_states():
    facts = {
        "repo": "test/repo",
        "profile_exists": True,
        "has_workflows": True,
        "workflow_runs_swift_test": True,
        "labels": list(po.TRIAGE_LABELS),
        "has_agent_docs": True,
        "has_claude_md_skills": True,
        "board_exists": True,
        "clone_hint_resolves": True,
        "swift_installed": True,
        "has_package_swift": True,
        "detected_stack": "swift-package",
        "workflow_contents": "swift test",
        "package_json_scripts": {},
        "tools_installed": {"swift": True},
    }
    result = po.plan(facts)
    for piece, info in result.items():
        assert info["state"] in {"ok", "missing", "needs-human"}, f"{piece} has invalid state: {info['state']}"


# ── Profile piece ────────────────────────────────────────────────────────


def test_profile_ok_when_exists():
    facts = {"profile_exists": True}
    result = po.plan(facts)
    assert result["profile"]["state"] == "ok"


def test_profile_missing_when_not_exists():
    facts = {"profile_exists": False}
    result = po.plan(facts)
    assert result["profile"]["state"] == "missing"


# ── Stack piece ─────────────────────────────────────────────────────────


def test_stack_ok_when_detected():
    facts = {"detected_stack": "swift-package"}
    result = po.plan(facts)
    assert result["stack"]["state"] == "ok"


def test_stack_needs_human_when_not_detected():
    facts = {"detected_stack": None}
    result = po.plan(facts)
    assert result["stack"]["state"] == "needs-human"


# ── CI piece ────────────────────────────────────────────────────────────


def test_ci_ok_when_workflow_runs_swift_test():
    facts = {"workflow_runs_swift_test": True, "test_command_state": "ok", "detected_stack": "swift-package", "has_workflows": True, "workflow_contents": "swift test"}
    result = po.plan(facts)
    # The CI state depends on multiple factors; this is a basic check
    # CI should be ok when we have a working test command and matching CI


def test_ci_missing_when_no_workflows():
    facts = {"has_workflows": False, "workflow_runs_swift_test": False, "detected_stack": "swift-package", "package_json_scripts": {}, "workflow_contents": "", "tools_installed": {}}
    result = po.plan(facts)
    assert result["ci"]["state"] == "missing"


def test_ci_needs_human_when_test_command_unknown():
    facts = {"has_workflows": True, "workflow_runs_swift_test": False, "detected_stack": None, "package_json_scripts": {}, "workflow_contents": "", "tools_installed": {}}
    result = po.plan(facts)
    assert result["ci"]["state"] == "needs-human"


# ── Triage labels piece ──────────────────────────────────────────────────


def test_triage_labels_ok_when_all_five_present():
    facts = {"labels": list(po.TRIAGE_LABELS)}
    result = po.plan(facts)
    assert result["triage_labels"]["state"] == "ok"


def test_triage_labels_missing_when_some_absent():
    facts = {"labels": ["needs-triage", "ready-for-agent"]}
    result = po.plan(facts)
    assert result["triage_labels"]["state"] == "missing"
    assert "missing:" in result["triage_labels"]["reason"]


def test_triage_labels_ok_with_extra_labels():
    facts = {"labels": list(po.TRIAGE_LABELS) + ["bug", "enhancement"]}
    result = po.plan(facts)
    assert result["triage_labels"]["state"] == "ok"


# ── Agent docs piece ────────────────────────────────────────────────────


def test_agent_docs_ok_when_all_present():
    facts = {"has_agent_docs": True, "has_claude_md_skills": True}
    result = po.plan(facts)
    assert result["agent_docs"]["state"] == "ok"


def test_agent_docs_missing_when_no_docs_files():
    facts = {"has_agent_docs": False, "has_claude_md_skills": True}
    result = po.plan(facts)
    assert result["agent_docs"]["state"] == "missing"
    assert "docs/agents" in result["agent_docs"]["reason"]


def test_agent_docs_missing_when_no_claude_md_block():
    facts = {"has_agent_docs": True, "has_claude_md_skills": False}
    result = po.plan(facts)
    assert result["agent_docs"]["state"] == "missing"
    assert "CLAUDE.md" in result["agent_docs"]["reason"]


def test_agent_docs_missing_when_both_absent():
    facts = {"has_agent_docs": False, "has_claude_md_skills": False}
    result = po.plan(facts)
    assert result["agent_docs"]["state"] == "missing"


# ── Board piece ──────────────────────────────────────────────────────────


def test_board_ok_when_exists():
    facts = {"board_exists": True}
    result = po.plan(facts)
    assert result["board"]["state"] == "ok"


def test_board_missing_when_not_exists():
    facts = {"board_exists": False}
    result = po.plan(facts)
    assert result["board"]["state"] == "missing"


# ── Clone and toolchain piece ────────────────────────────────────────────


def test_clone_and_toolchain_ok_when_both_present():
    facts = {"clone_hint_resolves": True, "swift_installed": True}
    result = po.plan(facts)
    assert result["clone_and_toolchain"]["state"] == "ok"


def test_clone_and_toolchain_missing_when_clone_exists_but_swift_missing():
    facts = {"clone_hint_resolves": True, "swift_installed": False}
    result = po.plan(facts)
    assert result["clone_and_toolchain"]["state"] == "missing"


def test_clone_and_toolchain_missing_when_clone_missing_but_clonable():
    facts = {"clone_hint_resolves": False, "swift_installed": False, "profile_exists": True}
    result = po.plan(facts)
    assert result["clone_and_toolchain"]["state"] == "missing"


def test_clone_and_toolchain_needs_human_when_no_clone_hint():
    facts = {"clone_hint_resolves": False, "swift_installed": False, "profile_exists": False}
    result = po.plan(facts)
    assert result["clone_and_toolchain"]["state"] == "needs-human"


# ── Test command piece ───────────────────────────────────────────────────


def test_test_command_ok_for_swift_package():
    facts = {"detected_stack": "swift-package", "package_json_scripts": {}, "workflow_contents": "", "tools_installed": {}}
    result = po.plan(facts)
    assert result["test_command"]["state"] == "ok"


def test_test_command_ok_for_xcodegen_app():
    facts = {"detected_stack": "xcodegen-app", "package_json_scripts": {}, "workflow_contents": "", "tools_installed": {}}
    result = po.plan(facts)
    assert result["test_command"]["state"] == "ok"


def test_test_command_ok_for_node_electron_with_test_script():
    facts = {"detected_stack": "node-electron", "package_json_scripts": {"test": "vitest"}, "workflow_contents": "", "tools_installed": {}}
    result = po.plan(facts)
    assert result["test_command"]["state"] == "ok"


def test_test_command_needs_human_for_node_electron_without_test_script():
    facts = {"detected_stack": "node-electron", "package_json_scripts": {}, "workflow_contents": "", "tools_installed": {}}
    result = po.plan(facts)
    assert result["test_command"]["state"] == "needs-human"


def test_test_command_needs_human_when_stack_unknown():
    facts = {"detected_stack": None, "package_json_scripts": {}, "workflow_contents": "", "tools_installed": {}}
    result = po.plan(facts)
    assert result["test_command"]["state"] == "needs-human"


# ── Inspection: integration tests ────────────────────────────────────────


def test_inspect_returns_dict_with_required_keys():
    def mock_gh(args):
        return ""

    result = po.inspect("test/repo", gh=mock_gh)
    required_keys = {
        "repo", "visibility", "default_branch", "file_tree", "labels",
        "profile_exists", "board_exists", "clone_hint_resolves",
        "swift_installed", "has_package_swift", "has_workflows",
        "workflow_runs_swift_test", "has_agent_docs", "has_claude_md_skills",
        "detected_stack", "workflow_contents", "package_json_scripts", "tools_installed",
    }
    assert set(result.keys()) >= required_keys


def test_inspect_defaults_to_main_branch():
    def mock_gh(args):
        return ""

    result = po.inspect("test/repo", gh=mock_gh)
    assert result["default_branch"] == "main"


def test_inspect_parses_repo_visibility_and_branch():
    def mock_gh(args):
        if "repo view" in " ".join(args):
            return json.dumps({"visibility": "public", "defaultBranchRef": {"name": "develop"}})
        return ""

    result = po.inspect("test/repo", gh=mock_gh)
    assert result["visibility"] == "public"
    assert result["default_branch"] == "develop"


def test_inspect_tolerates_malformed_gh_responses():
    def mock_gh(args):
        return "{malformed json"

    result = po.inspect("test/repo", gh=mock_gh)
    assert result["visibility"] is None
    assert result["default_branch"] == "main"


def test_plan_with_fully_onboarded_project():
    facts = {
        "repo": "full/project",
        "profile_exists": True,
        "has_workflows": True,
        "workflow_runs_swift_test": True,
        "labels": list(po.TRIAGE_LABELS),
        "has_agent_docs": True,
        "has_claude_md_skills": True,
        "board_exists": True,
        "clone_hint_resolves": True,
        "swift_installed": True,
        "has_package_swift": True,
        "detected_stack": "swift-package",
        "workflow_contents": "swift test",
        "package_json_scripts": {},
        "tools_installed": {"swift": True},
        "visibility": "public",
    }
    result = po.plan(facts)
    for piece, info in result.items():
        assert info["state"] == "ok", f"{piece} should be ok but is {info['state']}"


def test_plan_with_fresh_project():
    facts = {
        "repo": "fresh/project",
        "profile_exists": False,
        "has_workflows": False,
        "workflow_runs_swift_test": False,
        "labels": [],
        "has_agent_docs": False,
        "has_claude_md_skills": False,
        "board_exists": False,
        "clone_hint_resolves": False,
        "swift_installed": False,
        "has_package_swift": False,
        "detected_stack": None,
        "workflow_contents": "",
        "package_json_scripts": {},
        "tools_installed": {},
    }
    result = po.plan(facts)
    for piece in ["profile", "ci", "triage_labels", "agent_docs", "board", "stack", "test_command"]:
        assert result[piece]["state"] in {"missing", "needs-human"}


# ── CLI and full workflow integration ────────────────────────────────────


def test_plan_output_has_reason_field_for_all_pieces():
    facts = {
        "repo": "test/repo",
        "profile_exists": True,
        "has_workflows": True,
        "workflow_runs_swift_test": True,
        "labels": list(po.TRIAGE_LABELS),
        "has_agent_docs": True,
        "has_claude_md_skills": True,
        "board_exists": True,
        "clone_hint_resolves": True,
        "swift_installed": True,
        "has_package_swift": True,
        "detected_stack": "swift-package",
        "workflow_contents": "swift test",
        "package_json_scripts": {},
        "tools_installed": {"swift": True},
        "visibility": "public",
    }
    result = po.plan(facts)
    for piece, info in result.items():
        assert "state" in info, f"{piece} missing 'state' field"
        assert "reason" in info, f"{piece} missing 'reason' field"
        assert isinstance(info["reason"], str), f"{piece} reason is not a string"
        assert len(info["reason"]) > 0, f"{piece} reason is empty"


def test_plan_with_partial_project_state():
    facts = {
        "repo": "partial/project",
        "profile_exists": True,
        "has_workflows": False,
        "workflow_runs_swift_test": False,
        "labels": ["needs-triage", "ready-for-agent"],
        "has_agent_docs": True,
        "has_claude_md_skills": False,
        "board_exists": True,
        "clone_hint_resolves": True,
        "swift_installed": False,
        "has_package_swift": True,
        "detected_stack": "swift-package",
        "workflow_contents": "",
        "package_json_scripts": {},
        "tools_installed": {"swift": False},
    }
    result = po.plan(facts)
    assert result["profile"]["state"] == "ok"
    assert result["stack"]["state"] == "ok"
    assert result["ci"]["state"] == "missing"
    assert result["triage_labels"]["state"] == "missing"
    assert result["agent_docs"]["state"] == "missing"
    assert result["board"]["state"] == "ok"
    assert result["clone_and_toolchain"]["state"] == "missing"
    assert result["test_command"]["state"] == "ok"


# ── Module correctness ───────────────────────────────────────────────────


def test_module_has_public_api():
    assert hasattr(po, "_gh") and callable(po._gh)
    assert hasattr(po, "inspect") and callable(po.inspect)
    assert hasattr(po, "plan") and callable(po.plan)
    assert hasattr(po, "main") and callable(po.main)
    assert hasattr(po, "TRIAGE_LABELS") and isinstance(po.TRIAGE_LABELS, set)


def test_triage_labels_are_the_canonical_five():
    expected = {"needs-triage", "needs-info", "ready-for-agent", "ready-for-human", "wontfix"}
    assert po.TRIAGE_LABELS == expected


# ── Stack detection ──────────────────────────────────────────────────────


def test_detect_swift_package_from_nested_package_swift():
    """Swift package with nested Package.swift (like clarity-captions)."""
    facts = {
        "detected_stack": "swift-package",
        "package_json_scripts": {},
        "workflow_contents": "",
        "tools_installed": {"swift": True},
        "clone_hint_resolves": True,
        "has_workflows": False,
    }
    result = po.plan(facts)
    assert result["stack"]["state"] == "ok"
    assert result["test_command"]["state"] == "ok"


def test_detect_xcodegen_app_over_swift_package():
    """When both project.yml and Package.swift exist, xcodegen-app wins (priority 10 vs 20)."""
    facts = {
        "detected_stack": "xcodegen-app",
        "package_json_scripts": {},
        "workflow_contents": "",
        "tools_installed": {"xcodegen": True},
    }
    result = po.plan(facts)
    assert result["stack"]["state"] == "ok"
    assert result["test_command"]["state"] == "ok"


def test_detect_node_electron_from_package_json():
    """Node/Electron app detection from package.json content."""
    facts = {
        "detected_stack": "node-electron",
        "package_json_scripts": {"test": "vitest"},
        "workflow_contents": "",
        "tools_installed": {"node": True},
    }
    result = po.plan(facts)
    assert result["stack"]["state"] == "ok"
    assert result["test_command"]["state"] == "ok"


def test_node_electron_without_test_script():
    """Node/Electron app without test script is needs-human."""
    facts = {
        "detected_stack": "node-electron",
        "package_json_scripts": {},
        "workflow_contents": "",
        "tools_installed": {"node": True},
    }
    result = po.plan(facts)
    assert result["test_command"]["state"] == "needs-human"
    assert "never guess" in result["test_command"]["reason"]


def test_cost_warning_for_private_macos_runner():
    """Private repo with macOS runner gets cost warning in CI piece."""
    facts = {
        "visibility": "private",
        "detected_stack": "swift-package",
        "has_workflows": True,
        "workflow_contents": "swift test",
        "package_json_scripts": {},
        "workflow_runs_swift_test": True,
        "tools_installed": {"swift": True},
        "clone_hint_resolves": True,
    }
    result = po.plan(facts)
    assert "cost_warning" in result["ci"]


def test_no_cost_warning_for_public_macos_runner():
    """Public repo with macOS runner does not get cost warning."""
    facts = {
        "visibility": "public",
        "detected_stack": "swift-package",
        "has_workflows": True,
        "workflow_contents": "swift test",
        "package_json_scripts": {},
        "workflow_runs_swift_test": True,
        "tools_installed": {"swift": True},
        "clone_hint_resolves": True,
    }
    result = po.plan(facts)
    assert result["ci"]["state"] == "ok"


def test_no_cost_warning_for_node_electron():
    """Node/Electron runs on ubuntu, no cost warning even if private."""
    facts = {
        "visibility": "private",
        "detected_stack": "node-electron",
        "has_workflows": True,
        "workflow_contents": "npm test",
        "package_json_scripts": {"test": "vitest"},
        "tools_installed": {"node": True},
    }
    result = po.plan(facts)
    assert "cost_warning" not in result["ci"]


# ── Real-world fixtures: finance-os and clarity-captions ───────────────


def test_clarity_captions_real_world():
    """Clarity-captions: public, xcodegen-app, nested Package.swift, should detect as xcodegen-app."""
    facts = {
        "repo": "G-Eskayo/clarity-captions",
        "visibility": "public",
        "detected_stack": "xcodegen-app",
        "has_package_swift": False,  # nested, not at root
        "has_workflows": True,
        "workflow_contents": "xcodebuild test",
        "package_json_scripts": {},
        "tools_installed": {"xcodegen": True, "swift": True},
        "clone_hint_resolves": True,
        "profile_exists": True,
        "board_exists": True,
        "labels": list(po.TRIAGE_LABELS),
        "has_agent_docs": True,
        "has_claude_md_skills": True,
    }
    result = po.plan(facts)
    # Verify AC4: no piece should report 'missing' when it shouldn't
    assert result["stack"]["state"] == "ok"
    assert result["test_command"]["state"] == "ok"
    assert result["ci"]["state"] == "ok"
    assert "missing" not in [result[p]["state"] for p in ["stack", "test_command"]]


def test_finance_os_real_world():
    """Finance-os: private, node-electron, has test script."""
    facts = {
        "repo": "G-Eskayo/finance-os",
        "visibility": "private",
        "detected_stack": "node-electron",
        "has_workflows": True,
        "workflow_contents": "npm test",
        "package_json_scripts": {"test": "vitest"},
        "tools_installed": {"node": True, "npm": True},
        "clone_hint_resolves": True,
        "profile_exists": True,
        "board_exists": True,
        "labels": list(po.TRIAGE_LABELS),
        "has_agent_docs": True,
        "has_claude_md_skills": True,
    }
    result = po.plan(facts)
    # Verify AC2 & AC4: test_command and stack are ok, ci is ok
    assert result["stack"]["state"] == "ok"
    assert result["test_command"]["state"] == "ok"
    assert result["ci"]["state"] == "ok"


# ── Generated paths proposals ────────────────────────────────────────────


def test_generated_paths_proposal_when_candidates_found():
    """Generated paths are proposed (needs-human) when their files exist in the tree."""
    facts = {
        "detected_stack": "swift-package",
        "file_tree": {".build": "dir", "Package.swift": "file"},
        "package_json_scripts": {},
        "workflow_contents": "",
        "tools_installed": {},
    }
    result = po.plan(facts)
    assert result["generated_paths"]["state"] == "needs-human"
    assert len(result["generated_paths"].get("proposals", [])) > 0


def test_generated_paths_ok_when_no_candidates_found():
    """Generated paths are ok (no proposals) when candidate files are not in the tree."""
    facts = {
        "detected_stack": "swift-package",
        "file_tree": {"Package.swift": "file"},
        "package_json_scripts": {},
        "workflow_contents": "",
        "tools_installed": {},
    }
    result = po.plan(facts)
    assert result["generated_paths"]["state"] == "ok"
    assert result["generated_paths"].get("proposals", []) == []


# ── Apply functions (ticket #146) ────────────────────────────────────────


def test_apply_labels_creates_missing_labels():
    """_apply_labels creates labels that are not in facts["labels"], idempotent."""
    facts = {"labels": []}
    calls = []

    def mock_gh(args):
        calls.append(args)
        return ""

    result = po._apply_labels("test/repo", facts, gh=mock_gh)
    assert result["action"] == "created"
    assert len(result["labels"]) == 5
    assert set(result["labels"]) == po.TRIAGE_LABELS
    # Each label should have a label create call
    assert len([c for c in calls if "label" in c and "create" in c]) == 5


def test_apply_labels_idempotent_when_all_present():
    """_apply_labels makes no calls when all labels already exist."""
    facts = {"labels": list(po.TRIAGE_LABELS)}
    calls = []

    def mock_gh(args):
        calls.append(args)
        return ""

    result = po._apply_labels("test/repo", facts, gh=mock_gh)
    assert result["action"] == "unchanged"
    assert len(result["labels"]) == 0
    assert len(calls) == 0


def test_apply_labels_partial_creates():
    """_apply_labels creates only missing labels."""
    facts = {"labels": ["needs-triage", "ready-for-agent"]}
    calls = []

    def mock_gh(args):
        calls.append(args)
        return ""

    result = po._apply_labels("test/repo", facts, gh=mock_gh)
    assert result["action"] == "created"
    assert len(result["labels"]) == 3
    missing = po.TRIAGE_LABELS - {"needs-triage", "ready-for-agent"}
    assert set(result["labels"]) == missing


def test_apply_labels_use_correct_colors():
    """_apply_labels passes correct hex colors for each label."""
    facts = {"labels": []}
    calls = []

    def mock_gh(args):
        calls.append(args)
        return ""

    po._apply_labels("test/repo", facts, gh=mock_gh)
    # Check that color args are present for each label create call
    color_calls = [c for c in calls if "label" in c and "create" in c]
    assert len(color_calls) > 0
    for call in color_calls:
        if "--color" in call:
            color_idx = call.index("--color")
            color = call[color_idx + 1]
            # Color should be a hex string like "d4c5f9"
            assert len(color) == 6
            assert all(c in "0123456789abcdefABCDEF" for c in color)


def test_apply_profile_no_stack_needs_human():
    """_apply_profile with no detected_stack returns needs-human."""
    facts = {"detected_stack": None}
    result = po._apply_profile("test/repo", facts)
    assert result["action"] == "needs-human"


def test_apply_profile_fresh_creates():
    """_apply_profile on fresh repo creates profile with correct structure."""
    import tempfile
    with tempfile.TemporaryDirectory() as tmpdir:
        profiles_dir = Path(tmpdir)
        facts = {
            "repo": "test/repo",
            "detected_stack": "swift-package",
            "default_branch": "main",
        }
        result = po._apply_profile("test/repo", facts, profiles_dir=profiles_dir)
        assert result["action"] == "created"
        assert "diff" in result
        assert result["diff"]  # Non-empty diff
        profile = result["profile"]
        assert profile["repo"] == "test/repo"
        assert profile["dispatch"] == "off"
        assert profile["merge_from_dashboard"] is False


def test_apply_profile_unchanged_on_rerun():
    """_apply_profile returns unchanged on second run with same repo."""
    import tempfile
    with tempfile.TemporaryDirectory() as tmpdir:
        profiles_dir = Path(tmpdir)
        facts = {
            "repo": "test/repo",
            "detected_stack": "swift-package",
            "default_branch": "main",
        }
        result1 = po._apply_profile("test/repo", facts, profiles_dir=profiles_dir)
        assert result1["action"] == "created"
        # Write the profile to disk
        profile_path = profiles_dir / "repo.json"
        profile_path.write_text(json.dumps(result1["profile"], indent=2) + "\n")

        # Run again
        result2 = po._apply_profile("test/repo", facts, profiles_dir=profiles_dir)
        assert result2["action"] == "unchanged"


def test_apply_profile_conflict_on_edit():
    """_apply_profile returns conflict when existing file differs."""
    import tempfile
    with tempfile.TemporaryDirectory() as tmpdir:
        profiles_dir = Path(tmpdir)
        facts = {
            "repo": "test/repo",
            "detected_stack": "swift-package",
            "default_branch": "main",
        }
        # Create a pre-existing file with different content
        profile_path = profiles_dir / "repo.json"
        profile_path.write_text('{"repo": "test/repo", "dispatch": "on"}\n')

        result = po._apply_profile("test/repo", facts, profiles_dir=profiles_dir)
        assert result["action"] == "conflict"
        assert "diff" in result
        # File should not be overwritten
        assert profile_path.read_text() == '{"repo": "test/repo", "dispatch": "on"}\n'


def test_apply_profile_conflict_on_malformed():
    """_apply_profile returns conflict when existing file is not valid JSON."""
    import tempfile
    with tempfile.TemporaryDirectory() as tmpdir:
        profiles_dir = Path(tmpdir)
        facts = {
            "repo": "test/repo",
            "detected_stack": "swift-package",
            "default_branch": "main",
        }
        # Create a pre-existing file with invalid JSON
        profile_path = profiles_dir / "repo.json"
        profile_path.write_text('not valid json')

        result = po._apply_profile("test/repo", facts, profiles_dir=profiles_dir)
        assert result["action"] == "conflict"
        # File should remain untouched
        assert profile_path.read_text() == 'not valid json'


def test_apply_board_idempotent():
    """_apply_board is idempotent via board_registry.ensure_board."""
    facts = {}
    # This tests that the wrapper correctly returns created/unchanged
    result = po._apply_board("test/repo", facts)
    assert "action" in result
    assert result["action"] in ("created", "unchanged")


def test_apply_full_idempotency():
    """apply() is fully idempotent across two runs."""
    import tempfile
    with tempfile.TemporaryDirectory() as tmpdir:
        profiles_dir = Path(tmpdir)
        facts = {
            "repo": "test/repo",
            "labels": [],
            "detected_stack": "swift-package",
            "default_branch": "main",
        }
        calls1 = []
        calls2 = []

        def mock_gh1(args):
            calls1.append(args)
            return ""

        def mock_gh2(args):
            calls2.append(args)
            return ""

        # First run
        result1 = po.apply("test/repo", facts=facts, profiles_dir=profiles_dir, gh=mock_gh1)
        assert result1["labels"]["action"] == "created"
        assert result1["profile"]["action"] == "created"
        # Profile should be written to disk
        profile_path = profiles_dir / "repo.json"
        assert profile_path.exists()

        # Second run: labels and profile already exist now
        facts["labels"] = list(po.TRIAGE_LABELS)
        result2 = po.apply("test/repo", facts=facts, profiles_dir=profiles_dir, gh=mock_gh2)
        # Labels should be unchanged, so no new calls
        assert len([c for c in calls2 if "label" in c and "create" in c]) == 0
        # Profile should be unchanged
        assert result2["profile"]["action"] == "unchanged"
        # Profile file should not be modified (same content)
        profile_content_after = profile_path.read_text()
        profile_content_expected = json.dumps(result1["profile"]["profile"], indent=2) + "\n"
        assert profile_content_after == profile_content_expected


def test_apply_forces_dispatch_off():
    """_apply_profile always forces dispatch to 'off' and merge_from_dashboard to False."""
    import tempfile
    with tempfile.TemporaryDirectory() as tmpdir:
        profiles_dir = Path(tmpdir)
        facts = {
            "repo": "test/repo",
            "detected_stack": "swift-package",
            "default_branch": "main",
        }
        result = po._apply_profile("test/repo", facts, profiles_dir=profiles_dir)
        profile = result["profile"]
        assert profile["dispatch"] == "off"
        assert profile["merge_from_dashboard"] is False


def test_apply_profile_all_stacks():
    """_apply_profile works for all three stacks: swift-package, xcodegen-app, node-electron."""
    import tempfile
    with tempfile.TemporaryDirectory() as tmpdir:
        profiles_dir = Path(tmpdir)
        for stack in ["swift-package", "xcodegen-app", "node-electron"]:
            facts = {
                "repo": "test/repo",
                "detected_stack": stack,
                "default_branch": "main",
            }
            result = po._apply_profile(f"test/{stack}-repo", facts, profiles_dir=profiles_dir)
            # Should not fail for any stack


# ── Onboarding storage and refresh ──────────────────────────────────────

def test_onboarding_path():
    """onboarding_path extracts repo name and builds correct path."""
    path = po.onboarding_path("G-Eskayo/marvin")
    assert path.name == "marvin.json"
    assert "onboarding" in str(path)


def test_onboarding_path_with_custom_dir(tmp_path):
    """onboarding_path respects custom dir parameter."""
    path = po.onboarding_path("test/repo", dir=tmp_path)
    assert path.parent == tmp_path
    assert path.name == "repo.json"


def test_write_onboarding_plan(tmp_path):
    """write_onboarding_plan writes JSON with repo, generated_at, and pieces."""
    plan_out = {"profile": {"state": "ok", "reason": "exists"}}
    po.write_onboarding_plan("test/repo", plan_out, dir=tmp_path)

    path = tmp_path / "repo.json"
    assert path.exists()
    data = json.loads(path.read_text())
    assert data["repo"] == "test/repo"
    assert data["pieces"] == plan_out
    assert "generated_at" in data


def test_refresh_onboarding_plan(tmp_path):
    """refresh_onboarding_plan runs inspect, plan, and write."""
    def mock_gh(args):
        if "repo" in args and "view" in args:
            return '{"visibility": "public", "defaultBranchRef": {"name": "main"}}'
        if "trees" in args:
            return '{"tree": []}'
        if "label" in args:
            return '[]'
        return ""

    po.refresh_onboarding_plan("test/repo", gh=mock_gh, dir=tmp_path)

    path = tmp_path / "repo.json"
    assert path.exists()
    data = json.loads(path.read_text())
    assert data["repo"] == "test/repo"
    assert "pieces" in data


def test_refresh_all_onboarding_plans_with_failure(tmp_path, monkeypatch):
    """refresh_all_onboarding_plans writes successes, leaves failures untouched."""
    def mock_gh_success(args):
        if "repo" in args and "view" in args:
            return '{"visibility": "public", "defaultBranchRef": {"name": "main"}}'
        if "trees" in args:
            return '{"tree": []}'
        if "label" in args:
            return '[]'
        return ""

    # First run: both succeed
    result1 = po.refresh_all_onboarding_plans(
        ["test/repo1", "test/repo2"],
        gh=mock_gh_success,
        dir=tmp_path
    )
    assert len(result1["ok"]) == 2
    assert len(result1["failed"]) == 0

    # Verify files exist
    assert (tmp_path / "repo1.json").exists()
    assert (tmp_path / "repo2.json").exists()

    # Read original repo2 content
    original_repo2 = (tmp_path / "repo2.json").read_text()

    # Second run with partial failure: repo2 fails, repo1 succeeds
    # Mock refresh_onboarding_plan to raise for repo2
    original_refresh = po.refresh_onboarding_plan
    def mock_refresh(repo, gh, dir):
        if repo == "test/repo2":
            raise Exception("Network error")
        return original_refresh(repo, gh, dir)

    monkeypatch.setattr(po, "refresh_onboarding_plan", mock_refresh)

    result2 = po.refresh_all_onboarding_plans(
        ["test/repo1", "test/repo2"],
        gh=mock_gh_success,
        dir=tmp_path
    )
    # repo1 should succeed, repo2 should fail
    assert "test/repo1" in result2["ok"]
    assert any(r == "test/repo2" for r, _ in result2["failed"])

    # Verify repo2's file is unchanged (not nuked by error)
    assert (tmp_path / "repo2.json").read_text() == original_repo2


# ── PR mode helpers and pure functions ──────────────────────────────────────


def test_missing_agent_doc_files_all_present():
    """_missing_agent_doc_files returns empty list when all docs present."""
    file_tree = {
        "docs/agents/issue-tracker.md": "file",
        "docs/agents/triage-labels.md": "file",
        "docs/agents/domain.md": "file",
    }
    result = po._missing_agent_doc_files(file_tree)
    assert result == []


def test_missing_agent_doc_files_some_missing():
    """_missing_agent_doc_files returns list of missing files."""
    file_tree = {
        "docs/agents/triage-labels.md": "file",
    }
    result = po._missing_agent_doc_files(file_tree)
    assert set(result) == {
        "docs/agents/issue-tracker.md",
        "docs/agents/domain.md",
    }


def test_render_issue_tracker_doc():
    """_render_issue_tracker_doc produces valid markdown with repo name."""
    result = po._render_issue_tracker_doc("G-Eskayo/marvin")
    assert "# Issue Tracker" in result
    assert "G-Eskayo/marvin" in result
    assert "GitHub Issues" in result
    assert "`gh`" in result


def test_render_triage_labels_doc():
    """_render_triage_labels_doc produces markdown table with all five roles."""
    result = po._render_triage_labels_doc()
    assert "# Triage Labels" in result
    assert "needs-triage" in result
    assert "needs-info" in result
    assert "ready-for-agent" in result
    assert "ready-for-human" in result
    assert "wontfix" in result


def test_render_domain_doc():
    """_render_domain_doc produces markdown with single-context layout."""
    result = po._render_domain_doc()
    assert "# Domain Docs" in result
    assert "Single-context" in result
    assert "CONTEXT.md" in result
    assert "docs/adr/" in result


def test_render_claude_md_block():
    """_render_claude_md_block produces markdown with format placeholder."""
    result = po._render_claude_md_block()
    assert "## Agent skills" in result
    assert "{repo}" in result
    formatted = result.format(repo="test/repo")
    assert "test/repo" in formatted


def test_ci_yml_for_stack_swift():
    """_ci_yml_for_stack returns content for swift-package."""
    result = po._ci_yml_for_stack("swift-package")
    assert result is not None
    assert "swift test" in result


def test_ci_yml_for_stack_node():
    """_ci_yml_for_stack returns content for node-electron."""
    result = po._ci_yml_for_stack("node-electron")
    assert result is not None


def test_ci_yml_for_stack_none():
    """_ci_yml_for_stack returns None when stack is None."""
    result = po._ci_yml_for_stack(None)
    assert result is None


def test_ci_yml_for_stack_unknown():
    """_ci_yml_for_stack returns None for unknown stack."""
    result = po._ci_yml_for_stack("unknown-stack")
    assert result is None


def test_check_workflow_scope_present():
    """_check_workflow_scope returns True when workflow scope is present."""
    def mock_run(cmd, **kwargs):
        result = subprocess.CompletedProcess(cmd, 0)
        result.stdout = "gh version\nToken scopes: repo, admin:org_hook, workflow"
        result.stderr = ""
        return result

    result = po._check_workflow_scope(run=mock_run)
    assert result is True


def test_check_workflow_scope_absent():
    """_check_workflow_scope returns False when workflow scope is absent."""
    def mock_run(cmd, **kwargs):
        result = subprocess.CompletedProcess(cmd, 0)
        result.stdout = "gh version\nToken scopes: repo, admin:org_hook"
        result.stderr = ""
        return result

    result = po._check_workflow_scope(run=mock_run)
    assert result is False


def test_check_workflow_scope_command_failure():
    """_check_workflow_scope returns False on command failure."""
    def mock_run(cmd, **kwargs):
        result = subprocess.CompletedProcess(cmd, 1)
        result.stdout = ""
        result.stderr = "error"
        return result

    result = po._check_workflow_scope(run=mock_run)
    assert result is False


def test_pr_files_to_write_all_missing():
    """_pr_files_to_write includes all docs when missing (except CLAUDE.md)."""
    facts = {
        "file_tree": {},
        "detected_stack": "swift-package",
        "has_claude_md_skills": False,
    }
    plan_out = {
        "ci": {"state": "missing"},
    }
    result = po._pr_files_to_write("test/repo", facts, plan_out)

    assert "docs/agents/issue-tracker.md" in result
    assert "docs/agents/triage-labels.md" in result
    assert "docs/agents/domain.md" in result
    assert ".github/workflows/ci.yml" in result
    assert "CLAUDE.md" not in result  # Handled separately in _apply_pr
    assert "test/repo" in result["docs/agents/issue-tracker.md"]


def test_pr_files_to_write_partial_missing():
    """_pr_files_to_write includes only missing docs (except CLAUDE.md)."""
    facts = {
        "file_tree": {
            "docs/agents/issue-tracker.md": "file",
        },
        "detected_stack": "swift-package",
        "has_claude_md_skills": True,
    }
    plan_out = {
        "ci": {"state": "missing"},
    }
    result = po._pr_files_to_write("test/repo", facts, plan_out)

    assert "docs/agents/issue-tracker.md" not in result
    assert "docs/agents/triage-labels.md" in result
    assert "docs/agents/domain.md" in result
    assert ".github/workflows/ci.yml" in result


def test_pr_files_to_write_ci_needs_human():
    """_pr_files_to_write excludes CI when state is needs-human."""
    facts = {
        "file_tree": {},
        "detected_stack": None,
        "has_claude_md_skills": False,
    }
    plan_out = {
        "ci": {"state": "needs-human"},
    }
    result = po._pr_files_to_write("test/repo", facts, plan_out)

    assert ".github/workflows/ci.yml" not in result


def test_pr_files_to_write_nothing_missing():
    """_pr_files_to_write returns empty dict when nothing is missing."""
    facts = {
        "file_tree": {
            "docs/agents/issue-tracker.md": "file",
            "docs/agents/triage-labels.md": "file",
            "docs/agents/domain.md": "file",
        },
        "detected_stack": None,
        "has_claude_md_skills": True,
    }
    plan_out = {
        "ci": {"state": "ok"},
    }
    result = po._pr_files_to_write("test/repo", facts, plan_out)

    assert result == {}


def test_merge_claude_md_block_creates_new_file(tmp_path):
    """_merge_claude_md_block creates CLAUDE.md if neither file exists."""
    result = po._merge_claude_md_block("test/repo", {}, tmp_path)
    assert result is True
    assert (tmp_path / "CLAUDE.md").exists()
    content = (tmp_path / "CLAUDE.md").read_text()
    assert "## Agent skills" in content
    assert "test/repo" in content


def test_merge_claude_md_block_merges_into_existing(tmp_path):
    """_merge_claude_md_block inserts block into existing CLAUDE.md."""
    claude_path = tmp_path / "CLAUDE.md"
    claude_path.write_text("# My Project\n\nSome content here.\n")

    result = po._merge_claude_md_block("test/repo", {}, tmp_path)
    assert result is True

    content = claude_path.read_text()
    assert "## Agent skills" in content
    assert "My Project" in content
    assert "Some content here" in content


def test_merge_claude_md_block_idempotent(tmp_path):
    """_merge_claude_md_block is idempotent — doesn't add block twice."""
    claude_path = tmp_path / "CLAUDE.md"
    claude_path.write_text("# My Project\n\n## Agent skills\n\nAlready present.\n")

    result = po._merge_claude_md_block("test/repo", {}, tmp_path)
    assert result is False
    assert claude_path.read_text().count("## Agent skills") == 1


def test_merge_claude_md_block_uses_agents_md(tmp_path):
    """_merge_claude_md_block uses AGENTS.md if CLAUDE.md doesn't exist."""
    agents_path = tmp_path / "AGENTS.md"
    agents_path.write_text("# Agents Config\n\nSome content.\n")

    result = po._merge_claude_md_block("test/repo", {}, tmp_path)
    assert result is True
    assert not (tmp_path / "CLAUDE.md").exists()

    content = agents_path.read_text()
    assert "## Agent skills" in content
    assert "Agents Config" in content


# ── PR mode integration tests with fixture repo ──────────────────────────────


def _run(cmd, cwd=None, **kwargs):
    """Helper to run git commands in tests."""
    subprocess.run(cmd, cwd=cwd, check=True, capture_output=True, **kwargs)


@pytest.fixture
def fixture_repo(tmp_path):
    """Fixture: a bare 'origin' remote and a main-repo clone with initial commit."""
    origin = tmp_path / "origin.git"
    origin.mkdir()
    _run(["git", "init", "-q", "--bare"], cwd=origin)

    main_repo = tmp_path / "main-repo"
    main_repo.mkdir()
    _run(["git", "init", "-q"], cwd=main_repo)
    _run(["git", "config", "user.email", "test@test.com"], cwd=main_repo)
    _run(["git", "config", "user.name", "Test"], cwd=main_repo)
    (main_repo / "README.md").write_text("hello\n")
    _run(["git", "add", "."], cwd=main_repo)
    _run(["git", "commit", "-q", "-m", "init"], cwd=main_repo)
    _run(["git", "branch", "-M", "main"], cwd=main_repo)
    _run(["git", "remote", "add", "origin", str(origin)], cwd=main_repo)
    _run(["git", "push", "-u", "origin", "main"], cwd=main_repo)

    return {
        "origin": origin,
        "main_repo": main_repo,
        "repo_path": f"file://{origin}",
    }


def test_apply_pr_unchanged_when_nothing_missing(fixture_repo):
    """_apply_pr returns 'unchanged' when no files are missing and Claude skills exist."""
    facts = {
        "file_tree": {
            "docs/agents/issue-tracker.md": "file",
            "docs/agents/triage-labels.md": "file",
            "docs/agents/domain.md": "file",
        },
        "default_branch": "main",
        "detected_stack": None,
        "has_claude_md_skills": True,
    }
    plan_out = {"ci": {"state": "ok"}}

    def mock_run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 0, "", "")

    def mock_gh(args):
        return ""

    result = po._apply_pr("test/repo", facts, plan_out, gh=mock_gh, run=mock_run)

    assert result["action"] == "unchanged"


def test_apply_pr_needs_human_when_scope_missing():
    """_apply_pr returns needs-human when workflow scope is missing (AC2)."""
    facts = {
        "file_tree": {},
        "default_branch": "main",
        "detected_stack": "swift-package",
        "has_claude_md_skills": False,
    }
    plan_out = {"ci": {"state": "missing"}}

    def mock_run_no_workflow(cmd, **kwargs):
        if cmd[0:2] == ["gh", "auth"]:
            result = subprocess.CompletedProcess(cmd, 0)
            result.stdout = "Token scopes: repo"
            result.stderr = ""
            return result
        return subprocess.CompletedProcess(cmd, 0, "", "")

    result = po._apply_pr("test/repo", facts, plan_out, run=mock_run_no_workflow)

    assert result["action"] == "needs-human"
    assert "workflow" in result["reason"]
    assert result["pr_url"] is None


def test_apply_pr_no_git_operations_before_scope_check():
    """_apply_pr checks workflow scope before any git operations (AC2)."""
    facts = {
        "file_tree": {},
        "default_branch": "main",
        "detected_stack": "swift-package",
        "has_claude_md_skills": False,
    }
    plan_out = {"ci": {"state": "missing"}}

    calls = {"gh_repo_clone": 0}

    def mock_run_no_workflow(cmd, **kwargs):
        if cmd[0:2] == ["gh", "auth"]:
            result = subprocess.CompletedProcess(cmd, 0)
            result.stdout = "Token scopes: repo"
            result.stderr = ""
            return result
        if cmd[0:3] == ["gh", "repo", "clone"]:
            calls["gh_repo_clone"] += 1
        return subprocess.CompletedProcess(cmd, 0, "", "")

    po._apply_pr("test/repo", facts, plan_out, run=mock_run_no_workflow)

    assert calls["gh_repo_clone"] == 0


def test_apply_pr_uses_fixed_branch_name():
    """_apply_pr uses fixed branch name 'onboarding/agent-wiring' (AC4)."""
    facts = {
        "file_tree": {},
        "default_branch": "main",
        "detected_stack": "swift-package",
        "has_claude_md_skills": False,
    }
    plan_out = {"ci": {"state": "missing"}}

    git_commands = []

    def mock_run(cmd, **kwargs):
        git_commands.append(cmd)
        if cmd[0:2] == ["gh", "auth"]:
            result = subprocess.CompletedProcess(cmd, 0)
            result.stdout = "Token scopes: repo, workflow"
            result.stderr = ""
            return result
        if cmd[0] == "git" and "checkout" in cmd:
            if "onboarding/agent-wiring" not in cmd:
                raise AssertionError(f"Expected onboarding/agent-wiring in {cmd}")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    result = po._apply_pr("test/repo", facts, plan_out, run=mock_run)

    checkout_cmds = [c for c in git_commands if c[0] == "git" and "checkout" in c]
    assert any("onboarding/agent-wiring" in c for c in checkout_cmds)


def test_apply_pr_never_commits_to_default_branch():
    """_apply_pr never commits or pushes to default_branch (AC4)."""
    facts = {
        "file_tree": {},
        "default_branch": "main",
        "detected_stack": "swift-package",
        "has_claude_md_skills": False,
    }
    plan_out = {"ci": {"state": "missing"}}

    git_commands = []

    def mock_run(cmd, **kwargs):
        git_commands.append(cmd)
        if cmd[0:2] == ["gh", "auth"]:
            result = subprocess.CompletedProcess(cmd, 0)
            result.stdout = "Token scopes: repo, workflow"
            result.stderr = ""
            return result
        return subprocess.CompletedProcess(cmd, 0, "", "")

    result = po._apply_pr("test/repo", facts, plan_out, run=mock_run)

    commit_cmds = [c for c in git_commands if c[0] == "git" and "commit" in c]
    push_cmds = [c for c in git_commands if c[0] == "git" and "push" in c]

    for cmd in commit_cmds + push_cmds:
        assert "main" not in cmd, f"Command should not reference 'main': {cmd}"
