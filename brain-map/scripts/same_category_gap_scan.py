#!/usr/bin/env python3
"""
Scan tree-data.json for same-category node pairs with no connecting synapse.
Identifies potential missing relationships between nodes sharing semantic categories.
"""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path
from collections import defaultdict


QUEUE_FILE = Path.home() / ".claude" / "improvement-queue.md"


def load_tree_data(path: Path | str = None) -> dict:
    """Load tree-data.json, or a test fixture with the same structure."""
    if path is None:
        path = Path.home() / ".agents" / "brain-map" / "tree-data.json"
    else:
        path = Path(path)

    if not path.exists():
        raise FileNotFoundError(f"tree-data.json not found at {path}")

    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def flatten(tree: dict) -> dict[str, dict]:
    """Recursively collect all nodes by id from the tree structure.
    Excludes pure layout wrapper nodes (cat in {"root", "skills-trunk"})."""
    nodes = {}

    def visit(node: dict) -> None:
        node_id = node.get("id")
        cat = node.get("cat")

        # Skip structural wrappers
        if cat not in ("root", "skills-trunk"):
            if node_id:
                nodes[node_id] = node

        # Recurse into children
        for child in node.get("children", []):
            visit(child)

    visit(tree)
    return nodes


def load_manifest_tags(path: Path | str = None) -> dict[str, set[str]]:
    """Load intent:/domain: tags from manifest.json by skill name.
    Gracefully handles missing file or parse errors."""
    if path is None:
        path = Path.home() / ".claude" / "manifest.json"
    else:
        path = Path(path)

    result = {}
    try:
        with path.open("r", encoding="utf-8") as f:
            manifest = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return result

    for entry in manifest.get("index", []):
        name = entry.get("name")
        if not name:
            continue

        tags = set()
        for field in ("intent", "domain"):
            val = entry.get(field)
            if val:
                if isinstance(val, list):
                    for v in val:
                        tags.add(f"{field}:{v}")
                else:
                    tags.add(f"{field}:{val}")

        if tags:
            result[name] = tags

    return result


def categories_of(node: dict, manifest_tags: dict[str, set[str]]) -> set[str]:
    """Return union of node's cat field and its intent:/domain: tags from manifest."""
    cats = set()

    # Add the node's own cat field
    if "cat" in node:
        cats.add(node["cat"])

    # Add intent:/domain: tags from manifest (if this node is in manifest)
    node_id = node.get("id")
    if node_id and node_id in manifest_tags:
        cats.update(manifest_tags[node_id])

    return cats


def existing_edges(synapses: list[dict]) -> set[frozenset[str, str]]:
    """Build undirected edge set from synapses list."""
    edges = set()
    for synapse in synapses:
        a = synapse.get("a")
        b = synapse.get("b")
        if a and b:
            edges.add(frozenset([a, b]))
    return edges


def find_gaps(
    nodes: dict[str, dict],
    manifest_tags: dict[str, set[str]],
    edges: set[frozenset[str, str]],
) -> list[dict]:
    """Find pairs of nodes sharing a category with no connecting synapse.
    Deduplicates pairs that share multiple categories into a single finding."""

    # Group nodes by category
    by_category: dict[str, list[str]] = defaultdict(list)
    for node_id, node in nodes.items():
        for cat in categories_of(node, manifest_tags):
            by_category[cat].append(node_id)

    # Find missing edges within each category
    findings = {}  # key: frozenset([a, b]), value: {node_a, node_b, shared_categories: set}

    for cat, node_ids in by_category.items():
        # Only consider categories with 2+ members
        if len(node_ids) < 2:
            continue

        # Check all pairs within this category
        for i, a in enumerate(node_ids):
            for b in node_ids[i + 1:]:
                pair = frozenset([a, b])

                # Skip if edge exists
                if pair in edges:
                    continue

                # Record or update finding
                if pair not in findings:
                    findings[pair] = {
                        "node_a": a,
                        "node_b": b,
                        "shared_categories": set(),
                    }
                findings[pair]["shared_categories"].add(cat)

    # Convert to list and sort for consistency
    result = []
    for pair, data in sorted(findings.items(), key=lambda x: (x[1]["node_a"], x[1]["node_b"])):
        result.append({
            "node_a": data["node_a"],
            "node_b": data["node_b"],
            "shared_categories": sorted(data["shared_categories"]),
            "desc_a": nodes[data["node_a"]].get("desc", ""),
            "desc_b": nodes[data["node_b"]].get("desc", ""),
        })

    return result


def append_to_queue(findings: list[dict]) -> None:
    """Append findings to ~/.claude/improvement-queue.md using the standard block format."""
    if not findings:
        return

    # Import the appending logic from improvement_sweep.py conventions
    from datetime import datetime

    lines = []
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines.append(f"## Brain-map same-category gaps ({timestamp})")
    lines.append("")

    for finding in findings:
        cats = ", ".join(finding["shared_categories"])
        a = finding["node_a"]
        b = finding["node_b"]
        lines.append(f"- `{a}` ↔ `{b}` (shared: {cats})")

    lines.append("")

    try:
        with QUEUE_FILE.open("a", encoding="utf-8") as f:
            f.write("\n".join(lines))
    except Exception as e:
        print(f"Warning: could not append to improvement queue: {e}", file=sys.stderr)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Scan tree-data.json for same-category node pairs with no synapse."
    )
    parser.add_argument(
        "--tree-data",
        type=Path,
        default=None,
        help="Path to tree-data.json (default: ~/.agents/brain-map/tree-data.json)",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=None,
        help="Path to manifest.json (default: ~/.claude/manifest.json)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output as JSON instead of human-readable list",
    )
    parser.add_argument(
        "--append-to-queue",
        action="store_true",
        help="Append findings to ~/.claude/improvement-queue.md",
    )

    args = parser.parse_args()

    try:
        data = load_tree_data(args.tree_data)
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    tree = data.get("tree", {})
    synapses = data.get("synapses", [])

    nodes = flatten(tree)
    manifest_tags = load_manifest_tags(args.manifest)
    edges = existing_edges(synapses)

    gaps = find_gaps(nodes, manifest_tags, edges)

    if args.json:
        print(json.dumps(gaps, indent=2, ensure_ascii=False))
    else:
        if not gaps:
            print("No same-category gaps found.")
        else:
            print(f"Found {len(gaps)} same-category gap(s):\n")
            for finding in gaps:
                a = finding["node_a"]
                b = finding["node_b"]
                cats = ", ".join(finding["shared_categories"])
                print(f"  {a} ↔ {b}")
                print(f"    Shared: {cats}")
                if finding["desc_a"]:
                    print(f"    {a}: {finding['desc_a']}")
                if finding["desc_b"]:
                    print(f"    {b}: {finding['desc_b']}")
                print()

    if args.append_to_queue:
        append_to_queue(gaps)

    sys.exit(0)


if __name__ == "__main__":
    main()
