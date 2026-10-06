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


def test_plan_returns_all_six_pieces():
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
    }
    result = po.plan(facts)
    expected_pieces = {"profile", "ci", "triage_labels", "agent_docs", "board", "clone_and_toolchain", "test_command"}
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


# ── CI piece ────────────────────────────────────────────────────────────


def test_ci_ok_when_workflow_runs_swift_test():
    facts = {"workflow_runs_swift_test": True}
    result = po.plan(facts)
    assert result["ci"]["state"] == "ok"


def test_ci_missing_when_no_workflows():
    facts = {"has_workflows": False, "workflow_runs_swift_test": False}
    result = po.plan(facts)
    assert result["ci"]["state"] == "missing"


def test_ci_needs_human_when_workflow_exists_but_no_swift_test():
    facts = {"has_workflows": True, "workflow_runs_swift_test": False}
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


def test_test_command_ok_when_package_swift_has_swift_test_in_workflow():
    facts = {"has_package_swift": True, "workflow_runs_swift_test": True}
    result = po.plan(facts)
    assert result["test_command"]["state"] == "ok"


def test_test_command_missing_when_package_swift_but_no_test_target():
    facts = {"has_package_swift": True, "workflow_runs_swift_test": False}
    result = po.plan(facts)
    assert result["test_command"]["state"] == "missing"


def test_test_command_needs_human_when_not_swift_package():
    facts = {"has_package_swift": False}
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
    }
    result = po.plan(facts)
    for piece in ["profile", "ci", "triage_labels", "agent_docs", "board"]:
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
    }
    result = po.plan(facts)
    assert result["profile"]["state"] == "ok"
    assert result["ci"]["state"] == "missing"
    assert result["triage_labels"]["state"] == "missing"
    assert result["agent_docs"]["state"] == "missing"
    assert result["board"]["state"] == "ok"
    assert result["clone_and_toolchain"]["state"] == "missing"
    assert result["test_command"]["state"] == "missing"


# ── Module correctness ───────────────────────────────────────────────────


def test_module_has_public_api():
    assert hasattr(po, "_gh") and callable(po._gh)
    assert hasattr(po, "inspect") and callable(po.inspect)
    assert hasattr(po, "plan") and callable(po.plan)
    assert hasattr(po, "main") and callable(po.main)
    assert hasattr(po, "write_plan") and callable(po.write_plan)
    assert hasattr(po, "TRIAGE_LABELS") and isinstance(po.TRIAGE_LABELS, set)


def test_triage_labels_are_the_canonical_five():
    expected = {"needs-triage", "needs-info", "ready-for-agent", "ready-for-human", "wontfix"}
    assert po.TRIAGE_LABELS == expected


# ── Persistence: write_plan ──────────────────────────────────────────────

def test_write_plan_creates_json_file(tmp_path):
    def mock_gh(args):
        return ""

    output_path = tmp_path / "test-repo.json"
    result = po.write_plan("test/repo", gh=mock_gh, path=output_path)

    assert output_path.exists()
    assert "repo" in result
    assert result["repo"] == "test/repo"
    assert "generated_at" in result
    assert "pieces" in result


def test_write_plan_atomic_write(tmp_path):
    def mock_gh(args):
        return ""

    output_path = tmp_path / "test-repo.json"
    po.write_plan("test/repo", gh=mock_gh, path=output_path)

    content = output_path.read_text()
    parsed = json.loads(content)
    assert isinstance(parsed, dict)
    assert parsed["repo"] == "test/repo"
    # tmp file should not exist
    assert not output_path.with_suffix(".tmp").exists()


def test_write_plan_has_iso_timestamp(tmp_path):
    def mock_gh(args):
        return ""

    output_path = tmp_path / "test-repo.json"
    result = po.write_plan("test/repo", gh=mock_gh, path=output_path)

    # Should be ISO format (can be parsed)
    from datetime import datetime
    generated = result["generated_at"]
    parsed = datetime.fromisoformat(generated)
    assert parsed is not None


def test_write_plan_includes_all_pieces(tmp_path):
    def mock_gh(args):
        return ""

    output_path = tmp_path / "test-repo.json"
    result = po.write_plan("test/repo", gh=mock_gh, path=output_path)

    expected_pieces = {"profile", "ci", "triage_labels", "agent_docs", "board", "clone_and_toolchain", "test_command"}
    assert set(result["pieces"].keys()) == expected_pieces
