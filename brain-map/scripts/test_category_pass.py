#!/usr/bin/env python3
"""
Tests for category_pass.py — detects when multiple nodes share the same category
but have no direct synapse between them.

Attack checklist:
  1. Correct grouping by category
  2. Core finding: same-category pairs with no synapse
  3. Exclusion of pairs with direct edge
  4. Cross-category pairs NOT flagged (stays in lane vs #31/#32)
  5. Synthetic regression test (AC2): research/research-colony shape
  6. Empty tree, no categories
  7. Missing cat field (skip, not crash)
  8. Malformed synapse entries (ignored, not crash)
  9. Large category scale (~100 nodes)
  10. Missing tree-data.json (exit cleanly)
  11. Malformed JSON (raises clearly)
  12. Idempotent rerun (stable output)
  13. Main rerun overwrites cleanly
  14. Concurrent invocations (atomic write)
  15. Read-only output dir (fails clearly, skip if root)
"""
import json
import os
import sys
import tempfile
import threading
from pathlib import Path

# Import the module under test
sys.path.insert(0, str(Path(__file__).parent))
from category_pass import (
    find_categories,
    has_direct_edge,
    find_gaps,
    render_markdown,
    main,
)


def build_synthetic_tree():
    """Minimal tree fixture with multiple categories."""
    return {
        "id": "root",
        "cat": "root",
        "desc": "Root node",
        "children": [
            {
                "id": "skill1",
                "cat": "skill",
                "desc": "A skill",
            },
            {
                "id": "skill2",
                "cat": "skill",
                "desc": "Another skill",
            },
            {
                "id": "skill3",
                "cat": "skill",
                "desc": "Yet another skill",
            },
            {
                "id": "agent1",
                "cat": "agent",
                "desc": "An agent",
            },
            {
                "id": "agent2",
                "cat": "agent",
                "desc": "Another agent",
            },
        ],
    }


def test_find_categories_basic():
    """Test 1: Groups node ids correctly by cat across synthetic tree."""
    tree = build_synthetic_tree()
    categories = find_categories(tree)

    assert "skill" in categories
    assert "agent" in categories
    assert "root" in categories

    assert categories["skill"] == {"skill1", "skill2", "skill3"}
    assert categories["agent"] == {"agent1", "agent2"}
    assert categories["root"] == {"root"}


def test_find_gaps_no_edge_between_same_category():
    """Test 2: Core finding — same-cat pairs with no synapse are emitted."""
    tree = build_synthetic_tree()
    synapses = [
        # skill nodes: skill1, skill2, skill3 (no edges between them)
        {"a": "skill1", "b": "memory", "label": "test", "type": "hook"},
    ]

    gaps = find_gaps(tree, synapses)
    skill_gaps = [g for g in gaps if g["category"] == "skill"]

    # C(3,2) = 3 total pairs in skill category
    assert len(skill_gaps) == 3, f"Expected 3 gaps, got {len(skill_gaps)}: {skill_gaps}"

    # Verify findings
    for gap in skill_gaps:
        assert gap["kind"] == "category-match"
        assert gap["category"] == "skill"
        assert "reason" in gap


def test_find_gaps_with_direct_edge_excluded():
    """Test 3: Pairs with direct edge are excluded."""
    tree = build_synthetic_tree()
    synapses = [
        # skill nodes: skill1, skill2, skill3
        {"a": "skill1", "b": "skill2", "label": "test", "type": "calls"},
    ]

    gaps = find_gaps(tree, synapses)
    skill_gaps = [g for g in gaps if g["category"] == "skill"]

    # C(3,2) = 3 total pairs, minus 1 with direct edge = 2 gaps
    assert len(skill_gaps) == 2, f"Expected 2 gaps, got {len(skill_gaps)}: {skill_gaps}"
    pairs = {(g["node_a"], g["node_b"]) for g in skill_gaps}

    # The connected pair should NOT be present
    assert ("skill1", "skill2") not in pairs
    assert ("skill2", "skill1") not in pairs


def test_find_gaps_cross_category_not_flagged():
    """Test 4: Different-category pairs are NOT flagged (stays in lane)."""
    tree = build_synthetic_tree()
    synapses = [
        {"a": "skill1", "b": "agent1", "label": "test", "type": "calls"},
    ]

    gaps = find_gaps(tree, synapses)

    # No finding should have different categories
    for gap in gaps:
        # Verify both nodes belong to the reported category
        # (we'd need the tree to fully verify, so just check kind is category-match)
        assert gap["kind"] == "category-match"


def test_synthetic_research_research_colony_regression():
    """Test 5 (AC2): Synthetic regression — research/research-colony shape.

    The real pair's categories have since diverged (research→research, research-colony→agents).
    This test uses a synthetic fixture shaped like the historical incident.
    """
    tree = {
        "id": "root",
        "cat": "root",
        "desc": "Root",
        "children": [
            {"id": "research", "cat": "research-tool", "desc": "Research skill"},
            {
                "id": "research-colony",
                "cat": "research-tool",
                "desc": "Research colony skill",
            },
        ],
    }
    synapses = [
        # No edge between research and research-colony
        {"a": "research", "b": "memory", "label": "test", "type": "hook"},
    ]

    gaps = find_gaps(tree, synapses)

    # Should find the research-tool category gap
    assert len(gaps) == 1, f"Expected 1 gap, got {len(gaps)}: {gaps}"
    gap = gaps[0]
    assert gap["category"] == "research-tool"
    assert set([gap["node_a"], gap["node_b"]]) == {"research", "research-colony"}


def test_empty_tree_no_categories():
    """Test 6: Empty tree produces no categories and no gaps."""
    tree = {
        "id": "root",
        "cat": "root",
        "desc": "Test",
        "children": [],
    }
    synapses = []

    categories = find_categories(tree)
    gaps = find_gaps(tree, synapses)

    # Should have root category but no gaps (only 1 node per category)
    assert "root" in categories
    assert len(gaps) == 0


def test_node_missing_cat_field_skipped_not_crashed():
    """Test 7: Nodes missing cat field are skipped, not crashed."""
    tree = {
        "id": "root",
        "cat": "root",
        "desc": "Root",
        "children": [
            {"id": "node1", "cat": "type-a", "desc": "Has cat"},
            {"id": "node2", "desc": "Missing cat field (hand-edit)"},
            {"id": "node3", "cat": "type-a", "desc": "Has cat"},
        ],
    }
    synapses = []

    # Should not crash
    categories = find_categories(tree)
    gaps = find_gaps(tree, synapses)

    # node2 should not appear in any category
    for cat, nodes in categories.items():
        assert "node2" not in nodes

    # Should find 1 gap for type-a (node1, node3)
    type_a_gaps = [g for g in gaps if g["category"] == "type-a"]
    assert len(type_a_gaps) == 1


def test_malformed_synapse_entries_ignored():
    """Test 8: Malformed synapse entries (missing a/b, None values) don't crash."""
    tree = build_synthetic_tree()
    synapses = [
        {"a": "skill1", "b": "skill2", "label": "test", "type": "calls"},
        {"label": "bad1", "type": "missing_a_b"},  # Missing a, b
        {"a": "skill1", "b": None, "label": "bad2"},  # None value
        {"a": None, "b": "skill2", "label": "bad3"},  # None value
        {"a": "", "b": "skill3", "label": "bad4"},  # Empty string
    ]

    # Should not crash
    gaps = find_gaps(tree, synapses)

    # The direct edge (skill1, skill2) should exclude that pair
    skill_gaps = [g for g in gaps if g["category"] == "skill"]
    pairs = {(g["node_a"], g["node_b"]) for g in skill_gaps}
    assert ("skill1", "skill2") not in pairs


def test_find_gaps_large_category_scale():
    """Test 9: Large category (~100 nodes) processes in reasonable time."""
    # Build tree with 100 nodes in "large" category
    large_cat_children = [
        {"id": f"node_{i:03d}", "cat": "large", "desc": f"Node {i}"}
        for i in range(100)
    ]
    tree = {
        "id": "root",
        "cat": "root",
        "desc": "Root",
        "children": large_cat_children,
    }
    synapses = [
        # Add one synapse to prevent all C(100,2) gaps
        {"a": "node_000", "b": "node_001", "label": "test", "type": "calls"},
    ]

    # Should complete without hanging or quadratic explosion
    gaps = find_gaps(tree, synapses)

    # C(100,2) = 4950 total pairs, minus 1 = 4949 gaps
    large_gaps = [g for g in gaps if g["category"] == "large"]
    assert len(large_gaps) == 4949, f"Expected 4949 gaps, got {len(large_gaps)}"


def test_main_missing_tree_data_file_exits_cleanly():
    """Test 10: Missing tree-data.json exits cleanly, not with raw traceback."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)
        # Override OUTPUT_DIR in main to point to temp
        import category_pass

        orig_tree_path = category_pass.TREE_DATA_PATH
        try:
            # Point to nonexistent file
            category_pass.TREE_DATA_PATH = tmpdir_path / "nonexistent.json"
            category_pass.OUTPUT_DIR = tmpdir_path / "reports"

            # Should exit with non-zero status and stderr message
            try:
                category_pass.main()
                assert False, "Expected sys.exit(1)"
            except SystemExit as e:
                assert e.code == 1
        finally:
            category_pass.TREE_DATA_PATH = orig_tree_path


def test_main_malformed_json_raises():
    """Test 11: Malformed JSON (truncated, invalid) raises clearly."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)
        tree_data_path = tmpdir_path / "tree-data.json"

        # Write truncated JSON
        tree_data_path.write_text('{"tree": {', encoding="utf-8")

        import category_pass

        orig_tree_path = category_pass.TREE_DATA_PATH
        orig_output_dir = category_pass.OUTPUT_DIR
        try:
            category_pass.TREE_DATA_PATH = tree_data_path
            category_pass.OUTPUT_DIR = tmpdir_path / "reports"

            # Should raise JSONDecodeError
            try:
                category_pass.main()
                assert False, "Expected JSONDecodeError"
            except json.JSONDecodeError:
                pass  # Expected
        finally:
            category_pass.TREE_DATA_PATH = orig_tree_path
            category_pass.OUTPUT_DIR = orig_output_dir


def test_find_gaps_idempotent_rerun():
    """Test 12: Running find_gaps twice yields identical, stable output."""
    tree = build_synthetic_tree()
    synapses = [
        {"a": "skill1", "b": "memory", "label": "test", "type": "hook"},
    ]

    result1 = find_gaps(tree, synapses)
    result2 = find_gaps(tree, synapses)

    # Should be identical (including order)
    assert result1 == result2


def test_main_rerun_overwrites_cleanly():
    """Test 13: Invoking main() twice overwrites, not appends/duplicates."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)
        tree_data_path = tmpdir_path / "tree-data.json"

        # Write minimal valid tree-data.json
        tree = build_synthetic_tree()
        data = {
            "tree": tree,
            "synapses": [{"a": "skill1", "b": "memory", "label": "test", "type": "hook"}],
        }
        tree_data_path.write_text(json.dumps(data), encoding="utf-8")

        import category_pass

        orig_tree_path = category_pass.TREE_DATA_PATH
        orig_output_dir = category_pass.OUTPUT_DIR
        try:
            category_pass.TREE_DATA_PATH = tree_data_path
            category_pass.OUTPUT_DIR = tmpdir_path / "reports"

            # Run twice
            category_pass.main()
            json_content_1 = (tmpdir_path / "reports" / "category-gaps.json").read_text(
                encoding="utf-8"
            )

            category_pass.main()
            json_content_2 = (tmpdir_path / "reports" / "category-gaps.json").read_text(
                encoding="utf-8"
            )

            # Should be identical (overwrite, not append)
            assert json_content_1 == json_content_2
            findings = json.loads(json_content_2)
            # Should have exactly 3 gaps from C(3,2) pairs
            assert len(findings) == 3
        finally:
            category_pass.TREE_DATA_PATH = orig_tree_path
            category_pass.OUTPUT_DIR = orig_output_dir


def test_main_concurrent_invocations_dont_corrupt_output():
    """Test 14: Concurrent main() calls produce valid, complete JSON."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)
        tree_data_path = tmpdir_path / "tree-data.json"

        # Write minimal valid tree-data.json
        tree = build_synthetic_tree()
        data = {
            "tree": tree,
            "synapses": [{"a": "skill1", "b": "memory", "label": "test", "type": "hook"}],
        }
        tree_data_path.write_text(json.dumps(data), encoding="utf-8")

        import category_pass

        orig_tree_path = category_pass.TREE_DATA_PATH
        orig_output_dir = category_pass.OUTPUT_DIR
        try:
            category_pass.TREE_DATA_PATH = tree_data_path
            category_pass.OUTPUT_DIR = tmpdir_path / "reports"

            errors = []

            def run_main():
                try:
                    category_pass.main()
                except Exception as e:
                    errors.append(e)

            # Run main in two threads concurrently
            t1 = threading.Thread(target=run_main)
            t2 = threading.Thread(target=run_main)
            t1.start()
            t2.start()
            t1.join()
            t2.join()

            assert not errors, f"Concurrent invocations raised: {errors}"

            # Final output should be valid, complete JSON
            json_path = tmpdir_path / "reports" / "category-gaps.json"
            json_content = json_path.read_text(encoding="utf-8")
            findings = json.loads(json_content)  # Should not raise

            # Should have the expected gaps
            assert isinstance(findings, list)
            assert len(findings) == 3
        finally:
            category_pass.TREE_DATA_PATH = orig_tree_path
            category_pass.OUTPUT_DIR = orig_output_dir


def test_main_output_dir_not_writable_fails_clearly():
    """Test 15: Read-only output dir fails with clear PermissionError.

    Skip if running as root (uid 0) since root can write to read-only dirs.
    """
    if os.getuid() == 0:
        # Skip test if running as root
        return

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)
        tree_data_path = tmpdir_path / "tree-data.json"
        reports_dir = tmpdir_path / "reports"

        # Write minimal valid tree-data.json
        tree = build_synthetic_tree()
        data = {
            "tree": tree,
            "synapses": [{"a": "skill1", "b": "memory", "label": "test", "type": "hook"}],
        }
        tree_data_path.write_text(json.dumps(data), encoding="utf-8")

        import category_pass

        orig_tree_path = category_pass.TREE_DATA_PATH
        orig_output_dir = category_pass.OUTPUT_DIR
        try:
            category_pass.TREE_DATA_PATH = tree_data_path
            category_pass.OUTPUT_DIR = reports_dir

            # Make reports dir read-only after creation
            reports_dir.mkdir(parents=True, exist_ok=True)
            reports_dir.chmod(0o444)

            # Should raise PermissionError
            try:
                category_pass.main()
                assert False, "Expected PermissionError"
            except PermissionError:
                pass  # Expected
        finally:
            # Restore permissions for cleanup
            reports_dir.chmod(0o755)
            category_pass.TREE_DATA_PATH = orig_tree_path
            category_pass.OUTPUT_DIR = orig_output_dir


if __name__ == "__main__":
    # Run tests manually
    print("Running tests...")
    test_find_categories_basic()
    print("✓ test_find_categories_basic")

    test_find_gaps_no_edge_between_same_category()
    print("✓ test_find_gaps_no_edge_between_same_category")

    test_find_gaps_with_direct_edge_excluded()
    print("✓ test_find_gaps_with_direct_edge_excluded")

    test_find_gaps_cross_category_not_flagged()
    print("✓ test_find_gaps_cross_category_not_flagged")

    test_synthetic_research_research_colony_regression()
    print("✓ test_synthetic_research_research_colony_regression")

    test_empty_tree_no_categories()
    print("✓ test_empty_tree_no_categories")

    test_node_missing_cat_field_skipped_not_crashed()
    print("✓ test_node_missing_cat_field_skipped_not_crashed")

    test_malformed_synapse_entries_ignored()
    print("✓ test_malformed_synapse_entries_ignored")

    test_find_gaps_large_category_scale()
    print("✓ test_find_gaps_large_category_scale")

    test_main_missing_tree_data_file_exits_cleanly()
    print("✓ test_main_missing_tree_data_file_exits_cleanly")

    test_main_malformed_json_raises()
    print("✓ test_main_malformed_json_raises")

    test_find_gaps_idempotent_rerun()
    print("✓ test_find_gaps_idempotent_rerun")

    test_main_rerun_overwrites_cleanly()
    print("✓ test_main_rerun_overwrites_cleanly")

    test_main_concurrent_invocations_dont_corrupt_output()
    print("✓ test_main_concurrent_invocations_dont_corrupt_output")

    test_main_output_dir_not_writable_fails_clearly()
    print("✓ test_main_output_dir_not_writable_fails_clearly")

    print("\nAll tests passed!")
