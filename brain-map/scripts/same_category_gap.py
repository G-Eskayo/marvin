#!/usr/bin/env python3
"""Find same-category leaf nodes with no synapse connection.

Reads tree-data.json and identifies pairs of leaf nodes (nodes with children=[])
that share the same category but have no synapse edge between them.

Usage:
    ~/.agents/venv/bin/python brain-map/scripts/same_category_gap.py
    ~/.agents/venv/bin/python brain-map/scripts/same_category_gap.py <path-to-tree-data.json>
"""
from __future__ import annotations
import json
import sys
from pathlib import Path


def find_gaps(tree_data: dict) -> list[dict]:
    """Identify leaf-node pairs in the same category with no synapse.

    Args:
        tree_data: dict with keys "tree" (nested node structure) and "synapses" (edges)

    Returns:
        list of dicts with keys "a" (node_id), "b" (node_id), "cat" (category)
    """
    tree = tree_data.get("tree", {})
    synapses = tree_data.get("synapses", [])

    # Flatten tree to leaf nodes only
    leaves: list[dict] = []

    def collect_leaves(node: dict) -> None:
        children = node.get("children", [])
        if not children:  # leaf node
            leaves.append(node)
        else:  # container node
            for child in children:
                collect_leaves(child)

    collect_leaves(tree)

    # Build set of connected pairs (undirected)
    connected = set()
    for synapse in synapses:
        a, b = synapse.get("a"), synapse.get("b")
        if a and b:
            # Store as frozenset to make undirected comparison work
            connected.add(frozenset([a, b]))

    # Group leaves by category
    by_category: dict[str, list[dict]] = {}
    for leaf in leaves:
        cat = leaf.get("cat")
        if cat:
            by_category.setdefault(cat, []).append(leaf)

    # Find gaps within each category
    gaps: list[dict] = []
    for cat, nodes in by_category.items():
        # Compare all pairs within category
        for i, node_a in enumerate(nodes):
            for node_b in nodes[i + 1:]:
                pair = frozenset([node_a["id"], node_b["id"]])
                if pair not in connected:
                    gaps.append({
                        "a": node_a["id"],
                        "b": node_b["id"],
                        "cat": cat,
                    })

    return gaps


def format_gap(gap: dict) -> str:
    """Format a single gap for human-readable output.

    Args:
        gap: dict with keys "a", "b", "cat"

    Returns:
        formatted string
    """
    return f"{gap['cat']}: {gap['a']} <-> {gap['b']}"


def main() -> None:
    # Determine tree-data.json path
    if len(sys.argv) > 1:
        tree_data_path = Path(sys.argv[1])
    else:
        script_dir = Path(__file__).parent
        tree_data_path = script_dir.parent / "tree-data.json"

    if not tree_data_path.exists():
        print(f"ERROR: tree-data.json not found at {tree_data_path}", file=sys.stderr)
        sys.exit(1)

    try:
        tree_data = json.loads(tree_data_path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"ERROR: failed to read {tree_data_path}: {e}", file=sys.stderr)
        sys.exit(1)

    gaps = find_gaps(tree_data)

    if not gaps:
        print("No same-category gaps found.")
        return

    # Sort for deterministic output
    gaps.sort(key=lambda g: (g["cat"], g["a"], g["b"]))

    print(f"Found {len(gaps)} same-category gap(s):\n")
    for gap in gaps:
        print(format_gap(gap))


if __name__ == "__main__":
    main()
