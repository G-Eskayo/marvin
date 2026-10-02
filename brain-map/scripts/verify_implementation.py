#!/usr/bin/env python3
"""
Quick verification that the implementation is correct by importing and running
a subset of the tests. This is used for manual verification.
"""
import sys
from pathlib import Path

# Change to script directory and import
sys.path.insert(0, str(Path(__file__).parent))

try:
    from shared_resource_pass import (
        find_resources,
        touchers_by_resource,
        has_direct_edge,
        find_gaps,
    )
    print("✓ Successfully imported all functions from shared_resource_pass")
except ImportError as e:
    print(f"✗ Import failed: {e}")
    sys.exit(1)

# Verify TypedDict is available (used in Finding class)
try:
    from typing import TypedDict
    print("✓ TypedDict available")
except ImportError:
    print("✗ TypedDict not available")
    sys.exit(1)

# Quick sanity check: run find_resources on a simple tree
simple_tree = {
    "id": "MARVIN",
    "cat": "root",
    "children": [
        {
            "id": "Memory",
            "cat": "memory",
            "children": [
                {"id": "qa-knowledge", "cat": "memory"},
                {"id": "research-feed", "cat": "memory"},
            ],
        }
    ],
}

resources = find_resources(simple_tree)
if resources == {"qa-knowledge", "research-feed"}:
    print("✓ find_resources() works correctly")
else:
    print(f"✗ find_resources() returned {resources}, expected {{'qa-knowledge', 'research-feed'}}")
    sys.exit(1)

# Test touchers_by_resource
synapses = [
    {"a": "qa-agent", "b": "qa-knowledge", "label": "test", "type": "hook"},
    {"a": "creative", "b": "qa-knowledge", "label": "test", "type": "hook"},
]
touchers = touchers_by_resource(synapses, resources)
if touchers["qa-knowledge"] == {"qa-agent", "creative"}:
    print("✓ touchers_by_resource() works correctly")
else:
    print(f"✗ touchers_by_resource() returned unexpected result: {touchers}")
    sys.exit(1)

# Test has_direct_edge
synapses2 = [
    {"a": "a", "b": "b", "label": "test", "type": "calls"},
]
if has_direct_edge("a", "b", synapses2) and has_direct_edge("b", "a", synapses2):
    print("✓ has_direct_edge() works correctly (both directions)")
else:
    print("✗ has_direct_edge() failed bidirectional check")
    sys.exit(1)

# Test find_gaps with a realistic scenario
gaps = find_gaps(simple_tree, synapses)
if len(gaps) == 1:  # One pair (qa-agent, creative) with no edge
    gap = gaps[0]
    if (
        gap["kind"] == "shared-resource"
        and "qa-knowledge" in gap["resources"]
        and {gap["node_a"], gap["node_b"]} == {"qa-agent", "creative"}
    ):
        print("✓ find_gaps() produces correct findings")
    else:
        print(f"✗ find_gaps() returned malformed finding: {gap}")
        sys.exit(1)
else:
    print(f"✗ find_gaps() returned {len(gaps)} gaps, expected 1")
    sys.exit(1)

print("\n✅ All verifications passed! Implementation is correct.")
print("\nTo run full test suite: python test_shared_resource_pass.py")
print("To run against real tree-data.json: python shared_resource_pass.py")
