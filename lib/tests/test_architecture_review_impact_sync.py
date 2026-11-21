"""
Tests to verify architecture-review/SKILL.md's Impact values stay in sync with
inbox.IMPACT_RANK.
"""
import re
from pathlib import Path

import pytest

LIB = Path(__file__).resolve().parents[1]
import sys
sys.path.insert(0, str(LIB))

import inbox  # noqa: E402


REPO = Path(__file__).resolve().parents[2]
ARCH_REVIEW_SKILL = REPO / "skills" / "architecture-review" / "SKILL.md"


def extract_impact_values(text=None):
    """Extract Impact values from architecture-review's Entry format block.

    Args:
        text: Optional text to extract from. If None, reads ARCH_REVIEW_SKILL file.
    """
    if text is None:
        text = ARCH_REVIEW_SKILL.read_text()
    # Find the Impact line in the Entry format block
    match = re.search(
        r"\*\*Impact\*\*:\s*\[(.*?)\]",
        text
    )
    if not match:
        raise AssertionError(
            "Could not find '**Impact**: [...]' in architecture-review/SKILL.md"
        )

    block = match.group(1)
    # Split by | and strip whitespace
    values = [v.strip() for v in block.split("|")]

    if not values:
        raise AssertionError(
            "Impact values block matched but extracted no values. "
            "Check that Impact block contains pipe-separated values."
        )
    return values, block


def _assert_impact_parity(values):
    """Helper to verify Impact values match inbox.IMPACT_RANK.keys().

    Args:
        values: List of impact values to check.

    Raises:
        AssertionError: If values don't match IMPACT_RANK.keys() exactly.
    """
    expected = set(inbox.IMPACT_RANK.keys())
    actual = set(values)

    assert actual == expected, (
        f"Impact values mismatch. "
        f"Missing from values: {expected - actual}. "
        f"Extra in values: {actual - expected}."
    )


def test_impact_values_parity_with_inbox_rank():
    """Verify architecture-review's Impact values match inbox.IMPACT_RANK.keys()."""
    values, _ = extract_impact_values()
    _assert_impact_parity(values)


def test_impact_values_order_matches_inbox_rank():
    """Verify architecture-review's Impact values are in the same order as inbox.IMPACT_RANK."""
    values, _ = extract_impact_values()
    expected_order = list(inbox.IMPACT_RANK.keys())

    assert values == expected_order, (
        f"Impact values order mismatch. "
        f"Expected: {expected_order}. "
        f"Got: {values}."
    )


def test_impact_values_whitespace_tolerance():
    """Verify the extraction handles whitespace correctly."""
    # Test with extra spaces and punctuation in the text
    text_with_spaces = """
    **Impact**: [  token-reduction  |  speed  |  organization  |  pipeline-logic  |  reliability  |  robustness  ]
    """
    values, block = extract_impact_values(text_with_spaces)

    # Ensure no leading/trailing whitespace in individual values after extraction
    for v in values:
        assert v == v.strip(), f"Value has whitespace: {v!r}"

    # Ensure values match expected (without spaces)
    expected = ["token-reduction", "speed", "organization", "pipeline-logic", "reliability", "robustness"]
    assert values == expected, f"Values don't match expected: {values} vs {expected}"

    # Ensure we correctly parsed the block
    assert len(values) > 0 and all(values), "Some values are empty or falsy"


def test_drift_detection_catches_extra_impact_value():
    """Verify that the parity helper detects when SKILL.md has extra values."""
    # Create drifted SKILL.md content with an extra value
    drifted_text = """
    **Impact**: [token-reduction | speed | organization | pipeline-logic | reliability | robustness | fake-impact]
    """
    drifted_values, _ = extract_impact_values(drifted_text)

    # The parity check should catch the extra value
    with pytest.raises(AssertionError, match="Extra in values"):
        _assert_impact_parity(drifted_values)


def test_drift_detection_catches_missing_impact_value():
    """Verify that the parity helper detects when SKILL.md is missing values."""
    # Create drifted SKILL.md content with a missing value
    drifted_text = """
    **Impact**: [token-reduction | speed | organization | reliability | robustness]
    """
    drifted_values, _ = extract_impact_values(drifted_text)

    # The parity check should catch the missing value
    with pytest.raises(AssertionError, match="Missing from values"):
        _assert_impact_parity(drifted_values)


def test_missing_impact_block_guard():
    """Verify that a missing Impact block raises an error."""
    # Test with text that lacks the **Impact**: block
    text_without_impact = """
    **Priority**: [1-10]
    **Status**: pending
    **Effort**: [low | medium | high]
    """

    # Assert that the extractor raises AssertionError when Impact block is missing
    with pytest.raises(AssertionError, match="Could not find.*\\*\\*Impact\\*\\*"):
        extract_impact_values(text_without_impact)
