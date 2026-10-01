"""Tests for same_category_gap_scan.py"""
from __future__ import annotations
import json
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))

import pytest

import same_category_gap_scan as sgc  # noqa: E402


@pytest.fixture
def basic_fixture():
    """Basic tree with two nodes in different cat buckets but sharing an intent: tag."""
    manifest_tags = {
        "research": {"intent:research"},
        "research-colony": {"intent:research"},
    }

    tree_data = {
        "tree": {
            "id": "MARVIN",
            "cat": "root",
            "desc": "test root",
            "children": [
                {
                    "id": "research",
                    "cat": "research",
                    "desc": "Research topic investigation",
                    "children": [],
                },
                {
                    "id": "research-colony",
                    "cat": "agents",
                    "desc": "Scheduled research digest runner",
                    "children": [],
                },
            ],
        },
        "synapses": [],
    }

    return tree_data, manifest_tags


@pytest.fixture
def two_nodes_same_cat():
    """Two Memory child nodes sharing the same cat bucket."""
    manifest_tags = {}

    tree_data = {
        "tree": {
            "id": "MARVIN",
            "cat": "root",
            "desc": "test root",
            "children": [
                {
                    "id": "Memory",
                    "cat": "Memory",
                    "desc": "Memory system",
                    "children": [
                        {
                            "id": "ChromaDB",
                            "cat": "Memory",
                            "desc": "ChromaDB collection",
                            "children": [],
                        },
                        {
                            "id": "TaskDispatch",
                            "cat": "Memory",
                            "desc": "Task dispatch",
                            "children": [],
                        },
                    ],
                },
            ],
        },
        "synapses": [],
    }

    return tree_data, manifest_tags


class TestFlatten:
    """Tests for the flatten() function."""

    def test_excludes_root_and_skills_trunk(self, basic_fixture):
        tree_data, _ = basic_fixture
        tree = tree_data["tree"]

        nodes = sgc.flatten(tree)

        # root should not be in nodes
        assert "MARVIN" not in nodes
        # But the children should be
        assert "research" in nodes
        assert "research-colony" in nodes

    def test_collects_all_nested_nodes(self, two_nodes_same_cat):
        tree_data, _ = two_nodes_same_cat
        tree = tree_data["tree"]

        nodes = sgc.flatten(tree)

        # All non-root nodes should be collected
        assert "Memory" in nodes
        assert "ChromaDB" in nodes
        assert "TaskDispatch" in nodes
        # root should not
        assert "MARVIN" not in nodes


class TestCategoriesOf:
    """Tests for the categories_of() function."""

    def test_returns_cat_field(self, basic_fixture):
        _, manifest_tags = basic_fixture

        node = {"id": "research", "cat": "research"}
        cats = sgc.categories_of(node, manifest_tags)

        assert "research" in cats

    def test_includes_manifest_tags(self, basic_fixture):
        _, manifest_tags = basic_fixture

        node = {"id": "research", "cat": "research"}
        cats = sgc.categories_of(node, manifest_tags)

        assert "intent:research" in cats

    def test_union_of_cat_and_tags(self, basic_fixture):
        _, manifest_tags = basic_fixture

        node = {"id": "research", "cat": "research"}
        cats = sgc.categories_of(node, manifest_tags)

        # Should have both the cat field AND the manifest tag
        assert "research" in cats
        assert "intent:research" in cats


class TestExistingEdges:
    """Tests for the existing_edges() function."""

    def test_undirected_edges(self):
        synapses = [
            {"a": "research", "b": "research-colony", "label": "test", "type": "calls"},
        ]

        edges = sgc.existing_edges(synapses)

        # Should have one edge, and it should be undirected
        assert frozenset(["research", "research-colony"]) in edges
        assert len(edges) == 1

    def test_empty_synapses(self):
        edges = sgc.existing_edges([])
        assert edges == set()

    def test_ignores_missing_nodes(self):
        synapses = [
            {"a": "research", "b": None, "label": "test"},
            {"a": None, "b": "colony", "label": "test"},
            {"a": "valid", "b": "pair", "label": "test"},
        ]

        edges = sgc.existing_edges(synapses)

        # Only the valid pair should be in edges
        assert frozenset(["valid", "pair"]) in edges
        assert len(edges) == 1


class TestFindGaps:
    """Tests for the find_gaps() function."""

    def test_flags_same_category_pair_with_no_synapse(self, basic_fixture):
        tree_data, manifest_tags = basic_fixture
        tree = tree_data["tree"]

        nodes = sgc.flatten(tree)
        edges = sgc.existing_edges([])  # No synapses

        gaps = sgc.find_gaps(nodes, manifest_tags, edges)

        # Should flag the research<->research-colony pair (both have intent:research)
        assert len(gaps) == 1
        assert gaps[0]["node_a"] == "research"
        assert gaps[0]["node_b"] == "research-colony"
        assert "intent:research" in gaps[0]["shared_categories"]

    def test_no_longer_flags_once_edge_added(self, basic_fixture):
        tree_data, manifest_tags = basic_fixture
        tree = tree_data["tree"]

        nodes = sgc.flatten(tree)
        edges = sgc.existing_edges(
            [{"a": "research", "b": "research-colony", "label": "test"}]
        )

        gaps = sgc.find_gaps(nodes, manifest_tags, edges)

        # Should not flag since edge exists
        assert len(gaps) == 0

    def test_ignores_pairs_with_no_shared_category(self):
        manifest_tags = {
            "node_a": {"intent:foo"},
            "node_b": {"intent:bar"},
        }

        tree_data = {
            "tree": {
                "id": "root",
                "cat": "root",
                "desc": "",
                "children": [
                    {"id": "node_a", "cat": "cat_a", "desc": "", "children": []},
                    {"id": "node_b", "cat": "cat_b", "desc": "", "children": []},
                ],
            },
            "synapses": [],
        }

        nodes = sgc.flatten(tree_data["tree"])
        edges = sgc.existing_edges([])

        gaps = sgc.find_gaps(nodes, manifest_tags, edges)

        # Should not flag since they share no category
        assert len(gaps) == 0

    def test_does_not_pair_structural_wrapper_nodes(self):
        manifest_tags = {}

        tree_data = {
            "tree": {
                "id": "MARVIN",
                "cat": "root",
                "desc": "",
                "children": [
                    {
                        "id": "Skills",
                        "cat": "skills-trunk",
                        "desc": "",
                        "children": [
                            {"id": "skill_a", "cat": "research", "desc": "", "children": []},
                            {"id": "skill_b", "cat": "research", "desc": "", "children": []},
                        ],
                    },
                ],
            },
            "synapses": [],
        }

        nodes = sgc.flatten(tree_data["tree"])
        edges = sgc.existing_edges([])

        gaps = sgc.find_gaps(nodes, manifest_tags, edges)

        # Should only flag skill_a<->skill_b, not the trunk
        assert len(gaps) == 1
        assert "skill_a" in [gaps[0]["node_a"], gaps[0]["node_b"]]
        assert "skill_b" in [gaps[0]["node_a"], gaps[0]["node_b"]]

    def test_same_cat_bucket_without_manifest_entry(self, two_nodes_same_cat):
        tree_data, manifest_tags = two_nodes_same_cat
        tree = tree_data["tree"]

        nodes = sgc.flatten(tree)
        edges = sgc.existing_edges([])

        gaps = sgc.find_gaps(nodes, manifest_tags, edges)

        # Should flag all pairs within the Memory category
        # (Memory has cat: Memory, ChromaDB has cat: Memory, TaskDispatch has cat: Memory)
        assert len(gaps) == 3
        pairs = {frozenset([gap["node_a"], gap["node_b"]]) for gap in gaps}
        assert frozenset(["Memory", "ChromaDB"]) in pairs
        assert frozenset(["Memory", "TaskDispatch"]) in pairs
        assert frozenset(["ChromaDB", "TaskDispatch"]) in pairs

    def test_pair_sharing_multiple_categories_reported_once(self):
        manifest_tags = {
            "node_a": {"intent:foo", "domain:bar"},
            "node_b": {"intent:foo", "domain:bar"},
        }

        tree_data = {
            "tree": {
                "id": "root",
                "cat": "root",
                "desc": "",
                "children": [
                    {"id": "node_a", "cat": "cat_a", "desc": "", "children": []},
                    {"id": "node_b", "cat": "cat_a", "desc": "", "children": []},
                ],
            },
            "synapses": [],
        }

        nodes = sgc.flatten(tree_data["tree"])
        edges = sgc.existing_edges([])

        gaps = sgc.find_gaps(nodes, manifest_tags, edges)

        # Should have exactly one finding (not duplicated for each shared category)
        assert len(gaps) == 1
        # But it should list all shared categories
        assert "cat_a" in gaps[0]["shared_categories"]
        assert "intent:foo" in gaps[0]["shared_categories"]
        assert "domain:bar" in gaps[0]["shared_categories"]

    def test_ignores_single_node_categories(self):
        manifest_tags = {}

        tree_data = {
            "tree": {
                "id": "root",
                "cat": "root",
                "desc": "",
                "children": [
                    {"id": "node_a", "cat": "unique_cat", "desc": "", "children": []},
                ],
            },
            "synapses": [],
        }

        nodes = sgc.flatten(tree_data["tree"])
        edges = sgc.existing_edges([])

        gaps = sgc.find_gaps(nodes, manifest_tags, edges)

        # Should not flag anything (only one node in the category)
        assert len(gaps) == 0


class TestLoadManifestTags:
    """Tests for the load_manifest_tags() function."""

    def test_returns_empty_dict_for_missing_file(self, tmp_path):
        path = tmp_path / "nonexistent.json"
        tags = sgc.load_manifest_tags(path)
        assert tags == {}

    def test_returns_empty_dict_for_invalid_json(self, tmp_path):
        path = tmp_path / "broken.json"
        path.write_text("{invalid json")
        tags = sgc.load_manifest_tags(path)
        assert tags == {}

    def test_extracts_intent_and_domain_tags(self, tmp_path):
        path = tmp_path / "manifest.json"
        manifest = {
            "index": [
                {
                    "name": "skill_a",
                    "intent": "research",
                    "domain": "analysis",
                },
                {
                    "name": "skill_b",
                    "intent": ["foo", "bar"],
                },
            ]
        }
        path.write_text(json.dumps(manifest))

        tags = sgc.load_manifest_tags(path)

        assert tags["skill_a"] == {"intent:research", "domain:analysis"}
        assert tags["skill_b"] == {"intent:foo", "intent:bar"}

    def test_skips_entries_without_intent_or_domain(self, tmp_path):
        path = tmp_path / "manifest.json"
        manifest = {
            "index": [
                {"name": "skill_a"},
                {"name": "skill_b", "intent": "foo"},
            ]
        }
        path.write_text(json.dumps(manifest))

        tags = sgc.load_manifest_tags(path)

        assert "skill_a" not in tags
        assert "skill_b" in tags


class TestAppendToQueue:
    """Tests for the append_to_queue() function."""

    def test_append_to_queue_flag_reuses_improvement_sweep_block_format(self, tmp_path, monkeypatch):
        """Verify that append_to_queue writes in the standard improvement-queue.md format."""
        queue_file = tmp_path / "improvement-queue.md"
        monkeypatch.setattr(sgc, "QUEUE_FILE", queue_file)

        # Patch Path.home() to return our tmp_path for the queue file location
        def mock_home():
            return tmp_path
        import pathlib
        original_home = pathlib.Path.home
        monkeypatch.setattr(pathlib.Path, "home", mock_home)

        findings = [
            {
                "node_a": "research",
                "node_b": "research-colony",
                "shared_categories": ["intent:research"],
                "desc_a": "Research investigation",
                "desc_b": "Research runner",
            },
            {
                "node_a": "skill_a",
                "node_b": "skill_b",
                "shared_categories": ["cat_x", "intent:foo"],
                "desc_a": "Skill A",
                "desc_b": "Skill B",
            },
        ]

        sgc.append_to_queue(findings)

        # Verify file was created and has expected structure
        assert queue_file.exists()
        content = queue_file.read_text()

        # Should have a header with Brain-map and a timestamp
        assert "Brain-map same-category gaps" in content
        # Should have bullet points for each finding
        assert "`research` ↔ `research-colony`" in content
        assert "intent:research" in content
        assert "`skill_a` ↔ `skill_b`" in content


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
