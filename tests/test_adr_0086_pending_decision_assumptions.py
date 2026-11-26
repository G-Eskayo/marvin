"""Test that ADR 0086 doesn't assume answers to pending Decisions.

Defect caught: Consequences section made absolute statements about behavior that
depend on unanswered Decisions (tunnel path, pickup-mechanism, wake-scope).
This test validates that pending Decisions are referenced conditionally.
"""

import re
from pathlib import Path


def test_adr_0086_pending_decisions_not_assumed_in_consequences():
    """Pending Decisions must be referenced conditionally, not assumed."""
    adr_path = Path(__file__).resolve().parent.parent / "docs" / "adr" / "0086-hub-reachability-ordered-resolver.md"
    content = adr_path.read_text()

    # Check that Status lists pending decisions
    assert "Pending owner decisions" in content, "Status should list pending decisions"
    assert "`tunnel`" in content, "Missing Decision `tunnel`"
    assert "`lan-address`" in content, "Missing Decision `lan-address`"
    assert "`pickup-mechanism`" in content, "Missing Decision `pickup-mechanism`"
    assert "`wake-scope`" in content, "Missing Decision `wake-scope`"

    # Extract Consequences section
    consequences_match = re.search(r"## Consequences\n+(.*?)\n## Alternatives", content, re.DOTALL)
    assert consequences_match, "Could not find Consequences section"
    consequences = consequences_match.group(1)

    # Check for the specific antipatterns that were in the original defect
    # Pattern 1: "starting from `tunnel: C`" (assumes a specific choice)
    assert not re.search(r"starting from `tunnel:\s*C`", consequences), "Consequences assumes tunnel: C without being conditional"

    # Pattern 2: "Work starts exactly once within a minute" (absolute timing without conditional on decisions)
    # This should be conditional on pickup-mechanism and wake-scope
    work_starts_match = re.search(r"Work starts exactly once within a minute", consequences)
    if work_starts_match:
        # If this phrase exists, it must be conditional (depends on decisions)
        assert False, "Found 'Work starts exactly once within a minute' - should be conditional on Decision answers"


def test_adr_0086_consequences_tunnel_decision_conditional():
    """Specific fix: tunnel Decision consequence should be conditional."""
    adr_path = Path(__file__).resolve().parent.parent / "docs" / "adr" / "0086-hub-reachability-ordered-resolver.md"
    content = adr_path.read_text()

    consequences_match = re.search(r"## Consequences\n+(.*?)\n## Alternatives", content, re.DOTALL)
    assert consequences_match
    consequences = consequences_match.group(1)

    # Verify the tunnel consequence is properly conditional
    # Must have:
    # 1. "Off-network reach, conditional on Decision `tunnel`" header
    # 2. Conditional language like "If the owner chooses"
    assert "Off-network reach, conditional on Decision `tunnel`" in consequences, \
        "Tunnel consequence header not found or not conditional"

    # Find the tunnel consequence paragraph
    tunnel_para = re.search(
        r"Off-network reach, conditional on Decision `tunnel`.*?(?=\n-\s|\Z)",
        consequences,
        re.DOTALL,
    )
    assert tunnel_para, "Could not extract tunnel consequence text"

    text = tunnel_para.group(0)
    # Verify it has conditional language
    assert any(
        cond in text
        for cond in ["If the owner chooses", "Option A", "Option B", "Option C", "If deferred"]
    ), f"Tunnel consequence missing conditional language: {text}"


def test_adr_0086_consequences_pickup_mechanism_conditional():
    """Specific fix: pickup-mechanism and wake-scope consequences should be conditional."""
    adr_path = Path(__file__).resolve().parent.parent / "docs" / "adr" / "0086-hub-reachability-ordered-resolver.md"
    content = adr_path.read_text()

    consequences_match = re.search(r"## Consequences\n+(.*?)\n## Alternatives", content, re.DOTALL)
    assert consequences_match
    consequences = consequences_match.group(1)

    # Verify the pickup prevention consequence is properly conditional
    # Must have:
    # 1. Header mentioning both pickup-mechanism and wake-scope decisions
    # 2. Conditional language about when work starts
    assert "Duplicate pickup prevention, conditional on Decision `pickup-mechanism` and `wake-scope`" in consequences, \
        "Pickup consequence header not found or not conditional"

    # Find the pickup consequence paragraph
    pickup_para = re.search(
        r"Duplicate pickup prevention, conditional on Decision.*?(?=\n-\s|\Z)",
        consequences,
        re.DOTALL,
    )
    assert pickup_para, "Could not extract pickup consequence text"

    text = pickup_para.group(0)
    # Verify it references both decisions and has conditional language
    assert "`pickup-mechanism`" in text, "Pickup consequence doesn't reference `pickup-mechanism`"
    assert "`wake-scope`" in text, "Pickup consequence doesn't reference `wake-scope`"

    # Should contain conditional language about when work starts
    assert any(
        cond in text
        for cond in [
            "When work starts depends on",
            "depends on Decision",
            "Option A",
            "Option B",
            "immediate on boot",
            "deferred to next hourly scan",
        ]
    ), f"Pickup consequence missing conditional logic: {text}"


def test_adr_0086_pickup_mechanism_options_match_alternatives():
    """Verify pickup-mechanism consequence correctly describes all options vs Alternatives section.

    Defect caught: consequence said work is "deferred to next hourly scan if Option B",
    but Option B (GitHub webhook) is described in Alternatives as "faster at notifying",
    and Option C (both A and B) was not mentioned. This test ensures all three options
    are named and their speed tradeoffs match the Alternatives section.
    """
    adr_path = Path(__file__).resolve().parent.parent / "docs" / "adr" / "0086-hub-reachability-ordered-resolver.md"
    content = adr_path.read_text()

    # Extract Consequences section
    consequences_match = re.search(r"## Consequences\n+(.*?)\n## Alternatives", content, re.DOTALL)
    assert consequences_match, "Could not find Consequences section"
    consequences = consequences_match.group(1)

    # Extract Alternatives section
    alternatives_match = re.search(r"## Alternatives considered\n+(.*?)(\Z|$)", content, re.DOTALL)
    assert alternatives_match, "Could not find Alternatives section"
    alternatives = alternatives_match.group(1)

    # Find the pickup-mechanism consequence paragraph
    pickup_para = re.search(
        r"Duplicate pickup prevention, conditional on Decision.*?(?=\n-\s|\Z)",
        consequences,
        re.DOTALL,
    )
    assert pickup_para, "Could not extract pickup consequence text"
    pickup_text = pickup_para.group(0)

    # Verify all three options are mentioned in the consequence
    assert "Option A" in pickup_text, "Option A not mentioned in pickup-mechanism consequence"
    assert "Option B" in pickup_text, "Option B not mentioned in pickup-mechanism consequence"
    assert "Option C" in pickup_text, "Option C not mentioned in pickup-mechanism consequence"

    # Verify Option B is described with correct speed characteristic
    # Find what the consequence says about Option B
    option_b_match = re.search(r"Option B[^.]*", pickup_text)
    assert option_b_match, "Could not find Option B description in consequence"
    option_b_desc = option_b_match.group(0)

    # Option B should NOT say "deferred" (that was the bug)
    # Instead it should indicate faster/webhook-based behavior
    assert "deferred to next hourly scan" not in option_b_desc or \
           any(faster_phrase in pickup_text for faster_phrase in ["faster", "webhook", "GitHub"]), \
        "Option B incorrectly described as deferred; should reference faster webhook behavior"

    # Verify consistency: Alternatives says GitHub webhook is "faster at notifying"
    # so the consequence should not say Option B defers work
    if "GitHub webhook" in alternatives and "faster" in alternatives:
        assert "deferred" not in option_b_desc or "faster" in option_b_desc, \
            "Consequence contradicts Alternatives: webhook (B) is faster but consequence says deferred"
