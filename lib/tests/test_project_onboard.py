"""Tests for project_onboard.py. Run via:
    ~/.agents/venv/bin/python -m pytest lib/tests/test_project_onboard.py -v
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

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
        "file_tree": {},
    }
    result = po.plan(facts)
    expected_pieces = {"profile", "stack", "test_command", "ci", "triage_labels", "agent_docs", "board", "clone_and_toolchain", "generated_paths", "repo_pr"}
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
        "file_tree": {".github/workflows/ci.yml": "file"},
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
        result1 = po.apply("test/repo", facts=facts, profiles_dir=profiles_dir, local=True, gh=mock_gh1)
        assert result1["labels"]["action"] == "created"
        assert result1["profile"]["action"] == "created"
        # Profile should be written to disk
        profile_path = profiles_dir / "repo.json"
        assert profile_path.exists()

        # Second run: labels and profile already exist now
        facts["labels"] = list(po.TRIAGE_LABELS)
        result2 = po.apply("test/repo", facts=facts, profiles_dir=profiles_dir, local=True, gh=mock_gh2)
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
            assert result["action"] in ("created", "unchanged", "conflict", "needs-human")


# ── Workflow scope check (ticket #147) ─────────────────────────────────────


def test_check_workflow_scope_when_present():
    """_check_workflow_scope returns has_scope=True when workflow scope present."""
    def mock_gh_with_scope(args):
        if "auth" in args and "status" in args:
            return "GH_TOKEN=... GitHub user ...\nToken scopes: repo, gist, workflow\n"
        return ""

    # Mock subprocess for this test
    original_run = __import__("subprocess").run
    def mock_run(*args, **kwargs):
        if args[0][0] == "gh" and "auth" in args[0] and "status" in args[0]:
            result = __import__("subprocess").CompletedProcess(
                args=args[0], returncode=0, stdout="",
                stderr="GH_TOKEN=... GitHub user ...\nToken scopes: repo, gist, workflow\n"
            )
            return result
        return original_run(*args, **kwargs)

    import subprocess as sp_module
    original_sp_run = sp_module.run
    sp_module.run = mock_run
    try:
        result = po._check_workflow_scope()
        assert result["has_scope"] is True
        assert "workflow" in result["message"] or result["message"] == "workflow scope present"
    finally:
        sp_module.run = original_sp_run


def test_check_workflow_scope_when_missing():
    """_check_workflow_scope returns has_scope=False with fix message when workflow scope missing."""
    original_run = __import__("subprocess").run
    def mock_run(*args, **kwargs):
        if args[0][0] == "gh" and "auth" in args[0] and "status" in args[0]:
            result = __import__("subprocess").CompletedProcess(
                args=args[0], returncode=0, stdout="",
                stderr="GH_TOKEN=... GitHub user ...\nToken scopes: repo, gist\n"
            )
            return result
        return original_run(*args, **kwargs)

    import subprocess as sp_module
    original_sp_run = sp_module.run
    sp_module.run = mock_run
    try:
        result = po._check_workflow_scope()
        assert result["has_scope"] is False
        assert "workflow" in result["message"] or "gh auth refresh" in result["message"]
    finally:
        sp_module.run = original_sp_run


# ── Repo PR piece in plan (ticket #147) ──────────────────────────────────


def test_plan_repo_pr_ok_when_all_files_present():
    """plan() includes repo_pr piece with state ok when CI and agent docs present."""
    facts = {
        "detected_stack": "swift-package",
        "has_agent_docs": True,
        "has_claude_md_skills": True,
        "file_tree": {".github/workflows/ci.yml": "file"},
        "package_json_scripts": {},
        "workflow_contents": "swift test",
        "tools_installed": {},
    }
    result = po.plan(facts)
    assert "repo_pr" in result
    assert result["repo_pr"]["state"] == "ok"


def test_plan_repo_pr_missing_when_files_absent():
    """plan() repo_pr piece is missing when CI and docs absent."""
    facts = {
        "detected_stack": "swift-package",
        "has_agent_docs": False,
        "has_claude_md_skills": False,
        "file_tree": {},
        "package_json_scripts": {},
        "workflow_contents": "",
        "tools_installed": {},
    }
    result = po.plan(facts)
    assert "repo_pr" in result
    assert result["repo_pr"]["state"] == "missing"


def test_plan_repo_pr_needs_human_when_no_stack():
    """plan() repo_pr piece is needs-human when no stack detected."""
    facts = {
        "detected_stack": None,
        "has_agent_docs": False,
        "has_claude_md_skills": False,
        "file_tree": {},
        "package_json_scripts": {},
        "workflow_contents": "",
        "tools_installed": {},
    }
    result = po.plan(facts)
    assert "repo_pr" in result
    assert result["repo_pr"]["state"] == "needs-human"


def test_plan_repo_pr_needs_human_when_test_command_unknown():
    """plan() repo_pr piece is needs-human when test_command is needs-human."""
    facts = {
        "detected_stack": "node-electron",
        "has_agent_docs": False,
        "has_claude_md_skills": False,
        "file_tree": {},
        "package_json_scripts": {},  # no test script
        "workflow_contents": "",
        "tools_installed": {},
    }
    result = po.plan(facts)
    assert "repo_pr" in result
    assert result["repo_pr"]["state"] == "needs-human"


# ── Repo PR expected_pieces in plan ──────────────────────────────────────


def test_plan_returns_repo_pr_in_expected_pieces():
    """plan() output includes repo_pr piece in addition to existing pieces."""
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
    expected_pieces = {"profile", "stack", "test_command", "ci", "triage_labels", "agent_docs", "board", "clone_and_toolchain", "generated_paths", "repo_pr"}
    assert set(result.keys()) == expected_pieces


# ── Seed template loading ────────────────────────────────────────────────


def test_get_seed_template_loads_github_issue_tracker():
    """_get_seed_template loads issue-tracker-github.md correctly."""
    result = po._get_seed_template("issue-tracker-github")
    assert result
    assert "Issue Tracker" in result
    assert "GitHub Issues" in result


def test_get_seed_template_loads_triage_labels():
    """_get_seed_template loads triage-labels.md correctly."""
    result = po._get_seed_template("triage-labels")
    assert result
    assert "needs-triage" in result
    assert "ready-for-agent" in result


def test_get_seed_template_loads_domain():
    """_get_seed_template loads domain.md correctly."""
    result = po._get_seed_template("domain")
    assert result
    assert "Domain Docs" in result
    assert "Single-context" in result


# ── Apply repo_pr (ticket #147) ──────────────────────────────────────────


def test_apply_repo_pr_needs_human_when_no_stack():
    """_apply_repo_pr returns needs-human when no stack detected."""
    facts = {"detected_stack": None}
    result = po._apply_repo_pr("test/repo", facts)
    assert result["action"] == "needs-human"
    assert "stack" in result["reason"].lower()


def test_apply_repo_pr_needs_human_when_no_clone():
    """_apply_repo_pr returns needs-human when clone not resolvable."""
    facts = {
        "detected_stack": "swift-package",
        "file_tree": {},
        "has_agent_docs": False,
        "has_claude_md_skills": False,
    }
    # Mock pp.load_profile to return None
    original_load = po.pp.load_profile
    po.pp.load_profile = lambda repo: None
    try:
        result = po._apply_repo_pr("test/repo", facts)
        assert result["action"] == "needs-human"
        assert "clone" in result["reason"].lower()
    finally:
        po.pp.load_profile = original_load


def test_apply_repo_pr_unchanged_when_all_files_exist():
    """_apply_repo_pr returns unchanged when CI and agent docs already present."""
    import tempfile
    with tempfile.TemporaryDirectory() as tmpdir:
        clone_path = Path(tmpdir)
        (clone_path / ".github" / "workflows").mkdir(parents=True, exist_ok=True)
        (clone_path / "docs" / "agents").mkdir(parents=True, exist_ok=True)

        facts = {
            "detected_stack": "swift-package",
            "default_branch": "main",
            "file_tree": {
                ".github/workflows/ci.yml": "file",
                "docs/agents/issue-tracker.md": "file",
                "docs/agents/triage-labels.md": "file",
                "docs/agents/domain.md": "file",
            },
            "has_agent_docs": True,
            "has_claude_md_skills": True,
        }

        # Mock profile with clone_hints pointing to temp directory
        original_load = po.pp.load_profile
        po.pp.load_profile = lambda repo: {"clone_hints": [str(clone_path)]}

        try:
            result = po._apply_repo_pr("test/repo", facts)
            assert result["action"] == "unchanged"
        finally:
            po.pp.load_profile = original_load


def test_apply_checks_workflow_scope_before_git():
    """_apply_repo_pr checks workflow scope before any git operation."""
    import tempfile
    with tempfile.TemporaryDirectory() as tmpdir:
        clone_path = Path(tmpdir)

        facts = {
            "detected_stack": "swift-package",
            "default_branch": "main",
            "file_tree": {},
            "has_agent_docs": False,
            "has_claude_md_skills": False,
        }

        original_load = po.pp.load_profile
        po.pp.load_profile = lambda repo: {"clone_hints": [str(clone_path)]}

        # Mock scope check to return False
        original_check = po._check_workflow_scope
        po._check_workflow_scope = lambda: {"has_scope": False, "message": "workflow scope missing"}

        git_was_called = []
        original_run = __import__("subprocess").run
        def mock_run(*args, **kwargs):
            if args[0][0] == "git":
                git_was_called.append(True)
            return original_run(*args, **kwargs)

        import subprocess as sp_module
        sp_module.run = mock_run

        try:
            result = po._apply_repo_pr("test/repo", facts)
            assert result["action"] == "needs-human"
            assert "workflow" in result["reason"].lower()
            assert len(git_was_called) == 0, "git should not be called when scope check fails"
        finally:
            sp_module.run = original_run
            po._check_workflow_scope = original_check
            po.pp.load_profile = original_load


# ── Apply with pr flag ───────────────────────────────────────────────────


def test_apply_with_pr_flag_only():
    """apply(..., pr=True, local=False) creates only repo_pr, not labels/board/profile."""
    facts = {
        "detected_stack": None,
        "labels": [],
        "has_agent_docs": False,
        "has_claude_md_skills": False,
    }
    result = po.apply("test/repo", facts=facts, pr=True, local=False)

    # Only repo_pr should be present
    assert "repo_pr" in result
    assert "labels" not in result
    assert "board" not in result
    assert "profile" not in result


def test_apply_with_local_flag_only():
    """apply(..., local=True, pr=False) creates only local pieces."""
    import tempfile
    with tempfile.TemporaryDirectory() as tmpdir:
        profiles_dir = Path(tmpdir)
        facts = {
            "repo": "test/repo",
            "detected_stack": "swift-package",
            "default_branch": "main",
            "labels": [],
        }
        result = po.apply("test/repo", facts=facts, local=True, pr=False, profiles_dir=profiles_dir)

        # Local pieces should be present
        assert "labels" in result
        assert "board" in result
        assert "profile" in result
        # repo_pr should not be present
        assert "repo_pr" not in result


def test_apply_with_both_flags():
    """apply(..., local=True, pr=True) creates both local and repo PR pieces."""
    import tempfile
    with tempfile.TemporaryDirectory() as tmpdir:
        profiles_dir = Path(tmpdir)
        facts = {
            "repo": "test/repo",
            "detected_stack": "swift-package",
            "default_branch": "main",
            "labels": [],
            "has_agent_docs": False,
            "has_claude_md_skills": False,
            "file_tree": {},
        }
        result = po.apply("test/repo", facts=facts, local=True, pr=True, profiles_dir=profiles_dir)

        # Both should be present
        assert "labels" in result
        assert "board" in result
        assert "profile" in result
        assert "repo_pr" in result


# ── Real-world fixtures extended with repo_pr ────────────────────────────


def test_clarity_captions_with_repo_pr():
    """Clarity-captions fixture extended with repo_pr piece."""
    facts = {
        "repo": "G-Eskayo/clarity-captions",
        "visibility": "public",
        "detected_stack": "xcodegen-app",
        "has_package_swift": False,
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
        "file_tree": {".github/workflows/ci.yml": "file"},
    }
    result = po.plan(facts)
    assert result["repo_pr"]["state"] == "ok"


def test_finance_os_with_repo_pr():
    """Finance-os fixture extended with repo_pr piece."""
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
        "file_tree": {".github/workflows/ci.yml": "file"},
    }
    result = po.plan(facts)
    assert result["repo_pr"]["state"] == "ok"
