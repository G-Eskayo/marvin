"""Test that the to-prd skill documents the correct PRD labeling."""
import re
from pathlib import Path


def test_to_prd_skill_step_3_documents_prd_title_format():
    """Verify that to-prd/SKILL.md step 3 describes the PRD: prefix and labeling."""
    skill_path = Path(__file__).resolve().parents[1] / "skills" / "to-prd" / "SKILL.md"
    content = skill_path.read_text()

    # Find step 3 by looking for "3." or similar heading
    step3_match = re.search(r'^3\.\s+(.+?)(?=\n4\.|$)', content, re.MULTILINE | re.DOTALL)
    assert step3_match, "Could not find step 3 in to-prd/SKILL.md"

    step3_text = step3_match.group(0)

    # Verify the PRD: prefix is mentioned
    assert "PRD:" in step3_text, "Step 3 should mention 'PRD:' prefix"

    # Verify enhancement label is mentioned
    assert "enhancement" in step3_text, "Step 3 should mention 'enhancement' label"

    # Verify project label is specifically mentioned (not just the word "project" anywhere)
    assert "project label" in step3_text.lower(), \
        "Step 3 should explicitly mention 'project label'"

    # Verify priority label is mentioned
    assert "priority label" in step3_text.lower(), \
        "Step 3 should explicitly mention 'priority label'"

    # Verify that the doc explicitly says NOT to apply triage-role labels
    # Look for wording like "apply none of" or "do not apply" or "carry no"
    has_no_apply_instruction = any(phrase in step3_text.lower() for phrase in [
        "apply none of",
        "do not apply",
        "carry no",
        "apply ... none",
    ])
    assert has_no_apply_instruction, \
        "Step 3 should explicitly state that triage-role labels are NOT applied"


def test_prd_prefix_matches_ticket_policy_regex():
    """Verify that the PRD: prefix format from SKILL.md matches ticket_policy.py regex."""
    # This tests that our documentation is consistent with the actual code
    import sys
    from pathlib import Path

    skill_path = Path(__file__).resolve().parents[1] / "skills" / "to-prd" / "SKILL.md"
    skill_content = skill_path.read_text()

    # Extract the PRD title format from step 3 of SKILL.md
    step3_match = re.search(r'^3\.\s+(.+?)(?=\n4\.|$)', skill_content, re.MULTILINE | re.DOTALL)
    assert step3_match, "Could not find step 3 in to-prd/SKILL.md"
    step3_text = step3_match.group(0)

    # Extract the title format: "Title it `PRD: <name>`"
    title_match = re.search(r'Title it\s+`([^`]+)`', step3_text)
    assert title_match, "Step 3 should specify the title format in backticks"
    title_format = title_match.group(1)

    # Verify it starts with "PRD:"
    assert title_format.startswith("PRD:"), \
        f"Title format from SKILL.md should start with 'PRD:' but got '{title_format}'"

    lib_path = Path(__file__).resolve().parents[1] / "lib"
    sys.path.insert(0, str(lib_path))

    import ticket_policy as tp

    # Test that the actual format from the doc matches is_parent_prd
    # Replace <name> placeholder with a test value
    test_title = title_format.replace("<name>", "Test Feature")
    assert tp.is_parent_prd({"title": test_title, "body": ""}), \
        f"PRD title format '{test_title}' from SKILL.md should match ticket_policy.is_parent_prd"

    # Also test case-insensitivity
    assert tp.is_parent_prd({"title": test_title.lower(), "body": ""}), \
        "PRD prefix should be case-insensitive per ticket_policy"

    # Verify non-PRD titles don't match
    assert not tp.is_parent_prd({"title": "This is not a PRD", "body": ""}), \
        "Non-PRD titles should not match"
