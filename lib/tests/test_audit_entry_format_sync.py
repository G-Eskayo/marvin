"""
Tests to verify audit/SKILL.md's dispatch prompt stays in sync with
architecture-review/SKILL.md's Entry format block.
"""
import re
from pathlib import Path


REPO = Path(__file__).resolve().parents[2]
AUDIT_SKILL = REPO / "skills" / "audit" / "SKILL.md"
ARCH_REVIEW_SKILL = REPO / "skills" / "architecture-review" / "SKILL.md"


def extract_entry_format_block():
    """Extract field names from architecture-review's Entry format block."""
    text = ARCH_REVIEW_SKILL.read_text()
    # Find the Entry format: block and extract field names from the markdown
    match = re.search(
        r"Entry format:.*?```.*?\n(.*?)\n```",
        text,
        re.DOTALL
    )
    if not match:
        raise AssertionError(
            "Could not find 'Entry format:' block in architecture-review/SKILL.md"
        )

    block = match.group(1)
    # Extract field names (e.g., **Priority**: becomes Priority)
    fields = re.findall(r"\*\*(\w+)\*\*:", block)
    assert fields, (
        "Entry format block regex matched but extracted no fields. "
        "Check that Entry format block contains **FieldName**: patterns."
    )
    return fields, block


def extract_audit_dispatch_prompt():
    """Extract the dispatch prompt section from audit/SKILL.md."""
    text = AUDIT_SKILL.read_text()
    # Find the dispatch section - look for "## How to dispatch" and extract until the next "## "
    match = re.search(
        r"## How to dispatch.*?\n(.*?)(?=\n## )",
        text,
        re.DOTALL
    )
    if not match:
        raise AssertionError(
            "Could not find '## How to dispatch' section in audit/SKILL.md"
        )
    return match.group(1)


def find_missing_fields(fields, dispatch_prompt):
    """Helper: find which fields are missing from the dispatch prompt."""
    missing_fields = []
    for field in fields:
        if f"**{field}**" not in dispatch_prompt:
            missing_fields.append(field)
    return missing_fields


def test_audit_dispatch_prompt_names_every_architecture_review_entry_field():
    """Verify audit's dispatch prompt mentions all Entry format fields."""
    fields, _ = extract_entry_format_block()
    dispatch_prompt = extract_audit_dispatch_prompt()

    # Look for **FieldName** pattern in the dispatch prompt
    missing_fields = find_missing_fields(fields, dispatch_prompt)

    assert not missing_fields, (
        f"Missing fields in audit/SKILL.md dispatch prompt: {missing_fields}. "
        f"Fields required from architecture-review: {fields}"
    )


def test_drift_check_detects_a_field_missing_from_audits_prompt():
    """Verify the test actually detects when a field is missing."""
    fields, _ = extract_entry_format_block()
    dispatch_prompt = extract_audit_dispatch_prompt()

    # Inject a field that doesn't exist in audit's prompt
    synthetic_fields = fields + ["Owner"]
    missing_fields = find_missing_fields(synthetic_fields, dispatch_prompt)

    # Assert that the detection logic correctly identifies "Owner" as missing
    assert missing_fields == ["Owner"], (
        f"Drift detection failed: expected ['Owner'] but got {missing_fields}. "
        f"The detection mechanism must identify fields not in the dispatch prompt."
    )


def test_audit_dispatch_prompt_no_longer_uses_the_stale_dated_header():
    """Verify the old header format [date] [title] is removed."""
    dispatch_prompt = extract_audit_dispatch_prompt()

    # Check that the old format is gone
    assert "## [date] [title]" not in dispatch_prompt, (
        "Old header format '## [date] [title]' still present in audit dispatch prompt"
    )

    # Check that the Entry format block is referenced instead
    assert "Entry format:" in dispatch_prompt, (
        "Reference to Entry format block not found in audit dispatch prompt"
    )
