#!/usr/bin/env python3
"""
Tests for shared_resource_pass.py — detects when multiple skills touch the same
resource (Memory node) but have no direct synapse between each other.
"""
import json
from pathlib import Path
import sys
import tempfile

# Import the module under test
sys.path.insert(0, str(Path(__file__).parent))
from shared_resource_pass import (
    find_resources,
    touchers_by_resource,
    has_direct_edge,
    find_gaps,
)


def build_synthetic_tree():
    """Minimal tree fixture with Memory trunk and resource children."""
    return {
        "id": "MARVIN",
        "cat": "root",
        "desc": "Memory, routing, and skills layer",
        "children": [
            {
                "id": "Memory",
                "cat": "memory",
                "desc": "Persistent context",
                "children": [
                    {
                        "id": "qa-knowledge",
                        "cat": "memory",
                        "desc": "ChromaDB — patterns/anti-patterns",
                    },
                    {
                        "id": "research-feed",
                        "cat": "memory",
                        "desc": "ChromaDB — arXiv/GitHub/HN",
                    },
                    {"id": "lexicon.md", "cat": "memory", "desc": "Shared vocabulary"},
                ],
            }
        ],
    }


def test_find_resources():
    """Verify resource discovery from Memory trunk."""
    tree = build_synthetic_tree()
    resources = find_resources(tree)
    assert resources == {"qa-knowledge", "research-feed", "lexicon.md"}


def test_touchers_by_resource():
    """Verify collection of nodes touching each resource."""
    synapses = [
        {"a": "qa-agent", "b": "qa-knowledge", "label": "test", "type": "hook"},
        {"a": "creative", "b": "qa-knowledge", "label": "test", "type": "undeclared"},
        {"a": "daily-digest", "b": "qa-knowledge", "label": "test", "type": "hook"},
        {"a": "research-colony", "b": "research-feed", "label": "test", "type": "hook"},
    ]
    resources = {"qa-knowledge", "research-feed", "lexicon.md"}
    touchers = touchers_by_resource(synapses, resources)

    assert touchers["qa-knowledge"] == {"qa-agent", "creative", "daily-digest"}
    assert touchers["research-feed"] == {"research-colony"}
    assert touchers["lexicon.md"] == set()


def test_has_direct_edge():
    """Verify direct-edge detection in both directions."""
    synapses = [
        {"a": "qa-agent", "b": "creative", "label": "test", "type": "calls"},
        {"a": "paper-dive", "b": "research-colony", "label": "test", "type": "hook"},
    ]

    assert has_direct_edge("qa-agent", "creative", synapses) is True
    assert has_direct_edge("creative", "qa-agent", synapses) is True  # reverse
    assert has_direct_edge("paper-dive", "research-colony", synapses) is True
    assert has_direct_edge("qa-agent", "daily-digest", synapses) is False


def test_find_gaps_no_edge_between_touchers():
    """Detect pairs of touchers with no direct edge (the core finding)."""
    tree = build_synthetic_tree()
    synapses = [
        # qa-knowledge touchers: qa-agent, creative, daily-digest (no edges between them)
        {"a": "qa-agent", "b": "qa-knowledge", "label": "test", "type": "hook"},
        {"a": "creative", "b": "qa-knowledge", "label": "test", "type": "undeclared"},
        {"a": "daily-digest", "b": "qa-knowledge", "label": "test", "type": "hook"},
        # research-colony also touches qa-knowledge
        {
            "a": "research-colony",
            "b": "qa-knowledge",
            "label": "test",
            "type": "hook",
        },
    ]

    gaps = find_gaps(tree, synapses)

    # For qa-knowledge with 4 touchers, 0 direct edges: C(4,2) = 6 pairs
    qa_gaps = [g for g in gaps if "qa-knowledge" in g.get("resources", [])]
    assert len(qa_gaps) == 6, f"Expected 6 gaps, got {len(qa_gaps)}: {qa_gaps}"

    # Verify they all reference qa-knowledge and have a reason
    for gap in qa_gaps:
        assert "qa-knowledge" in gap["resources"]
        assert "reason" in gap
        assert "shared-resource" == gap["kind"]


def test_find_gaps_with_one_direct_edge():
    """Pairs with a direct edge are excluded from gaps."""
    tree = build_synthetic_tree()
    synapses = [
        # qa-knowledge touchers: qa-agent, creative, daily-digest
        {"a": "qa-agent", "b": "qa-knowledge", "label": "test", "type": "hook"},
        {"a": "creative", "b": "qa-knowledge", "label": "test", "type": "undeclared"},
        {"a": "daily-digest", "b": "qa-knowledge", "label": "test", "type": "hook"},
        # One direct edge between qa-agent and creative
        {"a": "qa-agent", "b": "creative", "label": "test", "type": "calls"},
    ]

    gaps = find_gaps(tree, synapses)
    qa_gaps = [g for g in gaps if "qa-knowledge" in g.get("resources", [])]

    # C(3,2) = 3 total pairs, minus 1 with direct edge = 2 gaps
    assert len(qa_gaps) == 2, f"Expected 2 gaps, got {len(qa_gaps)}: {qa_gaps}"
    pairs = {(g["node_a"], g["node_b"]) for g in qa_gaps}
    # The pair (qa-agent, creative) should NOT be present since they have a direct edge
    assert ("qa-agent", "creative") not in pairs
    assert ("creative", "qa-agent") not in pairs


def test_find_gaps_multi_resource_dedup():
    """Pairs touching multiple resources are merged into one finding."""
    tree = build_synthetic_tree()
    synapses = [
        # Pair (qa-agent, creative) touches both qa-knowledge and research-feed
        {"a": "qa-agent", "b": "qa-knowledge", "label": "test", "type": "hook"},
        {"a": "creative", "b": "qa-knowledge", "label": "test", "type": "undeclared"},
        {"a": "qa-agent", "b": "research-feed", "label": "test", "type": "hook"},
        {"a": "creative", "b": "research-feed", "label": "test", "type": "hook"},
    ]

    gaps = find_gaps(tree, synapses)

    # Should have exactly 1 gap for the pair (qa-agent, creative), with both resources
    assert len(gaps) == 1
    gap = gaps[0]
    assert set(gap["resources"]) == {"qa-knowledge", "research-feed"}
    assert set([gap["node_a"], gap["node_b"]]) == {"qa-agent", "creative"}


def test_find_gaps_empty_tree():
    """Empty resource set produces no gaps."""
    tree = {
        "id": "MARVIN",
        "cat": "root",
        "desc": "Test",
        "children": [],
    }
    synapses = []
    gaps = find_gaps(tree, synapses)
    assert gaps == []


if __name__ == "__main__":
    # Run tests manually
    test_find_resources()
    print("✓ test_find_resources")

    test_touchers_by_resource()
    print("✓ test_touchers_by_resource")

    test_has_direct_edge()
    print("✓ test_has_direct_edge")

    test_find_gaps_no_edge_between_touchers()
    print("✓ test_find_gaps_no_edge_between_touchers")

    test_find_gaps_with_one_direct_edge()
    print("✓ test_find_gaps_with_one_direct_edge")

    test_find_gaps_multi_resource_dedup()
    print("✓ test_find_gaps_multi_resource_dedup")

    test_find_gaps_empty_tree()
    print("✓ test_find_gaps_empty_tree")

    print("\nAll tests passed!")
