#!/usr/bin/env python3
"""
same_category_pass.py — Detect same-category skill/agent pairs with no synapse.

This is the cheap, literal connectivity pass: matches nodes purely by their
existing `cat` field. Pairs sharing a category but with no synapse between them
are potential candidates for new edges (issues #31 semantic-similarity and
#32 shared-resource will add fuzzier matching).

Input: brain-map/tree-data.json (or --input PATH)
  {"tree": <nested node structure>, "synapses": [{"a","b","label","type"}]}

Output:
  - Writes dated section to brain-map/connection-candidates.md
  - Prints human-readable summary to stdout
  - Exits 0 on success (even if zero findings), non-zero only on genuine failure
    (missing input file, parse error, etc.)

Filters applied:
  - Excludes nodes with desc == "" (pure category-label wrapper nodes)
  - Excludes ancestor/descendant pairs (tree edges already document those)
  - Treats synapses as undirected (a→b counts as connecting both)

NOTE: AC3 (destination of findings) cannot be fully satisfied until issue #45
decides where findings should live. Currently defaulting to dedicated report
file (brain-map/connection-candidates.md). Once #45 lands, the write_findings()
function can be redirected to post-process or write elsewhere instead.
"""
import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


def collect_nodes_with_ancestors(
    node: dict[str, Any], parent_chain: list[str], all_nodes: dict[str, dict]
) -> None:
    """Walk tree recursively, recording each node and its ancestor chain."""
    node_id = node.get("id")
    desc = node.get("desc", "")
    cat = node.get("cat", "")

    if node_id:
        all_nodes[node_id] = {
            "cat": cat,
            "desc": desc,
            "ancestors": parent_chain.copy(),
        }

    current_chain = parent_chain + ([node_id] if node_id else [])
    for child in node.get("children", []):
        collect_nodes_with_ancestors(child, current_chain, all_nodes)


def is_ancestor_descendant(node_id_a: str, node_id_b: str, all_nodes: dict) -> bool:
    """Check if a and b are in an ancestor/descendant relationship."""
    ancestors_a = set(all_nodes[node_id_a]["ancestors"])
    ancestors_b = set(all_nodes[node_id_b]["ancestors"])
    # a is ancestor of b if a is in b's ancestor chain
    if node_id_a in ancestors_b:
        return True
    # b is ancestor of a if b is in a's ancestor chain
    if node_id_b in ancestors_a:
        return True
    return False


def load_tree_data(input_path: str) -> tuple[dict, list]:
    """Load tree-data.json, returning (all_nodes, synapses)."""
    path = Path(input_path)
    if not path.exists():
        print(
            f"ERROR: {input_path} not found. Run brain-map/generate.py first.",
            file=sys.stderr,
        )
        sys.exit(1)

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        print(f"ERROR: failed to parse {input_path}: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"ERROR: failed to read {input_path}: {e}", file=sys.stderr)
        sys.exit(1)

    tree = data.get("tree", {})
    synapses = data.get("synapses", [])

    # Walk tree and collect all nodes with their ancestor chains
    all_nodes: dict[str, dict] = {}
    collect_nodes_with_ancestors(tree, [], all_nodes)

    return all_nodes, synapses


def build_connected_pairs(synapses: list) -> set[tuple[str, str]]:
    """Return set of connected id-pairs from synapses (treated as undirected)."""
    connected = set()
    for synapse in synapses:
        a = synapse.get("a")
        b = synapse.get("b")
        if a and b:
            # Store as sorted tuple for consistent comparison
            pair = tuple(sorted([a, b]))
            connected.add(pair)
    return connected


def find_same_category_gaps(
    all_nodes: dict[str, dict], connected: set[tuple[str, str]]
) -> list[dict[str, str]]:
    """Find same-category pairs with no synapse, excluding ancestors/descendants."""
    # Group nodes by category, excluding empty descriptions
    by_category: dict[str, list[str]] = {}
    for node_id, info in all_nodes.items():
        if info["desc"] == "":
            continue
        cat = info["cat"]
        if cat not in by_category:
            by_category[cat] = []
        by_category[cat].append(node_id)

    gaps = []
    for cat, node_ids in by_category.items():
        # Generate all pairs within this category
        for i, id_a in enumerate(node_ids):
            for id_b in node_ids[i + 1 :]:
                pair = tuple(sorted([id_a, id_b]))
                # Skip if already connected
                if pair in connected:
                    continue
                # Skip if ancestor/descendant
                if is_ancestor_descendant(id_a, id_b, all_nodes):
                    continue
                gaps.append({"a": id_a, "b": id_b, "cat": cat})

    return gaps


def write_findings(gaps: list[dict[str, str]], report_path: str) -> None:
    """Write findings to connection-candidates.md in dated section format.

    This function is the destination for AC3 findings. Once issue #45 decides
    where findings should live, the write logic here can be redirected or
    post-processed (e.g., to append to improvement-queue.md instead).
    """
    timestamp = datetime.now().isoformat(timespec="seconds")
    section_header = f"## {timestamp} — same-category pass"

    report_path_obj = Path(report_path)
    report_path_obj.parent.mkdir(parents=True, exist_ok=True)

    # Read existing content if file exists
    existing = ""
    if report_path_obj.exists():
        existing = report_path_obj.read_text(encoding="utf-8")

    # Build new findings section
    findings_lines = [section_header]
    if gaps:
        for gap in gaps:
            findings_lines.append(
                f"- [{gap['a']}](#) ↔ [{gap['b']}](#) (cat: `{gap['cat']}`)"
            )
    else:
        findings_lines.append("- (no gaps found)")

    new_section = "\n".join(findings_lines) + "\n"

    # Append to file
    report_path_obj.write_text(new_section + "\n" + existing, encoding="utf-8")


def print_summary(gaps: list[dict[str, str]]) -> None:
    """Print human-readable summary to stdout."""
    if not gaps:
        print("✓ No same-category gaps found.")
        return

    print(f"Found {len(gaps)} same-category gap(s):")
    by_category = {}
    for gap in gaps:
        cat = gap["cat"]
        if cat not in by_category:
            by_category[cat] = []
        by_category[cat].append(gap)

    for cat in sorted(by_category.keys()):
        print(f"\n  {cat}:")
        for gap in by_category[cat]:
            print(f"    {gap['a']} ↔ {gap['b']}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Detect same-category nodes with no synapse."
    )
    parser.add_argument(
        "--input",
        default="brain-map/tree-data.json",
        help="Path to tree-data.json (default: brain-map/tree-data.json)",
    )
    parser.add_argument(
        "--output",
        default="brain-map/connection-candidates.md",
        help="Path to write report (default: brain-map/connection-candidates.md)",
    )
    args = parser.parse_args()

    all_nodes, synapses = load_tree_data(args.input)
    connected = build_connected_pairs(synapses)
    gaps = find_same_category_gaps(all_nodes, connected)

    write_findings(gaps, args.output)
    print_summary(gaps)


if __name__ == "__main__":
    main()
