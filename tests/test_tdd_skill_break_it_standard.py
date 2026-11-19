"""Test that TDD skill documentation enforces break-it testing as per ADR 0063."""
import re
from pathlib import Path


def test_skill_md_no_longer_limits_edge_cases():
    """Verify SKILL.md does not contain 'not every possible edge case'."""
    skill_path = Path(__file__).resolve().parents[1] / "skills" / "tdd" / "SKILL.md"
    content = skill_path.read_text()
    assert "not every possible edge case" not in content, \
        "SKILL.md still contains the old 'not every possible edge case' phrase"


def test_skill_md_cites_adr_0063():
    """Verify SKILL.md cites docs/north-stars.md or ADR 0063."""
    skill_path = Path(__file__).resolve().parents[1] / "skills" / "tdd" / "SKILL.md"
    content = skill_path.read_text()
    # Check for citation of north-stars or ADR 0063
    has_north_stars = "north-stars.md" in content or "docs/north-stars.md" in content
    has_adr_citation = "ADR 0063" in content or "0063" in content
    assert has_north_stars or has_adr_citation, \
        "SKILL.md must cite docs/north-stars.md or ADR 0063"


def test_checklist_has_break_it_item():
    """Verify Checklist Per Cycle includes break-it cases."""
    skill_path = Path(__file__).resolve().parents[1] / "skills" / "tdd" / "SKILL.md"
    content = skill_path.read_text()
    # Look for break-it related keywords in the checklist section
    checklist_start = content.find("## Checklist Per Cycle")
    assert checklist_start != -1, "Checklist Per Cycle section not found"
    checklist_section = content[checklist_start:]
    # Check for break-it cases keywords
    has_break_it = any(keyword in checklist_section for keyword in [
        "break-it", "break it", "empty input", "malformed", "huge input",
        "dependency fail", "repeats", "wrong order", "stale state"
    ])
    assert has_break_it, \
        "Checklist must include break-it test cases (empty/malformed/huge input, etc.)"


def test_checklist_has_outward_facing_item():
    """Verify Checklist Per Cycle includes outward-facing adversarial cases."""
    skill_path = Path(__file__).resolve().parents[1] / "skills" / "tdd" / "SKILL.md"
    content = skill_path.read_text()
    checklist_start = content.find("## Checklist Per Cycle")
    assert checklist_start != -1, "Checklist Per Cycle section not found"
    checklist_section = content[checklist_start:]
    # Check for adversarial/outward-facing keywords
    has_adversarial = any(keyword in checklist_section for keyword in [
        "adversarial", "outward-facing", "injection", "traversal",
        "oversized payload", "secrets in logs", "fail closed"
    ])
    assert has_adversarial, \
        "Checklist must include outward-facing adversarial cases (injection, traversal, etc.)"


def test_mocking_md_states_temp_home_rule():
    """Verify mocking.md contains temp-HOME rule with monkeypatch example."""
    mocking_path = Path(__file__).resolve().parents[1] / "skills" / "tdd" / "mocking.md"
    content = mocking_path.read_text()
    # Check for the actual new rule: monkeypatch.setenv("HOME", ...) pattern
    # This verifies the specific implementation, not just generic keywords
    assert 'monkeypatch.setenv("HOME"' in content or "monkeypatch.setenv('HOME'" in content, \
        "mocking.md must include monkeypatch.setenv(\"HOME\", tmp_path) example for isolating home-dir tests"
    # Regression check: ChromaDB example still present
    assert "chromadb" in content.lower() or "ChromaDB" in content, \
        "mocking.md must still contain ChromaDB tmp_path example"


def test_mocking_md_cites_logs_wipe_incident():
    """Verify mocking.md references the 2026-10-09 logs-wipe incident."""
    mocking_path = Path(__file__).resolve().parents[1] / "skills" / "tdd" / "mocking.md"
    content = mocking_path.read_text()
    # Check for citation of the incident
    has_incident_ref = "2026-10-09" in content or "logs-wipe" in content or "logs wipe" in content
    assert has_incident_ref, \
        "mocking.md must cite the 2026-10-09 logs-wipe incident"


def test_tests_md_has_failure_path_example():
    """Verify tests.md includes a second Good example for failure paths with explicit statement."""
    tests_path = Path(__file__).resolve().parents[1] / "skills" / "tdd" / "tests.md"
    content = tests_path.read_text()
    # Verify at least 2 Good examples exist
    good_count = content.count("**Good**")
    assert good_count >= 2, \
        "tests.md must have at least 2 'Good' examples (one for happy path, one for failure path)"
    # Verify the specific statement about failure paths being behavior
    assert "Failure paths are behavior too" in content, \
        "tests.md must explicitly state: 'Failure paths are behavior too'"
    # Find the second Good section and verify it covers failure behavior
    # Look for second **Good** and verify it has content about rejection/failure
    parts = content.split("**Good**")
    assert len(parts) >= 3, "Must have at least 2 Good examples"
    second_good_section = parts[2]  # Content after second **Good**
    has_failure_content = any(keyword in second_good_section for keyword in [
        "malformed", "empty", "raises", "pytest.raises", "rejected", "reject"
    ])
    assert has_failure_content, \
        "Second 'Good' example must demonstrate failure path (malformed input, rejection, etc.)"


def test_mock_boundary_rule_unchanged():
    """Verify 'Mock at the true external boundary only' sentence is unchanged."""
    mocking_path = Path(__file__).resolve().parents[1] / "skills" / "tdd" / "mocking.md"
    content = mocking_path.read_text()
    exact_phrase = "Mock at the true external boundary only"
    assert exact_phrase in content, \
        f"mocking.md must contain unchanged phrase: '{exact_phrase}'"
