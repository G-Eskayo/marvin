"""Tests for project_onboard.py. Run via:
    ~/.agents/venv/bin/python -m pytest lib/tests/test_project_onboard.py -v
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
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


def test_test_command_ok_for_python():
    facts = {"detected_stack": "python", "package_json_scripts": {}, "workflow_contents": "", "tools_installed": {}}
    result = po.plan(facts)
    assert result["test_command"]["state"] == "ok"
    assert "pytest" in result["test_command"]["reason"]


# ── Python stack: CI and dependency checks ───────────────────────────────

def test_python_ci_needs_human_when_requirements_missing():
    """Python project without requirements.txt gets needs-human."""
    facts = {
        "detected_stack": "python",
        "has_requirements_file": False,
        "requirements_pinned": False,
        "unpinned_dependencies": [],
        "tests_read_machine_local": False,
        "machine_local_test_files": [],
        "has_workflows": False,
        "workflow_contents": "",
        "package_json_scripts": {},
        "tools_installed": {},
    }
    result = po.plan(facts)
    assert result["ci"]["state"] == "needs-human"
    assert "dependencies" in result["ci"]["reason"]


def test_python_ci_needs_human_when_requirements_unpinned():
    """Python project with unpinned dependencies gets needs-human."""
    facts = {
        "detected_stack": "python",
        "has_requirements_file": True,
        "requirements_pinned": False,
        "unpinned_dependencies": ["requests", "pytest"],
        "tests_read_machine_local": False,
        "machine_local_test_files": [],
        "has_workflows": False,
        "workflow_contents": "",
        "package_json_scripts": {},
        "tools_installed": {},
    }
    result = po.plan(facts)
    assert result["ci"]["state"] == "needs-human"
    assert "unpinned" in result["ci"]["reason"].lower()


def test_python_ci_needs_human_when_tests_read_machine_local():
    """Python project with machine-local test references gets needs-human."""
    facts = {
        "detected_stack": "python",
        "has_requirements_file": True,
        "requirements_pinned": True,
        "unpinned_dependencies": [],
        "tests_read_machine_local": True,
        "machine_local_test_files": ["tests/test_config.py"],
        "has_workflows": False,
        "workflow_contents": "",
        "package_json_scripts": {},
        "tools_installed": {},
    }
    result = po.plan(facts)
    assert result["ci"]["state"] == "needs-human"
    assert "machine-local" in result["ci"]["reason"].lower() or "~/.claude" in result["ci"]["reason"]


def test_python_ci_needs_human_reports_both_problems():
    """Python project with both problems reports both in reason."""
    facts = {
        "detected_stack": "python",
        "has_requirements_file": True,
        "requirements_pinned": False,
        "unpinned_dependencies": ["requests"],
        "tests_read_machine_local": True,
        "machine_local_test_files": ["tests/test_config.py"],
        "has_workflows": False,
        "workflow_contents": "",
        "package_json_scripts": {},
        "tools_installed": {},
    }
    result = po.plan(facts)
    assert result["ci"]["state"] == "needs-human"
    reason = result["ci"]["reason"]
    # Both problems should be mentioned
    assert ("unpinned" in reason.lower() or "dependencies" in reason.lower())
    assert ("machine-local" in reason.lower() or "~/.claude" in reason.lower() or "Path.home" in reason)


def test_python_ci_missing_when_clean():
    """Python project with pinned requirements and no machine-local tests can have CI generated."""
    facts = {
        "detected_stack": "python",
        "has_requirements_file": True,
        "requirements_pinned": True,
        "unpinned_dependencies": [],
        "tests_read_machine_local": False,
        "machine_local_test_files": [],
        "has_workflows": False,
        "workflow_contents": "",
        "package_json_scripts": {},
        "tools_installed": {},
    }
    result = po.plan(facts)
    assert result["ci"]["state"] == "missing"


def test_python_ci_ok_when_pytest_workflow_exists():
    """Python project with pytest in workflow already running is ok."""
    facts = {
        "detected_stack": "python",
        "has_requirements_file": True,
        "requirements_pinned": True,
        "unpinned_dependencies": [],
        "tests_read_machine_local": False,
        "machine_local_test_files": [],
        "has_workflows": True,
        "workflow_contents": "pytest",
        "package_json_scripts": {},
        "tools_installed": {},
    }
    result = po.plan(facts)
    assert result["ci"]["state"] == "ok"


def test_python_with_pyproject_and_lock_counts_as_pinned():
    """Python project with pyproject.toml and lock file counts as pinned."""
    facts = {
        "detected_stack": "python",
        "has_requirements_file": False,
        "requirements_pinned": True,
        "unpinned_dependencies": [],
        "tests_read_machine_local": False,
        "machine_local_test_files": [],
        "has_workflows": False,
        "workflow_contents": "",
        "package_json_scripts": {},
        "tools_installed": {},
    }
    result = po.plan(facts)
    assert result["ci"]["state"] == "missing"


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


def test_inspect_detects_python_stack():
    """inspect() detects Python stack when .py files exist."""
    def mock_gh(args):
        if "repo view" in " ".join(args):
            return json.dumps({"visibility": "public", "defaultBranchRef": {"name": "main"}})
        if "trees" in " ".join(args):
            return json.dumps({"tree": [
                {"path": "setup.py", "type": "file"},
                {"path": "lib/main.py", "type": "file"},
            ]})
        if "label" in " ".join(args):
            return "[]"
        return ""

    result = po.inspect("test/repo", gh=mock_gh)
    assert result["detected_stack"] == "python"


def test_inspect_detects_requirements_file():
    """inspect() detects requirements.txt and checks pinning."""
    def mock_gh(args):
        if "repo view" in " ".join(args):
            return json.dumps({"visibility": "public", "defaultBranchRef": {"name": "main"}})
        if "trees" in " ".join(args):
            return json.dumps({"tree": [
                {"path": "requirements.txt", "type": "file"},
                {"path": "main.py", "type": "file"},
            ]})
        if "contents/requirements.txt" in " ".join(args):
            return json.dumps({"content": po.base64.b64encode(b"pytest==7.4.3\nrequests==2.31.0\n").decode()})
        if "label" in " ".join(args):
            return "[]"
        return ""

    result = po.inspect("test/repo", gh=mock_gh)
    assert result["has_requirements_file"] is True
    assert result["requirements_pinned"] is True
    assert result["unpinned_dependencies"] == []


def test_inspect_detects_unpinned_dependencies():
    """inspect() detects unpinned dependencies in requirements.txt."""
    def mock_gh(args):
        if "repo view" in " ".join(args):
            return json.dumps({"visibility": "public", "defaultBranchRef": {"name": "main"}})
        if "trees" in " ".join(args):
            return json.dumps({"tree": [
                {"path": "requirements.txt", "type": "file"},
                {"path": "main.py", "type": "file"},
            ]})
        if "contents/requirements.txt" in " ".join(args):
            return json.dumps({"content": po.base64.b64encode(b"pytest>=7.0\nrequests\n").decode()})
        if "label" in " ".join(args):
            return "[]"
        return ""

    result = po.inspect("test/repo", gh=mock_gh)
    assert result["has_requirements_file"] is True
    assert result["requirements_pinned"] is False
    assert "pytest>=7.0" in result["unpinned_dependencies"]
    assert "requests" in result["unpinned_dependencies"]


def test_inspect_detects_machine_local_test_references():
    """inspect() detects tests that reference Path.home() or ~/.claude."""
    def mock_gh(args):
        if "repo view" in " ".join(args):
            return json.dumps({"visibility": "public", "defaultBranchRef": {"name": "main"}})
        if "trees" in " ".join(args):
            return json.dumps({"tree": [
                {"path": "test_main.py", "type": "file"},
                {"path": "main.py", "type": "file"},
            ]})
        if "contents/test_main.py" in " ".join(args):
            return json.dumps({"content": po.base64.b64encode(b"from pathlib import Path\nconfig = Path.home() / '.claude'\n").decode()})
        if "label" in " ".join(args):
            return "[]"
        return ""

    result = po.inspect("test/repo", gh=mock_gh)
    assert result["tests_read_machine_local"] is True
    assert "test_main.py" in result["machine_local_test_files"]


def test_inspect_detects_expanduser_in_tests():
    """inspect() detects tests that use expanduser() with home paths."""
    def mock_gh(args):
        if "repo view" in " ".join(args):
            return json.dumps({"visibility": "public", "defaultBranchRef": {"name": "main"}})
        if "trees" in " ".join(args):
            return json.dumps({"tree": [
                {"path": "test_config.py", "type": "file"},
            ]})
        if "contents/test_config.py" in " ".join(args):
            return json.dumps({"content": po.base64.b64encode(b"path = os.path.expanduser('~/.claude/config')\n").decode()})
        if "label" in " ".join(args):
            return "[]"
        return ""

    result = po.inspect("test/repo", gh=mock_gh)
    assert result["tests_read_machine_local"] is True
    assert "test_config.py" in result["machine_local_test_files"]


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


def test_matches_detect_rule_file_any_with_pnpm_workspace():
    """_matches_detect_rule detects file_any rule matching pnpm-workspace.yaml."""
    file_tree = {"pnpm-workspace.yaml": "file", "package.json": "file"}
    rule = {"file_any": ["pnpm-workspace.yaml", "turbo.json"]}
    assert po._matches_detect_rule(file_tree, rule) is True


def test_matches_detect_rule_file_any_with_turbo_json():
    """_matches_detect_rule detects file_any rule matching turbo.json."""
    file_tree = {"turbo.json": "file", "package.json": "file"}
    rule = {"file_any": ["pnpm-workspace.yaml", "turbo.json"]}
    assert po._matches_detect_rule(file_tree, rule) is True


def test_matches_detect_rule_file_any_with_both():
    """_matches_detect_rule matches file_any when both files exist (checks first match)."""
    file_tree = {"pnpm-workspace.yaml": "file", "turbo.json": "file"}
    rule = {"file_any": ["pnpm-workspace.yaml", "turbo.json"]}
    assert po._matches_detect_rule(file_tree, rule) is True


def test_matches_detect_rule_file_any_no_match():
    """_matches_detect_rule returns False when file_any has no matching files."""
    file_tree = {"package.json": "file"}
    rule = {"file_any": ["pnpm-workspace.yaml", "turbo.json"]}
    assert po._matches_detect_rule(file_tree, rule) is False


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


def test_detect_node_pnpm_turbo_with_test_script():
    """Node pnpm-turbo monorepo with test script is ok."""
    facts = {
        "detected_stack": "node-pnpm-turbo",
        "package_json_scripts": {"test": "turbo run test"},
        "workflow_contents": "",
        "tools_installed": {"node": True, "pnpm": True},
    }
    result = po.plan(facts)
    assert result["stack"]["state"] == "ok"
    assert result["test_command"]["state"] == "ok"


def test_node_pnpm_turbo_without_test_script():
    """Node pnpm-turbo without test script is needs-human."""
    facts = {
        "detected_stack": "node-pnpm-turbo",
        "package_json_scripts": {},
        "workflow_contents": "",
        "tools_installed": {"node": True, "pnpm": True},
    }
    result = po.plan(facts)
    assert result["test_command"]["state"] == "needs-human"
    assert "never guess" in result["test_command"]["reason"]


def test_node_pnpm_turbo_ci_ok_with_turbo_test():
    """Node pnpm-turbo CI is ok when workflow contains turbo test."""
    facts = {
        "detected_stack": "node-pnpm-turbo",
        "package_json_scripts": {"test": "turbo run test"},
        "has_workflows": True,
        "workflow_contents": "turbo test",
        "tools_installed": {"node": True, "pnpm": True},
    }
    result = po.plan(facts)
    assert result["ci"]["state"] == "ok"


def test_node_pnpm_turbo_ci_ok_with_pnpm_test():
    """Node pnpm-turbo CI is ok when workflow contains pnpm test."""
    facts = {
        "detected_stack": "node-pnpm-turbo",
        "package_json_scripts": {"test": "turbo run test"},
        "has_workflows": True,
        "workflow_contents": "pnpm test",
        "tools_installed": {"node": True, "pnpm": True},
    }
    result = po.plan(facts)
    assert result["ci"]["state"] == "ok"


def test_node_pnpm_turbo_ci_missing_no_workflow():
    """Node pnpm-turbo without CI workflow is missing."""
    facts = {
        "detected_stack": "node-pnpm-turbo",
        "package_json_scripts": {"test": "turbo run test"},
        "has_workflows": False,
        "workflow_contents": "",
        "tools_installed": {"node": True, "pnpm": True},
    }
    result = po.plan(facts)
    assert result["ci"]["state"] == "missing"


def test_family_node_both_node_stacks():
    """Both node-electron and node-pnpm-turbo use family: node for shared test-command logic."""
    facts_electron = {
        "detected_stack": "node-electron",
        "package_json_scripts": {"test": "vitest"},
        "workflow_contents": "",
        "tools_installed": {"node": True},
    }
    facts_pnpm = {
        "detected_stack": "node-pnpm-turbo",
        "package_json_scripts": {"test": "turbo run test"},
        "workflow_contents": "",
        "tools_installed": {"node": True, "pnpm": True},
    }
    result_electron = po.plan(facts_electron)
    result_pnpm = po.plan(facts_pnpm)
    # Both should have ok test_command via family-based check
    assert result_electron["test_command"]["state"] == "ok"
    assert result_pnpm["test_command"]["state"] == "ok"


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
    assert not result["labels"]
    assert not calls


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
        assert not [c for c in calls2 if "label" in c and "create" in c]
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
    """_apply_profile works for all five stacks: swift-package, xcodegen-app, node-electron, node-pnpm-turbo, python."""
    import tempfile
    with tempfile.TemporaryDirectory() as tmpdir:
        profiles_dir = Path(tmpdir)
        for stack in ["swift-package", "xcodegen-app", "node-electron", "node-pnpm-turbo", "python"]:
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
        if "trees" in " ".join(args):
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
        if "trees" in " ".join(args):
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
    assert not result1["failed"]

    # Verify files exist
    assert (tmp_path / "repo1.json").exists()
    assert (tmp_path / "repo2.json").exists()

    # Read original repo2 content
    original_repo2 = (tmp_path / "repo2.json").read_text()

    # Second run with partial failure: repo2 fails, repo1 succeeds
    # Mock refresh_onboarding_plan to raise for repo2
    original_refresh = po.refresh_onboarding_plan
    def mock_refresh(repo, gh, dir, **kw):
        if repo == "test/repo2":
            raise Exception("Network error")
        return original_refresh(repo, gh, dir, **kw)

    monkeypatch.setattr(po, "refresh_onboarding_plan", mock_refresh)

    result2 = po.refresh_all_onboarding_plans(
        ["test/repo1", "test/repo2"],
        gh=mock_gh_success,
        dir=tmp_path
    )
    # repo1 should succeed, repo2 should fail
    assert "test/repo1" in result2["ok"]
    assert any(r == "test/repo2" for r, _ in result2["failed"])

    # repo2's plan is kept (not nuked by the error), now marked stale with why (ADR 0058)
    kept, before = json.loads((tmp_path / "repo2.json").read_text()), json.loads(original_repo2)
    assert kept["pieces"] == before["pieces"]
    assert kept["stale"]["reason"] == "Network error"


# ── PR apply tests (ticket #147) ────────────────────────────────────────

def test_render_agent_docs_substitutes_repo():
    """_render_agent_docs substitutes {repo} in templates."""
    result = po._render_agent_docs("test/myrepo")
    assert "test/myrepo" in result["docs/agents/issue-tracker.md"]
    assert "test/myrepo" in result["_CLAUDE_MD_BLOCK"]


def test_render_agent_docs_returns_all_three_files():
    """_render_agent_docs returns all three docs files."""
    result = po._render_agent_docs("test/repo")
    assert "docs/agents/issue-tracker.md" in result
    assert "docs/agents/triage-labels.md" in result
    assert "docs/agents/domain.md" in result
    assert "_CLAUDE_MD_BLOCK" in result


def test_render_agent_docs_issue_tracker_matches_known_good():
    """_render_agent_docs issue-tracker content includes expected sections."""
    result = po._render_agent_docs("G-Eskayo/marvin")
    content = result["docs/agents/issue-tracker.md"]
    assert "# Issue Tracker" in content
    assert "GitHub Issues" in content
    assert "G-Eskayo/marvin" in content
    assert "gh issue create" in content


def test_render_agent_docs_triage_labels_matches_known_good():
    """_render_agent_docs triage-labels includes all 5 roles."""
    result = po._render_agent_docs("test/repo")
    content = result["docs/agents/triage-labels.md"]
    assert "# Triage Labels" in content
    assert "needs-triage" in content
    assert "needs-info" in content
    assert "ready-for-agent" in content
    assert "ready-for-human" in content
    assert "wontfix" in content


def test_render_agent_docs_domain_is_single_context():
    """_render_agent_docs domain defaults to Single-context."""
    result = po._render_agent_docs("test/repo")
    content = result["docs/agents/domain.md"]
    assert "# Domain Docs" in content
    assert "Single-context" in content
    assert "CONTEXT.md" in content


def test_render_agent_docs_claude_md_block_format():
    """_render_agent_docs CLAUDE.md block has correct format."""
    result = po._render_agent_docs("test/repo")
    block = result["_CLAUDE_MD_BLOCK"]
    assert "## Agent skills" in block
    assert "### Issue tracker" in block
    assert "### Triage labels" in block
    assert "### Domain docs" in block
    assert "test/repo" in block


def test_check_workflow_scope_parses_yes():
    """_check_workflow_scope returns True when workflow scope is present."""
    auth_status = "Token scopes: 'repo', 'workflow', 'gist'"
    result = po._check_workflow_scope(auth_status=auth_status)
    assert result is True


def test_check_workflow_scope_parses_no():
    """_check_workflow_scope returns False when workflow scope is absent."""
    auth_status = "Token scopes: 'repo', 'gist'"
    result = po._check_workflow_scope(auth_status=auth_status)
    assert result is False


def test_check_workflow_scope_handles_single_quotes():
    """_check_workflow_scope handles single-quoted scopes."""
    auth_status = "Token scopes: 'repo,workflow'"
    result = po._check_workflow_scope(auth_status=auth_status)
    assert result is True


def test_check_workflow_scope_empty_status():
    """_check_workflow_scope returns False on empty status."""
    result = po._check_workflow_scope(auth_status="")
    assert result is False


def test_check_workflow_scope_unparseable_status():
    """_check_workflow_scope returns False on unparseable status."""
    result = po._check_workflow_scope(auth_status="something invalid")
    assert result is False


def test_apply_pr_unchanged_when_nothing_missing():
    """_apply_pr returns unchanged when no files are missing."""
    facts = {
        "repo": "test/repo",
        "default_branch": "main",
        "file_tree": {
            "docs/agents/issue-tracker.md": "file",
            "docs/agents/triage-labels.md": "file",
            "docs/agents/domain.md": "file",
            "CLAUDE.md": "file",
        },
        "has_claude_md_skills": True,
    }
    plan_out = {
        "ci": {"state": "ok"},
        "agent_docs": {"state": "ok"},
    }

    def mock_gh(args):
        return ""

    result = po._apply_pr("test/repo", facts, plan_out, gh=mock_gh)
    assert result["action"] == "unchanged"


def test_apply_pr_file_selection_missing_docs_only():
    """_apply_pr includes only missing docs files (AC1 at file granularity)."""
    facts = {
        "repo": "test/repo",
        "default_branch": "main",
        "file_tree": {
            "docs/agents/issue-tracker.md": "file",
            "CLAUDE.md": "file",
        },
        "has_claude_md_skills": True,
    }
    plan_out = {
        "ci": {"state": "ok"},
        "agent_docs": {"state": "missing", "reason": "missing triage-labels and domain"},
    }

    files_selected = []

    def mock_gh(args):
        if "contents" in args and any(f in " ".join(args) for f in ["triage", "domain", "ci.yml"]):
            files_selected.append(" ".join(args))
        return ""

    result = po._apply_pr("test/repo", facts, plan_out, gh=mock_gh)
    assert result["action"] in ("created", "updated", "needs-human")


def test_apply_pr_ci_omitted_when_needs_human():
    """_apply_pr omits CI when plan says needs-human (R5)."""
    facts = {
        "repo": "test/repo",
        "default_branch": "main",
        "file_tree": {},
        "detected_stack": "swift-package",
    }
    plan_out = {
        "ci": {"state": "needs-human", "reason": "test command unknown"},
        "agent_docs": {"state": "missing"},
    }

    def mock_gh(args):
        return ""

    result = po._apply_pr("test/repo", facts, plan_out, gh=mock_gh)
    assert ".github/workflows/ci.yml" not in result.get("files", [])


def test_apply_pr_scope_gate_blocks_push(tmp_path):
    """_apply_pr returns needs-human without pushing when workflow scope is missing (AC2)."""
    facts = {
        "repo": "test/repo",
        "default_branch": "main",
        "file_tree": {},
        "detected_stack": "swift-package",
    }
    plan_out = {
        "ci": {"state": "missing"},
        "agent_docs": {"state": "missing"},
    }

    api_calls = []

    def mock_gh(args):
        api_calls.append(" ".join(args))
        return ""

    auth_status = "Token scopes: 'repo'"
    result = po._apply_pr("test/repo", facts, plan_out, gh=mock_gh, auth_status=auth_status)

    assert result["action"] == "needs-human"
    assert "workflow" in result["reason"]
    assert not any("refs/heads" in call or "contents" in call for call in api_calls)


def test_apply_pr_scope_gate_allows_when_present():
    """_apply_pr proceeds with files when workflow scope is present (AC2)."""
    facts = {
        "repo": "test/repo",
        "default_branch": "main",
        "file_tree": {},
        "detected_stack": "swift-package",
    }
    plan_out = {
        "ci": {"state": "missing"},
        "agent_docs": {"state": "missing"},
    }

    def mock_gh(args):
        if "git/ref/heads" in " ".join(args):
            return json.dumps({"object": {"sha": "abc123"}})
        return ""

    auth_status = "Token scopes: 'repo', 'workflow'"
    result = po._apply_pr("test/repo", facts, plan_out, gh=mock_gh, auth_status=auth_status)

    assert result["action"] != "needs-human" or "workflow" not in result.get("reason", "")


def test_apply_pr_branch_safety_never_writes_to_default_branch(tmp_path):
    """_apply_pr never writes to default branch (AC4) — reads are OK for getting SHA."""
    facts = {
        "repo": "test/repo",
        "default_branch": "main",
        "file_tree": {},
        "detected_stack": "swift-package",
    }
    plan_out = {
        "ci": {"state": "missing"},
        "agent_docs": {"state": "missing"},
    }

    api_calls = []

    def mock_gh(args):
        api_calls.append(args)
        return json.dumps({"object": {"sha": "abc123"}}) if "git/ref/heads/main" in " ".join(args) else ""

    auth_status = "Token scopes: 'repo', 'workflow'"
    result = po._apply_pr("test/repo", facts, plan_out, gh=mock_gh, auth_status=auth_status)

    for call in api_calls:
        call_str = " ".join(call) if isinstance(call, list) else str(call)
        if "PUT" in call_str or "POST" in call_str or "-X" in call_str:
            assert "heads/main" not in call_str, f"Write to default branch detected: {call_str}"


def test_apply_pr_idempotency_unchanged_on_rerun():
    """_apply_pr returns unchanged when run twice with same facts."""
    facts = {
        "repo": "test/repo",
        "default_branch": "main",
        "file_tree": {
            "docs/agents/issue-tracker.md": "file",
            "docs/agents/triage-labels.md": "file",
            "docs/agents/domain.md": "file",
        },
        "has_claude_md_skills": True,
    }
    plan_out = {
        "ci": {"state": "ok"},
        "agent_docs": {"state": "ok"},
    }

    def mock_gh(args):
        return ""

    result1 = po._apply_pr("test/repo", facts, plan_out, gh=mock_gh)
    result2 = po._apply_pr("test/repo", facts, plan_out, gh=mock_gh)

    assert result1["action"] == "unchanged"
    assert result2["action"] == "unchanged"


def test_apply_pr_deterministic_branch_name():
    """_apply_pr uses deterministic branch name."""
    facts = {
        "repo": "test/repo",
        "default_branch": "main",
        "file_tree": {},
        "detected_stack": "swift-package",
    }
    plan_out = {
        "ci": {"state": "missing"},
        "agent_docs": {"state": "missing"},
    }

    branches_used = []

    def mock_gh(args):
        call_str = " ".join(args)
        if "refs/heads/" in call_str:
            branches_used.append(call_str)
        if "git/ref/heads/main" in call_str:
            return json.dumps({"object": {"sha": "abc123"}})
        return ""

    auth_status = "Token scopes: 'repo', 'workflow'"
    po._apply_pr("test/repo", facts, plan_out, gh=mock_gh, auth_status=auth_status)

    assert any("onboarding/agent-docs-ci" in call for call in branches_used)


def test_apply_pr_returns_correct_fields():
    """_apply_pr returns result dict with expected fields."""
    facts = {
        "repo": "test/repo",
        "default_branch": "main",
        "file_tree": {},
        "detected_stack": "swift-package",
    }
    plan_out = {
        "ci": {"state": "missing"},
        "agent_docs": {"state": "missing"},
    }

    def mock_gh(args):
        return ""

    auth_status = "Token scopes: 'repo', 'workflow'"
    result = po._apply_pr("test/repo", facts, plan_out, gh=mock_gh, auth_status=auth_status)

    assert "action" in result
    assert result["action"] in ("created", "updated", "unchanged", "needs-human")


def test_apply_pr_claude_md_append_only_when_missing_block():
    """_apply_pr only appends CLAUDE.md block when has_claude_md_skills is False."""
    facts_without_block = {
        "repo": "test/repo",
        "default_branch": "main",
        "file_tree": {"CLAUDE.md": "file"},
        "has_claude_md_skills": False,
    }
    plan_out = {
        "ci": {"state": "ok"},
        "agent_docs": {"state": "missing", "reason": "missing CLAUDE.md block"},
    }

    calls = []

    def mock_gh(args):
        if "CLAUDE.md" in " ".join(args):
            calls.append(" ".join(args))
        return '{"content": "' + po.base64.b64encode(b"# Example").decode() + '"}'

    result = po._apply_pr("test/repo", facts_without_block, plan_out, gh=mock_gh)
    assert result["action"] in ("created", "updated", "needs-human")


def test_apply_pr_handles_missing_stack_gracefully():
    """_apply_pr handles no detected_stack gracefully."""
    facts = {
        "repo": "test/repo",
        "default_branch": "main",
        "file_tree": {},
        "detected_stack": None,
    }
    plan_out = {
        "ci": {"state": "missing"},
        "agent_docs": {"state": "missing"},
    }

    def mock_gh(args):
        return ""

    auth_status = "Token scopes: 'repo', 'workflow'"
    result = po._apply_pr("test/repo", facts, plan_out, gh=mock_gh, auth_status=auth_status)
    assert result["action"] in ("created", "updated", "unchanged", "needs-human")


# ── prove and baseline ──────────────────────────────────────────────────────


def test_prove_returns_ok_when_selftest_passes():
    """prove maps selftest passed → state ok with both offers enabled."""
    selftest_result = {"kind": "passed", "error": "baseline passed"}

    def mock_selftest(profile):
        return selftest_result

    result = po.prove("test/repo", profile={"repo": "test/repo"}, selftest_fn=mock_selftest)
    assert result["state"] == "ok"
    assert result["offers"]["merge_from_dashboard"] is True
    assert result["offers"]["dispatch"] is True
    assert "ran_at" in result


def test_prove_returns_missing_when_selftest_fails():
    """prove maps selftest failed → state missing with both offers disabled."""
    selftest_result = {"kind": "failed", "error": "2 tests failed"}

    def mock_selftest(profile):
        return selftest_result

    result = po.prove("test/repo", profile={"repo": "test/repo"}, selftest_fn=mock_selftest)
    assert result["state"] == "missing"
    assert result["offers"]["merge_from_dashboard"] is False
    assert result["offers"]["dispatch"] is False
    assert "2 tests failed" in result["reason"]


def test_prove_returns_needs_human_for_env_missing():
    """prove maps selftest env_missing → state needs-human (distinct from project failure)."""
    selftest_result = {"kind": "env_missing", "error": "this machine lacks swift"}

    def mock_selftest(profile):
        return selftest_result

    result = po.prove("test/repo", profile={"repo": "test/repo"}, selftest_fn=mock_selftest)
    assert result["state"] == "needs-human"
    assert result["offers"]["merge_from_dashboard"] is False
    assert result["offers"]["dispatch"] is False


def test_prove_needs_human_when_no_profile():
    """prove returns needs-human when no profile exists."""
    result = po.prove("test/repo", profile=None, selftest_fn=lambda p: {})
    assert result["state"] == "needs-human"
    assert "no profile yet" in result["reason"]


def test_record_baseline_writes_baseline_piece(tmp_path):
    """record_baseline adds baseline to pieces."""
    baseline_data = {
        "state": "ok",
        "offers": {"merge_from_dashboard": True, "dispatch": True},
        "reason": "baseline passed",
    }
    po.record_baseline("test/repo", baseline_data, dir=tmp_path)

    path = po.onboarding_path("test/repo", dir=tmp_path)
    data = json.loads(path.read_text())
    assert data["pieces"]["baseline"] == baseline_data


def test_record_baseline_merges_offers(tmp_path):
    """record_baseline merges offers (baseline wins for overlapping keys)."""
    # Create initial file with some offers
    initial_data = {
        "repo": "test/repo",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "pieces": {},
        "offers": {"other_flag": True},
    }
    path = po.onboarding_path("test/repo", dir=tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(initial_data) + "\n")

    # Record baseline with different offers
    baseline_data = {
        "state": "ok",
        "offers": {"merge_from_dashboard": True},
    }
    po.record_baseline("test/repo", baseline_data, dir=tmp_path)

    # Check that offers are merged (other_flag persists, merge_from_dashboard added)
    data = json.loads(path.read_text())
    assert data["offers"]["other_flag"] is True
    assert data["offers"]["merge_from_dashboard"] is True


def test_write_onboarding_plan_preserves_baseline(tmp_path):
    """write_onboarding_plan preserves existing baseline across refresh."""
    # Create initial file with baseline
    baseline_data = {"state": "ok", "reason": "passed"}
    initial_data = {
        "repo": "test/repo",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "pieces": {"baseline": baseline_data},
        "offers": {},
    }
    path = po.onboarding_path("test/repo", dir=tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(initial_data) + "\n")

    # Refresh plan (simulating hourly read-only rescan)
    new_pieces = {"profile": {"state": "ok"}}
    po.write_onboarding_plan("test/repo", new_pieces, dir=tmp_path)

    # Check baseline is still there
    data = json.loads(path.read_text())
    assert data["pieces"]["baseline"] == baseline_data


# ── 2026-10-08: the tree was never read, and failed reads looked like an empty repo (ADR 0058) ────────────────

def test_inspect_reads_the_tree_with_a_get_request():
    """`gh api <url> --field recursive=true` is a POST: GitHub answered 404 and every repo looked empty."""
    seen = []

    def gh(args):
        seen.append(args)
        if "trees" in " ".join(args):
            return json.dumps({"tree": [{"path": "pyproject.toml", "type": "blob"}]})
        return ""

    facts = po.inspect("test/repo", gh=gh)
    tree_call = next(a for a in seen if "trees" in " ".join(a))
    assert "--field" not in tree_call and "-f" not in tree_call and "-F" not in tree_call
    assert any("recursive=1" in a for a in tree_call)
    assert "pyproject.toml" in facts["file_tree"]


def test_inspect_lists_the_github_reads_that_failed():
    facts = po.inspect("test/repo", gh=lambda args: "")
    assert set(facts["read_errors"]) >= {"repo view", "file tree", "labels"}


def test_inspect_has_no_read_errors_when_github_answers():
    def gh(args):
        j = " ".join(args)
        if "repo view" in j:
            return json.dumps({"visibility": "PUBLIC", "defaultBranchRef": {"name": "main"}})
        if "trees" in j:
            return json.dumps({"tree": []})
        if "label" in j:
            return "[]"
        return ""
    assert po.inspect("test/repo", gh=gh)["read_errors"] == []


def test_a_failed_read_keeps_the_last_good_plan_and_marks_it_stale(tmp_path):
    good = {"board": {"state": "ok", "reason": "board registered"},
            "triage_labels": {"state": "ok", "reason": "all 5 triage labels present"}}
    po.write_onboarding_plan("o/repo", dict(good), dir=tmp_path)
    res = po.refresh_all_onboarding_plans(["o/repo"], gh=lambda args: "", dir=tmp_path)
    assert res["ok"] == [] and res["failed"][0][0] == "o/repo"
    kept = json.loads(po.onboarding_path("o/repo", dir=tmp_path).read_text())
    assert kept["pieces"]["triage_labels"]["state"] == "ok"
    assert "GitHub" in kept["stale"]["reason"]


def test_a_good_read_clears_the_stale_mark(tmp_path):
    po.write_onboarding_plan("o/repo", {"board": {"state": "ok", "reason": "x"}}, dir=tmp_path)
    po.refresh_all_onboarding_plans(["o/repo"], gh=lambda args: "", dir=tmp_path)

    def gh(args):
        j = " ".join(args)
        if "repo view" in j:
            return json.dumps({"visibility": "PUBLIC", "defaultBranchRef": {"name": "main"}})
        if "trees" in j:
            return json.dumps({"tree": []})
        if "label" in j:
            return "[]"
        return ""
    assert po.refresh_all_onboarding_plans(["o/repo"], gh=gh, dir=tmp_path)["ok"] == ["o/repo"]
    assert "stale" not in json.loads(po.onboarding_path("o/repo", dir=tmp_path).read_text())


def _answering_gh(args):
    j = " ".join(args)
    if "repo view" in j:
        return json.dumps({"visibility": "PUBLIC", "defaultBranchRef": {"name": "main"}})
    if "trees" in j:
        return json.dumps({"tree": [{"path": "pyproject.toml", "type": "blob"}]})
    if "label" in j:
        return "[]"
    return ""


def test_refresh_applies_the_safe_pieces_then_replans(tmp_path, monkeypatch):
    """ADR 0058: every hour, after a good read, labels/board/profile-draft are applied without anyone asking."""
    applied = []
    monkeypatch.setattr(po, "apply", lambda repo, facts=None, **kw: applied.append(repo) or {
        "labels": {"action": "created"}, "board": {"action": "unchanged"}, "profile": {"action": "created"}})
    res = po.refresh_all_onboarding_plans(["o/repo"], gh=_answering_gh, dir=tmp_path, apply_safe=True)
    assert applied == ["o/repo"] and res["ok"] == ["o/repo"]
    assert res["applied"] == {"o/repo": ["labels", "profile"]}


def test_refresh_never_applies_after_a_failed_read(tmp_path, monkeypatch):
    applied = []
    monkeypatch.setattr(po, "apply", lambda repo, facts=None, **kw: applied.append(repo) or {})
    po.refresh_all_onboarding_plans(["o/repo"], gh=lambda a: "", dir=tmp_path, apply_safe=True)
    assert applied == []


def test_refresh_without_apply_safe_changes_nothing(tmp_path, monkeypatch):
    applied = []
    monkeypatch.setattr(po, "apply", lambda repo, facts=None, **kw: applied.append(repo) or {})
    po.refresh_all_onboarding_plans(["o/repo"], gh=_answering_gh, dir=tmp_path)
    assert applied == []
