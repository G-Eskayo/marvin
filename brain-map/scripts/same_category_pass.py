#!/usr/bin/env python3
"""
same_category_pass.py — detect disconnected nodes that share a category tag.

Reads brain-map/tree-data.json and identifies pairs of nodes that both have the
same category tag (cat field) but have no direct synapse edge between them.

Reasoning: nodes in the same category often have implicit semantic coupling —
missing direct edges may indicate undeclared relationships, shared context, or
opportunities for cross-reference.

Algorithm:
  1. Walk the tree and collect all nodes with non-empty descriptions
  2. Record each node's ancestor chain (for exclusion of ancestor/descendant pairs)
  3. Group nodes by category
  4. For each category with 2+ nodes, generate all pairs
  5. Exclude pairs where one is an ancestor of the other
  6. Exclude pairs with a direct synapse edge
  7. Emit findings for remaining pairs

Output: brain-map/reports/same-category-gaps.json + .md rollup
"""
from __future__ import annotations
import json
import sys
from itertools import combinations
from pathlib import Path
from typing import TypedDict

HERE = Path(__file__).parent.parent
TREE_DATA_PATH = HERE / "tree-data.json"
OUTPUT_DIR = HERE / "reports"
OUTPUT_JSON = OUTPUT_DIR / "same-category-gaps.json"
OUTPUT_MD = OUTPUT_DIR / "same-category-gaps.md"


class Finding(TypedDict):
    kind: str
    cat: str
    node_a: str
    node_b: str
    reason: str


def collect_nodes_with_ancestors(
    node: dict, ancestors: list[str] | None = None
) -> dict[str, tuple[str, list[str]]]:
    """
    Recursively walk tree, returning {node_id: (cat, ancestor_ids)}.
    Excludes nodes with empty or missing descriptions.
    """
    if ancestors is None:
        ancestors = []

    result: dict[str, tuple[str, list[str]]] = {}

    # Include this node if it has a non-empty description
    node_id = node.get("id")
    node_cat = node.get("cat", "")
    node_desc = node.get("desc", "")
    if node_id and node_cat and node_desc.strip():
        result[node_id] = (node_cat, ancestors.copy())

    # Recurse to children
    for child in node.get("children", []):
        child_results = collect_nodes_with_ancestors(
            child, ancestors + [node_id] if node_id else ancestors
        )
        result.update(child_results)

    return result


def is_ancestor_of(potential_ancestor_id: str, node_id: str, nodes_with_ancestors: dict) -> bool:
    """Check if potential_ancestor_id is in the ancestor chain of node_id."""
    if node_id not in nodes_with_ancestors:
        return False
    _, ancestors = nodes_with_ancestors[node_id]
    return potential_ancestor_id in ancestors


def has_direct_edge(node_a: str, node_b: str, synapses: list[dict]) -> bool:
    """Check if any synapse connects node_a and node_b (either direction)."""
    for synapse in synapses:
        a, b = synapse.get("a", ""), synapse.get("b", "")
        if (a == node_a and b == node_b) or (a == node_b and b == node_a):
            return True
    return False


def find_gaps(tree: dict, synapses: list[dict]) -> list[Finding]:
    """Find pairs of same-category nodes with no direct edge, excluding ancestor/descendant."""
    nodes_with_ancestors = collect_nodes_with_ancestors(tree)

    # Group nodes by category
    by_category: dict[str, list[str]] = {}
    for node_id, (cat, _) in nodes_with_ancestors.items():
        if cat not in by_category:
            by_category[cat] = []
        by_category[cat].append(node_id)

    findings: list[Finding] = []

    for cat, node_ids in by_category.items():
        if len(node_ids) < 2:
            continue  # No pairs to check

        for node_a, node_b in combinations(sorted(node_ids), 2):
            # Skip ancestor/descendant pairs
            if is_ancestor_of(node_a, node_b, nodes_with_ancestors) or is_ancestor_of(
                node_b, node_a, nodes_with_ancestors
            ):
                continue

            # Skip pairs with direct edge
            if has_direct_edge(node_a, node_b, synapses):
                continue

            findings.append(
                Finding(
                    kind="same-category",
                    cat=cat,
                    node_a=node_a,
                    node_b=node_b,
                    reason=f"both tagged '{cat}' but have no synapse between them",
                )
            )

    return sorted(findings, key=lambda f: (f["cat"], f["node_a"], f["node_b"]))


def render_markdown(findings: list[Finding]) -> str:
    """Generate human-readable markdown report."""
    lines = [
        "# Same Category Gaps",
        "",
        f"Found {len(findings)} node pair(s) sharing a category but lacking direct synapse.",
        "",
    ]

    if not findings:
        lines.append("No gaps detected.")
        return "\n".join(lines)

    # Group by category for readability
    by_cat: dict[str, list[Finding]] = {}
    for finding in findings:
        cat = finding["cat"]
        if cat not in by_cat:
            by_cat[cat] = []
        by_cat[cat].append(finding)

    for cat, group in sorted(by_cat.items()):
        lines.append(f"## {cat}")
        lines.append("")
        for finding in sorted(group, key=lambda f: (f["node_a"], f["node_b"])):
            lines.append(
                f"- **{finding['node_a']}** ↔ **{finding['node_b']}**: "
                f"{finding['reason']}"
            )
        lines.append("")

    return "\n".join(lines)


def main() -> None:
    if not TREE_DATA_PATH.exists():
        print(
            f"ERROR: {TREE_DATA_PATH} not found. Run brain-map/generate.py first.",
            file=sys.stderr,
        )
        sys.exit(1)

    data = json.loads(TREE_DATA_PATH.read_text(encoding="utf-8"))
    tree, synapses = data["tree"], data["synapses"]

    findings = find_gaps(tree, synapses)

    # Ensure output directory exists
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Write JSON
    OUTPUT_JSON.write_text(
        json.dumps(findings, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    # Write markdown
    md_content = render_markdown(findings)
    OUTPUT_MD.write_text(md_content, encoding="utf-8")

    print(f"Found {len(findings)} same-category gap(s)")
    print(f"  JSON:  {OUTPUT_JSON}")
    print(f"  Markdown: {OUTPUT_MD}")


if __name__ == "__main__":
    main()
