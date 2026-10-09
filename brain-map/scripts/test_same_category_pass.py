#!/usr/bin/env python3
"""
Tests for same_category_pass.py — detects when multiple nodes share the same
category (cat field) but have no direct synapse between each other.
"""
import json
from pathlib import Path
import sys

# Import the module under test
sys.path.insert(0, str(Path(__file__).parent))
from same_category_pass import (
    collect_nodes_with_ancestors,
    is_ancestor_of,
    has_direct_edge,
    find_gaps,
)


def build_synthetic_tree():
    """
    Minimal tree fixture with nodes in various categories.
    Includes connected and disconnected same-category pairs.
    """
    return {
        "id": "MARVIN",
        "cat": "root",
        "desc": "Root node",
        "children": [
            {
                "id": "research",
                "cat": "research",
                "desc": "Research coordination",
                "children": [],
            },
            {
                "id": "research-colony",
                "cat": "research",
                "desc": "Autonomous research polling agent",
                "children": [],
            },
            {
                "id": "paper-dive",
                "cat": "research",
                "desc": "Walk through papers interactively",
                "children": [],
            },
            {
                "id": "quality",
                "cat": "quality",
                "desc": "Quality assurance",
                "children": [
                    {
                        "id": "qa-agent",
                        "cat": "quality",
                        "desc": "QA pattern scanner",
                        "children": [],
                    },
                    {
                        "id": "audit",
                        "cat": "quality",
                        "desc": "Intent vs reality auditor",
                        "children": [],
                    },
                ],
            },
            {
                "id": "wrapper-empty",
                "cat": "other",
                "desc": "",  # Empty description — should be excluded
                "children": [
                    {
                        "id": "child-of-empty",
                        "cat": "other",
                        "desc": "Child of empty wrapper",
                        "children": [],
                    }
                ],
            },
        ],
    }


def test_collect_nodes_with_ancestors():
    """Verify node collection and ancestor chain tracking."""
    tree = build_synthetic_tree()
    nodes = collect_nodes_with_ancestors(tree)

    # Should include MARVIN (root)
    assert "MARVIN" in nodes
    assert nodes["MARVIN"] == ("root", [])

    # Should include research nodes
    assert "research" in nodes
    assert "research-colony" in nodes
    assert "paper-dive" in nodes
    assert nodes["research"] == ("research", ["MARVIN"])
    assert nodes["research-colony"] == ("research", ["MARVIN"])

    # Should include qa-agent with ancestor chain through quality
    assert "qa-agent" in nodes
    assert nodes["qa-agent"] == ("quality", ["MARVIN", "quality"])

    # Should include audit (sibling of qa-agent)
    assert "audit" in nodes
    assert nodes["audit"] == ("quality", ["MARVIN", "quality"])

    # Should exclude wrapper-empty (empty description)
    assert "wrapper-empty" not in nodes

    # Should include child-of-empty even though parent is empty
    assert "child-of-empty" in nodes
    assert nodes["child-of-empty"] == ("other", ["MARVIN"])  # skips empty wrapper


def test_is_ancestor_of():
    """Verify ancestor/descendant detection."""
    tree = build_synthetic_tree()
    nodes = collect_nodes_with_ancestors(tree)

    # MARVIN is ancestor of qa-agent
    assert is_ancestor_of("MARVIN", "qa-agent", nodes) is True

    # quality is ancestor of qa-agent
    assert is_ancestor_of("quality", "qa-agent", nodes) is True

    # qa-agent is not ancestor of audit
    assert is_ancestor_of("qa-agent", "audit", nodes) is False

    # research is not ancestor of research-colony (siblings)
    assert is_ancestor_of("research", "research-colony", nodes) is False


def test_has_direct_edge():
    """Verify direct-edge detection in both directions."""
    synapses = [
        {"a": "research", "b": "research-colony", "label": "test", "type": "calls"},
        {"a": "qa-agent", "b": "audit", "label": "test", "type": "hook"},
    ]

    # Forward direction
    assert has_direct_edge("research", "research-colony", synapses) is True
    # Reverse direction
    assert has_direct_edge("research-colony", "research", synapses) is True
    # Different pair
    assert has_direct_edge("research", "paper-dive", synapses) is False


def test_find_gaps_same_category_no_edge():
    """
    Core test: detect pairs of same-category nodes with no direct edge.
    Uses the historical research/research-colony gap as regression case.
    """
    tree = build_synthetic_tree()
    synapses = [
        # Connect paper-dive and research-colony (but not research)
        {"a": "paper-dive", "b": "research-colony", "label": "test", "type": "calls"},
        # Connect qa-agent and audit
        {"a": "qa-agent", "b": "audit", "label": "test", "type": "hook"},
    ]

    gaps = find_gaps(tree, synapses)

    # Should find the research/research-colony gap (AC2 regression)
    research_gaps = [g for g in gaps if g["cat"] == "research"]
    assert len(research_gaps) > 0, "Historical gap not detected: research and research-colony"

    # Specific check: research and research-colony must be flagged
    pairs = {(g["node_a"], g["node_b"]) for g in research_gaps}
    assert ("research", "research-colony") in pairs or (
        "research-colony",
        "research",
    ) in pairs, "Missing gap: research ↔ research-colony"

    # Quality nodes are connected, so no gap expected
    quality_gaps = [g for g in gaps if g["cat"] == "quality"]
    assert len(quality_gaps) == 0, f"Unexpected gap in quality: {quality_gaps}"


def test_find_gaps_excludes_ancestor_descendants():
    """Pairs with ancestor/descendant relationship are excluded."""
    tree = build_synthetic_tree()
    synapses = []  # No edges

    gaps = find_gaps(tree, synapses)

    # MARVIN is root, but we expect ancestor/descendant exclusion
    # to prevent MARVIN-research, MARVIN-research-colony, etc. gaps
    marvin_pairs = [g for g in gaps if g["node_a"] == "MARVIN" or g["node_b"] == "MARVIN"]
    assert (
        len(marvin_pairs) == 0
    ), f"Ancestor pairs should be excluded, got: {marvin_pairs}"


def test_find_gaps_excludes_empty_desc():
    """Nodes with empty descriptions are excluded from gaps."""
    tree = build_synthetic_tree()
    synapses = []

    gaps = find_gaps(tree, synapses)

    # wrapper-empty should not appear in any findings
    for gap in gaps:
        assert gap["node_a"] != "wrapper-empty"
        assert gap["node_b"] != "wrapper-empty"


def test_find_gaps_multiple_in_category():
    """When one pair in a category has edge, others are still found."""
    tree = build_synthetic_tree()
    synapses = [
        # Only connect paper-dive and research-colony
        {"a": "paper-dive", "b": "research-colony", "label": "test", "type": "calls"},
    ]

    gaps = find_gaps(tree, synapses)
    research_gaps = [g for g in gaps if g["cat"] == "research"]

    # Three research nodes (research, research-colony, paper-dive)
    # One edge (paper-dive ↔ research-colony) → 2 gaps expected:
    # research ↔ research-colony, research ↔ paper-dive
    assert len(research_gaps) == 2, f"Expected 2 gaps, got {len(research_gaps)}: {research_gaps}"


def test_find_gaps_empty_tree():
    """Empty or minimal tree produces no gaps."""
    tree = {"id": "MARVIN", "cat": "root", "desc": "Root", "children": []}
    synapses = []
    gaps = find_gaps(tree, synapses)
    assert gaps == []


if __name__ == "__main__":
    # Run tests manually
    test_collect_nodes_with_ancestors()
    print("✓ test_collect_nodes_with_ancestors")

    test_is_ancestor_of()
    print("✓ test_is_ancestor_of")

    test_has_direct_edge()
    print("✓ test_has_direct_edge")

    test_find_gaps_same_category_no_edge()
    print("✓ test_find_gaps_same_category_no_edge (includes AC2 regression)")

    test_find_gaps_excludes_ancestor_descendants()
    print("✓ test_find_gaps_excludes_ancestor_descendants")

    test_find_gaps_excludes_empty_desc()
    print("✓ test_find_gaps_excludes_empty_desc")

    test_find_gaps_multiple_in_category()
    print("✓ test_find_gaps_multiple_in_category")

    test_find_gaps_empty_tree()
    print("✓ test_find_gaps_empty_tree")

    print("\nAll tests passed!")
