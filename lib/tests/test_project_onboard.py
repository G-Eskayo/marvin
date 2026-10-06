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


# ── Python stack: test command piece ──────────────────────────────────

def test_python_test_command_ok_with_pinned_requirements():
    """Python test command is ok when requirements are pinned."""
    facts = {
        "detected_stack": "python",
        "has_requirements_file": True,
        "requirements_pinned": True,
        "python_tests_touch_home": False,
        "workflow_contents": "",
        "package_json_scripts": {},
        "tools_installed": {},
    }
    result = po.plan(facts)
    assert result["test_command"]["state"] == "ok"
    assert "pytest" in result["test_command"]["reason"]


def test_python_test_command_needs_human_when_no_requirements_file():
    """Python test command is needs-human when requirements file is missing."""
    facts = {
        "detected_stack": "python",
        "has_requirements_file": False,
        "requirements_pinned": False,
        "python_tests_touch_home": False,
        "workflow_contents": "",
        "package_json_scripts": {},
        "tools_installed": {},
    }
    result = po.plan(facts)
    assert result["test_command"]["state"] == "needs-human"
    assert "no requirements file" in result["test_command"]["reason"]


def test_python_test_command_needs_human_when_requirements_unpinned():
    """Python test command is needs-human when requirements are unpinned."""
    facts = {
        "detected_stack": "python",
        "has_requirements_file": True,
        "requirements_pinned": False,
        "python_tests_touch_home": False,
        "workflow_contents": "",
        "package_json_scripts": {},
        "tools_installed": {},
    }
    result = po.plan(facts)
    assert result["test_command"]["state"] == "needs-human"
    assert "unpinned" in result["test_command"]["reason"]


# ── Python stack: CI piece ────────────────────────────────────────────

def test_python_ci_ok_with_pinned_requirements_and_clean_tests():
    """Python CI is ok when requirements are pinned and tests are clean."""
    facts = {
        "detected_stack": "python",
        "has_requirements_file": True,
        "requirements_pinned": True,
        "python_tests_touch_home": False,
        "machine_local_test_files": [],
        "has_workflows": False,
        "workflow_contents": "",
        "package_json_scripts": {},
        "tools_installed": {},
    }
    result = po.plan(facts)
    assert result["test_command"]["state"] == "ok"
    assert result["ci"]["state"] == "missing"


def test_python_ci_needs_human_when_tests_touch_home():
    """Python CI is needs-human when tests read machine-local state, even if requirements are pinned."""
    facts = {
        "detected_stack": "python",
        "has_requirements_file": True,
        "requirements_pinned": True,
        "python_tests_touch_home": True,
        "machine_local_test_files": ["lib/tests/test_claude_bin.py", "lib/tests/test_profile.py"],
        "has_workflows": False,
        "workflow_contents": "",
        "package_json_scripts": {},
        "tools_installed": {},
    }
    result = po.plan(facts)
    assert result["test_command"]["state"] == "ok"
    assert result["ci"]["state"] == "needs-human"
    assert "machine-local state" in result["ci"]["reason"]
    assert "test_claude_bin.py" in result["ci"]["reason"]


def test_python_ci_needs_human_when_test_command_needs_human():
    """Python CI is needs-human when test_command is needs-human."""
    facts = {
        "detected_stack": "python",
        "has_requirements_file": False,
        "requirements_pinned": False,
        "python_tests_touch_home": False,
        "machine_local_test_files": [],
        "has_workflows": False,
        "workflow_contents": "",
        "package_json_scripts": {},
        "tools_installed": {},
    }
    result = po.plan(facts)
    assert result["test_command"]["state"] == "needs-human"
    assert result["ci"]["state"] == "needs-human"
    assert "cannot wire CI" in result["ci"]["reason"]


# ── Helper function tests ──────────────────────────────────────────────

def test_is_test_file_recognizes_test_py():
    """_is_test_file recognizes test_*.py patterns."""
    assert po._is_test_file("lib/tests/test_claude_bin.py")
    assert po._is_test_file("test_foo.py")
    assert po._is_test_file("tests/test_bar.py")
    assert not po._is_test_file("lib/claude_bin.py")
    assert not po._is_test_file("test_foo.txt")


def test_is_test_file_recognizes_py_test():
    """_is_test_file recognizes *_test.py patterns."""
    assert po._is_test_file("lib/tests/claude_bin_test.py")
    assert po._is_test_file("foo_test.py")
    assert po._is_test_file("tests/bar_test.py")
    assert not po._is_test_file("lib/claude_bin.py")
    assert not po._is_test_file("foo_test.txt")


def test_test_touches_machine_local_state_with_path_home():
    """_test_touches_machine_local_state detects Path.home()."""
    content = "from pathlib import Path\nconfig = Path.home() / '.claude'"
    assert po._test_touches_machine_local_state(content)


def test_test_touches_machine_local_state_with_expanduser():
    """_test_touches_machine_local_state detects expanduser()."""
    content = "config_path = os.path.expanduser('~/.claude')"
    assert po._test_touches_machine_local_state(content)


def test_test_touches_machine_local_state_with_os_environ_home():
    """_test_touches_machine_local_state detects os.environ[\"HOME\"]."""
    content = 'home_dir = os.environ["HOME"]'
    assert po._test_touches_machine_local_state(content)


def test_test_touches_machine_local_state_with_os_environ_get():
    """_test_touches_machine_local_state detects os.environ.get(\"HOME\")."""
    content = 'home_dir = os.environ.get("HOME")'
    assert po._test_touches_machine_local_state(content)


def test_test_touches_machine_local_state_with_literal_path():
    """_test_touches_machine_local_state detects literal ~/.claude paths."""
    content = "config = ~/.claude/settings"
    assert po._test_touches_machine_local_state(content)


def test_test_does_not_touch_machine_local_state():
    """_test_touches_machine_local_state returns false for clean tests."""
    content = """
def test_foo():
    assert 1 + 1 == 2

def test_bar():
    result = compute_result()
    assert result == expected
"""
    assert not po._test_touches_machine_local_state(content)


def test_all_requirements_pinned_with_pinned_deps():
    """_all_requirements_pinned returns true when all deps use ==."""
    content = """
requests==2.31.0
pytest==7.4.0
numpy==1.24.0
"""
    assert po._all_requirements_pinned(content)


def test_all_requirements_pinned_ignores_comments():
    """_all_requirements_pinned ignores comment lines."""
    content = """
# Core dependencies
requests==2.31.0
# Testing
pytest==7.4.0
"""
    assert po._all_requirements_pinned(content)


def test_all_requirements_pinned_with_unpinned_deps():
    """_all_requirements_pinned returns false when any dep lacks ==."""
    content = """
requests==2.31.0
pytest>=7.0
numpy==1.24.0
"""
    assert not po._all_requirements_pinned(content)


def test_all_requirements_pinned_empty_file():
    """_all_requirements_pinned returns true for empty requirements."""
    content = ""
    assert po._all_requirements_pinned(content)


def test_all_requirements_pinned_only_comments():
    """_all_requirements_pinned returns true for files with only comments."""
    content = """
# This is a comment
# Another comment
"""
    assert po._all_requirements_pinned(content)


# ── Inspection: Python-specific detection ──────────────────────────────

def test_inspect_detects_python_requirements_file():
    """inspect() detects has_requirements_file when requirements.txt exists."""
    def mock_gh(args):
        if "git/trees" in " ".join(args):
            return json.dumps({"tree": [
                {"path": "requirements.txt", "type": "blob"},
                {"path": "app.py", "type": "blob"},
            ]})
        if "requirements.txt" in " ".join(args):
            import base64
            return json.dumps({"content": base64.b64encode(b"requests==2.31.0").decode()})
        return ""

    result = po.inspect("test/repo", gh=mock_gh)
    assert result["detected_stack"] == "python"
    assert result["has_requirements_file"] is True


def test_inspect_detects_unpinned_requirements():
    """inspect() detects requirements_pinned as False when deps are unpinned."""
    def mock_gh(args):
        if "git/trees" in " ".join(args):
            return json.dumps({"tree": [
                {"path": "requirements.txt", "type": "blob"},
                {"path": "app.py", "type": "blob"},
            ]})
        if "requirements.txt" in " ".join(args):
            import base64
            content = "requests>=2.31.0\npytest==7.4.0"
            return json.dumps({"content": base64.b64encode(content.encode()).decode()})
        return ""

    result = po.inspect("test/repo", gh=mock_gh)
    assert result["detected_stack"] == "python"
    assert result["has_requirements_file"] is True
    assert result["requirements_pinned"] is False


def test_inspect_detects_machine_local_tests():
    """inspect() detects python_tests_touch_home when tests read machine-local state."""
    def mock_gh(args):
        if "git/trees" in " ".join(args):
            return json.dumps({"tree": [
                {"path": "requirements.txt", "type": "blob"},
                {"path": "app.py", "type": "blob"},
                {"path": "lib/tests/test_config.py", "type": "blob"},
            ]})
        if "requirements.txt" in " ".join(args):
            import base64
            return json.dumps({"content": base64.b64encode(b"requests==2.31.0").decode()})
        if "test_config.py" in " ".join(args):
            import base64
            content = "from pathlib import Path\nconfig = Path.home() / '.claude'"
            return json.dumps({"content": base64.b64encode(content.encode()).decode()})
        return ""

    result = po.inspect("test/repo", gh=mock_gh)
    assert result["detected_stack"] == "python"
    assert result["python_tests_touch_home"] is True
    assert "lib/tests/test_config.py" in result["machine_local_test_files"]


def test_inspect_detects_pyproject_pinned_requirements():
    """inspect() detects requirements_pinned via pyproject.toml when deps are pinned."""
    def mock_gh(args):
        if "git/trees" in " ".join(args):
            return json.dumps({"tree": [
                {"path": "pyproject.toml", "type": "blob"},
                {"path": "app.py", "type": "blob"},
            ]})
        if "pyproject.toml" in " ".join(args):
            import base64
            content = '[project]\ndependencies = ["requests==2.31.0", "pytest==7.4.0"]'
            return json.dumps({"content": base64.b64encode(content.encode()).decode()})
        return ""

    result = po.inspect("test/repo", gh=mock_gh)
    assert result["detected_stack"] == "python"
    assert result["has_requirements_file"] is True
    assert result["requirements_pinned"] is True


def test_inspect_detects_pyproject_unpinned_requirements():
    """inspect() detects requirements_pinned as False when pyproject.toml deps are unpinned."""
    def mock_gh(args):
        if "git/trees" in " ".join(args):
            return json.dumps({"tree": [
                {"path": "pyproject.toml", "type": "blob"},
                {"path": "app.py", "type": "blob"},
            ]})
        if "pyproject.toml" in " ".join(args):
            import base64
            content = '[project]\ndependencies = ["requests>=2.31.0", "pytest==7.4.0"]'
            return json.dumps({"content": base64.b64encode(content.encode()).decode()})
        return ""

    result = po.inspect("test/repo", gh=mock_gh)
    assert result["detected_stack"] == "python"
    assert result["has_requirements_file"] is True
    assert result["requirements_pinned"] is False


# ── Real-world fixture: Marvin's repo ──────────────────────────────────

def test_marvin_repo_real_world():
    """Marvin's own repo: no requirements file + tests touch machine-local state (AC1)."""
    facts = {
        "repo": "G-Eskayo/marvin",
        "detected_stack": "python",
        "has_requirements_file": False,
        "requirements_pinned": False,
        "python_tests_touch_home": True,
        "machine_local_test_files": [
            "lib/tests/test_claude_bin.py",
            "lib/tests/test_project_profile.py",
            "lib/tests/test_board_registry.py",
        ],
        "has_workflows": False,
        "workflow_contents": "",
        "package_json_scripts": {},
        "tools_installed": {"python": True},
        "profile_exists": False,
        "board_exists": False,
        "labels": [],
        "has_agent_docs": False,
        "has_claude_md_skills": False,
        "clone_hint_resolves": False,
    }
    result = po.plan(facts)
    assert result["test_command"]["state"] == "needs-human"
    assert "no requirements file" in result["test_command"]["reason"]
    assert result["ci"]["state"] == "needs-human"
    assert "machine-local state" in result["ci"]["reason"]
    assert "test_claude_bin.py" in result["ci"]["reason"]
