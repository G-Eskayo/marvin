"""project_onboard: onboarding health check for a new project."""
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import project_onboard as po


# ── fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def clarity_captions_facts():
    """Realistic facts for clarity-captions: profile ok, clone exists, labels incomplete."""
    return {
        "repo_view": {"defaultBranchRef": "main", "visibility": "private"},
        "tree": [
            "Package.swift",
            "Packages/CaptionCore/Package.swift",
            "Packages/CaptionCore/Tests/CoreTests.swift",
            "Apps/Spike/Apps.swift",
            ".github/workflows/test.yml",
            "docs/agents/issue-tracker.md",
            "docs/agents/triage-labels.md",
            "docs/agents/domain.md",
            "CLAUDE.md",
        ],
        "labels": ["needs-triage", "needs-info", "ready-for-agent", "ready-for-human", "wontfix"],
        "profile_data": {
            "repo": "G-Eskayo/clarity-captions",
            "base_branch": "main",
            "dispatch": "on",
            "verify": [{"id": "test", "command": ["swift", "test"]}],
        },
        "board_entry": {"repo": "G-Eskayo/clarity-captions", "name": "clarity-captions"},
        "clone_path": "/Users/test/.agents-pipeline-clones/clarity-captions",
    }


@pytest.fixture
def bare_repo_facts():
    """Bare repo: no profile, no docs, no board, no clone."""
    return {
        "repo_view": {"defaultBranchRef": "main", "visibility": "public"},
        "tree": ["README.md", "src/main.rs"],
        "labels": None,
        "profile_data": None,
        "board_entry": None,
        "clone_path": None,
    }


@pytest.fixture
def gh_failure_spy():
    """Mock gh that records calls and fails."""
    calls = []

    def gh(args):
        calls.append(args)
        return ""  # fail all calls

    gh.calls = calls
    return gh


# ── stack detection ──────────────────────────────────────────────────────────

def test_swift_package_detected_from_package_swift():
    tree = ["Package.swift", "Sources/Lib.swift", "Tests/LibTests.swift"]
    stack, path = po._detect_stack(tree)
    assert stack == "swift-package"
    assert path == "Package.swift"


def test_unrecognized_stack_when_no_detectors_match():
    tree = ["README.md", "setup.py", "src/main.py"]
    stack, path = po._detect_stack(tree)
    assert stack is None
    assert path is None


def test_empty_tree_returns_unknown_stack():
    stack, path = po._detect_stack([])
    assert stack is None


# ── plan_profile ─────────────────────────────────────────────────────────────

def test_profile_ok_when_present_and_valid(clarity_captions_facts):
    result = po.plan_profile(clarity_captions_facts, "swift-package", "Package.swift")
    assert result["state"] == "ok"


def test_profile_missing_when_file_absent():
    facts = {"profile_data": None}
    result = po.plan_profile(facts, None, None)
    assert result["state"] == "missing"


def test_profile_needs_human_when_invalid():
    facts = {"profile_data": {"broken": True}}
    result = po.plan_profile(facts, None, None)
    assert result["state"] == "needs-human"
    assert "invalid" in result["reason"].lower()


# ── plan_ci ──────────────────────────────────────────────────────────────────

def test_ci_ok_when_workflows_exist(clarity_captions_facts):
    result = po.plan_ci(clarity_captions_facts, None, None)
    assert result["state"] == "ok"
    assert "workflows" in result["reason"].lower()


def test_ci_missing_when_no_workflows():
    facts = {"tree": ["README.md", "src/main.rs"]}
    result = po.plan_ci(facts, "swift-package", "Package.swift")
    assert result["state"] == "missing"


def test_ci_needs_human_for_unknown_stack():
    facts = {"tree": [".github/workflows/test.yml"]}
    result = po.plan_ci(facts, None, None)
    assert result["state"] == "needs-human"
    assert "unrecognised" in result["reason"].lower()


# ── plan_labels ──────────────────────────────────────────────────────────────

def test_labels_ok_when_all_five_present(clarity_captions_facts):
    result = po.plan_labels(clarity_captions_facts, None, None)
    assert result["state"] == "ok"


def test_labels_missing_when_some_absent():
    facts = {"labels": ["needs-triage", "ready-for-agent"]}
    result = po.plan_labels(facts, None, None)
    assert result["state"] == "missing"
    assert "missing labels" in result["reason"].lower()


def test_labels_needs_human_when_gh_fails():
    facts = {"labels": None}
    result = po.plan_labels(facts, None, None)
    assert result["state"] == "needs-human"
    assert "could not verify" in result["reason"].lower()


# ── plan_agent_docs ──────────────────────────────────────────────────────────

def test_agent_docs_ok_when_all_present(clarity_captions_facts):
    result = po.plan_agent_docs(clarity_captions_facts, None, None)
    assert result["state"] == "ok"
    assert "all three agent docs present" in result["reason"]


def test_agent_docs_missing_when_files_absent():
    facts = {"tree": ["README.md"]}
    result = po.plan_agent_docs(facts, None, None)
    assert result["state"] == "missing"
    assert "missing docs" in result["reason"].lower()


def test_agent_docs_missing_when_some_absent():
    facts = {"tree": ["docs/agents/issue-tracker.md", "README.md"]}
    result = po.plan_agent_docs(facts, None, None)
    assert result["state"] == "missing"


# ── plan_board ───────────────────────────────────────────────────────────────

def test_board_ok_when_registered(clarity_captions_facts):
    result = po.plan_board(clarity_captions_facts, None, None)
    assert result["state"] == "ok"


def test_board_missing_when_not_registered():
    facts = {"board_entry": None}
    result = po.plan_board(facts, None, None)
    assert result["state"] == "missing"


# ── plan_clone_toolchain ─────────────────────────────────────────────────────

def test_clone_toolchain_ok_when_tools_and_clone_present(clarity_captions_facts, monkeypatch):
    monkeypatch.setattr("project_profile.have", lambda tool, env: True)
    result = po.plan_clone_toolchain(clarity_captions_facts, "swift-package", "Package.swift")
    assert result["state"] == "ok"


def test_clone_toolchain_needs_human_when_tools_missing(monkeypatch):
    monkeypatch.setattr("project_profile.have", lambda tool, env: False)
    facts = {"clone_path": "/some/path"}
    result = po.plan_clone_toolchain(facts, "swift-package", "Package.swift")
    assert result["state"] == "needs-human"
    assert "missing tools" in result["reason"].lower()


def test_clone_toolchain_missing_when_clone_absent_but_tools_ok(monkeypatch):
    monkeypatch.setattr("project_profile.have", lambda tool, env: True)
    facts = {"clone_path": None}
    result = po.plan_clone_toolchain(facts, "swift-package", "Package.swift")
    assert result["state"] == "missing"
    assert "clone not found" in result["reason"].lower()


def test_clone_toolchain_needs_human_for_unknown_stack():
    facts = {"clone_path": None}
    result = po.plan_clone_toolchain(facts, None, None)
    assert result["state"] == "needs-human"
    assert "unrecognised" in result["reason"].lower()


# ── plan_test_command ────────────────────────────────────────────────────────

def test_test_command_ok_for_swift_package():
    result = po.plan_test_command({}, "swift-package", "Package.swift")
    assert result["state"] == "ok"
    assert "swift test" in result["reason"]


def test_test_command_needs_human_for_unknown_stack():
    result = po.plan_test_command({}, None, None)
    assert result["state"] == "needs-human"
    assert "unrecognised" in result["reason"].lower()


# ── gather ───────────────────────────────────────────────────────────────────

def test_gather_tolerates_gh_failures(gh_failure_spy, tmp_path):
    result = po.gather("test/repo", gh=gh_failure_spy, profiles_dir=tmp_path, boards_path=tmp_path / "boards.json")
    assert result["repo_view"] is None
    assert result["tree"] is None
    assert result["labels"] is None


def test_gather_reads_profile_file(tmp_path):
    profiles_dir = tmp_path / "profiles"
    profiles_dir.mkdir()
    profile_file = profiles_dir / "test.json"
    profile_file.write_text('{"repo": "a/test", "verify": [{"id": "x", "command": ["echo"]}]}')

    result = po.gather("a/test", gh=lambda x: "", profiles_dir=profiles_dir, boards_path=tmp_path / "boards.json")
    assert result["profile_data"] is not None
    assert result["profile_data"]["repo"] == "a/test"


def test_gather_reads_board_registry(tmp_path):
    boards_path = tmp_path / "boards.json"
    boards_path.write_text('{"boards": [{"repo": "a/test", "name": "Test Board"}]}')

    result = po.gather("a/test", gh=lambda x: "", profiles_dir=tmp_path / "profiles", boards_path=boards_path)
    assert result["board_entry"] is not None
    assert result["board_entry"]["name"] == "Test Board"


# ── plan ─────────────────────────────────────────────────────────────────────

def test_plan_returns_shape_with_seven_pieces(clarity_captions_facts):
    def mock_gh(args):
        return json.dumps(clarity_captions_facts["repo_view"]) if "repo" in args else ""

    def mock_gather(*args, **kwargs):
        return clarity_captions_facts

    import project_onboard
    original_gather = project_onboard.gather
    project_onboard.gather = mock_gather

    try:
        result = po.plan("G-Eskayo/clarity-captions", gh=mock_gh)
        assert result["repo"] == "G-Eskayo/clarity-captions"
        assert result["stack"] == "swift-package"
        assert set(result["pieces"].keys()) == {
            "profile", "ci", "labels", "agent_docs", "board", "clone_toolchain", "test_command"
        }
        for piece in result["pieces"].values():
            assert "state" in piece
            assert "reason" in piece
            assert piece["state"] in ("ok", "missing", "needs-human")
    finally:
        project_onboard.gather = original_gather


def test_plan_unrecognized_stack_shorts_circuit_three_pieces():
    facts = {
        "repo_view": {"defaultBranchRef": "main"},
        "tree": ["README.md"],
        "labels": ["needs-triage"],
        "profile_data": None,
        "board_entry": None,
        "clone_path": None,
    }

    def mock_gather(*args, **kwargs):
        return facts

    import project_onboard
    original_gather = project_onboard.gather
    project_onboard.gather = mock_gather

    try:
        result = po.plan("test/repo", gh=lambda x: "")
        assert result["stack"] == "unknown"
        assert result["pieces"]["ci"]["state"] == "needs-human"
        assert "unrecognised" in result["pieces"]["ci"]["reason"].lower()
        assert result["pieces"]["clone_toolchain"]["state"] == "needs-human"
        assert result["pieces"]["test_command"]["state"] == "needs-human"
    finally:
        project_onboard.gather = original_gather


# ── no mutating calls ────────────────────────────────────────────────────────

def test_plan_never_calls_mutating_gh_verbs(clarity_captions_facts):
    """Assert that plan() never calls gh with mutating verbs."""
    calls = []

    def spy_gh(args):
        calls.append(args)
        return ""

    def mock_gather(*args, **kwargs):
        return clarity_captions_facts

    import project_onboard
    original_gather = project_onboard.gather
    project_onboard.gather = mock_gather

    try:
        po.plan("test/repo", gh=spy_gh)
        for call in calls:
            verb = call[0] if call else None
            assert verb not in ("create", "delete", "edit", "clone", "push"), f"Found mutating call: {call}"
    finally:
        project_onboard.gather = original_gather
