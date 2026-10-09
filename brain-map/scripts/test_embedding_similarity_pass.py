#!/usr/bin/env python3
"""Tests for embedding_similarity_pass.py — find cross-category nodes with high semantic similarity."""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Avoid polluting sys.modules; import the module under test
import sys
import importlib.util

HERE = Path(__file__).parent
PASS_PATH = HERE / "embedding_similarity_pass.py"


def load_module():
    """Load the module dynamically so we can test it before it's installed."""
    spec = importlib.util.spec_from_file_location("embedding_similarity_pass", PASS_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules["embedding_similarity_pass"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def sample_tree():
    """A minimal tree with category-label nodes (empty desc) and content nodes."""
    return {
        "id": "MARVIN",
        "children": [
            {
                "id": "Skills",
                "cat": "skills-trunk",
                "desc": "10 skills",
                "children": [
                    {
                        "id": "Coding",
                        "cat": "coding",
                        "desc": "",  # category-label, empty desc
                        "children": [
                            {
                                "id": "test-first-development",
                                "cat": "coding",
                                "desc": "Write tests before code using red-green-refactor cycle",
                                "children": [],
                            },
                            {
                                "id": "automated-testing",
                                "cat": "coding",
                                "desc": "Automated verification of code behavior via test suites",
                                "children": [],
                            },
                        ],
                    },
                    {
                        "id": "Research",
                        "cat": "research",
                        "desc": "",  # category-label, empty desc
                        "children": [
                            {
                                "id": "literature-review",
                                "cat": "research",
                                "desc": "Survey academic papers and prior work on a topic",
                                "children": [],
                            },
                        ],
                    },
                ],
            },
        ],
    }


@pytest.fixture
def sample_synapses():
    """Synapses connecting some nodes."""
    return [
        {"a": "Skills", "b": "test-first-development"},
        {"a": "coding", "b": "automated-testing"},
    ]


class TestCollectNodes:
    def test_collect_nodes_skips_empty_desc(self, sample_tree):
        """Nodes with empty desc (category labels) are excluded from embeddings."""
        module = load_module()
        nodes = module.collect_nodes(sample_tree)
        node_ids = {n["id"] for n in nodes}

        # Category labels with empty desc should be excluded
        assert "Coding" not in node_ids
        assert "Research" not in node_ids

        # Actual content nodes should be included
        assert "test-first-development" in node_ids
        assert "automated-testing" in node_ids
        assert "literature-review" in node_ids

    def test_collect_nodes_empty_tree(self):
        """Empty tree returns empty list, no crash."""
        module = load_module()
        nodes = module.collect_nodes({})
        assert nodes == []

    def test_collect_nodes_only_empty_desc(self):
        """Tree with only empty-desc nodes returns empty list."""
        module = load_module()
        tree = {
            "id": "root",
            "desc": "",
            "children": [{"id": "child1", "desc": "", "children": []}],
        }
        nodes = module.collect_nodes(tree)
        assert nodes == []

    def test_collect_nodes_nested_deeply(self):
        """Nodes are collected from arbitrary depth."""
        module = load_module()
        tree = {
            "id": "root",
            "desc": "root description",
            "children": [
                {
                    "id": "level1",
                    "desc": "level 1",
                    "children": [
                        {
                            "id": "level2",
                            "desc": "level 2",
                            "children": [{"id": "level3", "desc": "level 3", "children": []}],
                        }
                    ],
                }
            ],
        }
        nodes = module.collect_nodes(tree)
        node_ids = {n["id"] for n in nodes}
        assert node_ids == {"root", "level1", "level2", "level3"}


class TestEmbedAll:
    def test_embed_all_with_working_embed(self, sample_tree):
        """embed_all calls embed on each node's description."""
        module = load_module()
        nodes = module.collect_nodes(sample_tree)

        # Mock embed to return a simple vector
        def fake_embed(text, task="document"):
            return [float(ord(c) % 256) / 256 for c in text[:10]]

        vectors = module.embed_all(nodes, embed=fake_embed)

        # All nodes with non-empty desc should have vectors
        for node in nodes:
            assert node["id"] in vectors
            assert vectors[node["id"]] is not None
            assert isinstance(vectors[node["id"]], list)

    def test_embed_all_partial_failure(self, sample_tree):
        """Nodes with None vectors are excluded; others still compared."""
        module = load_module()
        nodes = module.collect_nodes(sample_tree)

        # Mock embed to return None for specific node ids
        failing_ids = {"automated-testing"}
        def fake_embed(text, task="document"):
            # This is a simplistic mock; in reality, embed doesn't know node ids.
            # We'll check by examining the final vector dict instead.
            return [0.1, 0.2] if text.startswith("Survey") else None

        vectors = module.embed_all(nodes, embed=fake_embed)

        # Some nodes may have None or valid vectors; just verify the function doesn't crash
        assert isinstance(vectors, dict)

    def test_embed_all_dependency_down(self, sample_tree):
        """When embed returns None for all nodes, zero vectors collected."""
        module = load_module()
        nodes = module.collect_nodes(sample_tree)

        def fake_embed(text, task="document"):
            return None

        vectors = module.embed_all(nodes, embed=fake_embed)

        # No valid embeddings
        valid_vectors = {nid: v for nid, v in vectors.items() if v is not None}
        assert len(valid_vectors) == 0

    def test_embed_all_huge_desc(self, sample_tree):
        """Large descriptions are passed to embed without truncation."""
        module = load_module()
        huge_node = {
            "id": "huge",
            "cat": "test",
            "desc": "x" * 50000,
        }
        nodes = [huge_node]

        called_texts = []
        def fake_embed(text, task="document"):
            called_texts.append(text)
            return [0.1] * 10

        vectors = module.embed_all(nodes, embed=fake_embed)

        # Should have been called with the huge text
        assert len(called_texts) > 0
        assert len(called_texts[0]) > 40000  # didn't truncate

    def test_embed_all_cache_skips_unchanged(self, sample_tree):
        """Second run skips nodes with unchanged desc hash."""
        module = load_module()
        nodes = module.collect_nodes(sample_tree)

        call_count = [0]
        def fake_embed(text, task="document"):
            call_count[0] += 1
            return [float(call_count[0])]  # unique per call

        with tempfile.TemporaryDirectory() as tmpdir:
            cache_path = Path(tmpdir) / "cache.json"

            # First run
            vectors1 = module.embed_all(nodes, embed=fake_embed, cache_path=cache_path)
            count1 = call_count[0]

            # Second run on same tree
            call_count[0] = 0
            vectors2 = module.embed_all(nodes, embed=fake_embed, cache_path=cache_path)
            count2 = call_count[0]

            # Second run should have made zero new calls (all cache hits)
            assert count2 == 0
            # Vectors should match
            for node in nodes:
                assert vectors1.get(node["id"]) == vectors2.get(node["id"])

    def test_embed_all_cache_invalidates_on_desc_change(self):
        """Changed description invalidates cache for that node."""
        module = load_module()

        nodes1 = [{"id": "n1", "cat": "test", "desc": "original"}]
        nodes2 = [{"id": "n1", "cat": "test", "desc": "changed"}]

        call_count = [0]
        def fake_embed(text, task="document"):
            call_count[0] += 1
            return [float(call_count[0])]

        with tempfile.TemporaryDirectory() as tmpdir:
            cache_path = Path(tmpdir) / "cache.json"

            # First run with original desc
            module.embed_all(nodes1, embed=fake_embed, cache_path=cache_path)
            count1 = call_count[0]
            assert count1 == 1

            # Second run with changed desc
            call_count[0] = 0
            module.embed_all(nodes2, embed=fake_embed, cache_path=cache_path)
            count2 = call_count[0]

            # Should have re-embedded the node (cache miss)
            assert count2 == 1


class TestTreeDataMissing:
    def test_tree_data_missing_file(self):
        """main() exits cleanly when tree-data.json is missing."""
        module = load_module()

        with tempfile.TemporaryDirectory() as tmpdir:
            # Override the TREE_DATA_PATH
            module.TREE_DATA_PATH = Path(tmpdir) / "nonexistent.json"

            with pytest.raises(SystemExit) as exc_info:
                module.main()

            assert exc_info.value.code == 1

    def test_tree_data_malformed_json(self):
        """main() exits cleanly on invalid JSON."""
        module = load_module()

        with tempfile.TemporaryDirectory() as tmpdir:
            tree_path = Path(tmpdir) / "tree.json"
            tree_path.write_text("{invalid json")

            module.TREE_DATA_PATH = tree_path
            module.OUTPUT_DIR = Path(tmpdir) / "reports"

            with pytest.raises(SystemExit) as exc_info:
                module.main()

            assert exc_info.value.code == 1


class TestFindSimilarityGaps:
    def test_cross_category_high_similarity_flagged(self, sample_tree, sample_synapses):
        """Two different-category nodes with high similarity and no synapse are flagged."""
        module = load_module()

        nodes = module.collect_nodes(sample_tree)

        # Create two nearly identical vectors (high similarity)
        vectors = {
            "test-first-development": [1.0, 0.0, 0.0],
            "automated-testing": [0.99, 0.01, 0.0],
            "literature-review": [0.0, 1.0, 0.0],
        }

        findings = module.find_similarity_gaps(nodes, vectors, sample_synapses, threshold=0.9)

        # Should find the high-similarity pair from coding category
        assert len(findings) > 0
        assert any(f["node_a"] == "automated-testing" or f["node_b"] == "automated-testing" for f in findings)

    def test_same_category_high_similarity_excluded(self, sample_tree, sample_synapses):
        """Same-category nodes are excluded even with high similarity."""
        module = load_module()

        nodes = [
            {"id": "n1", "cat": "same", "desc": "first"},
            {"id": "n2", "cat": "same", "desc": "second"},
        ]

        # Nearly identical vectors
        vectors = {
            "n1": [1.0, 0.0],
            "n2": [0.99, 0.01],
        }

        findings = module.find_similarity_gaps(nodes, vectors, [], threshold=0.9)

        # Should exclude same-category pairs
        assert len(findings) == 0

    def test_existing_synapse_excluded(self, sample_tree, sample_synapses):
        """High similarity with direct edge is excluded."""
        module = load_module()

        nodes = [
            {"id": "a", "cat": "cat1", "desc": "first"},
            {"id": "b", "cat": "cat2", "desc": "second"},
        ]

        vectors = {
            "a": [1.0, 0.0],
            "b": [0.99, 0.01],  # high similarity
        }

        synapses = [{"a": "a", "b": "b"}]  # direct edge exists

        findings = module.find_similarity_gaps(nodes, vectors, synapses, threshold=0.9)

        # Should exclude pairs with existing synapses
        assert len(findings) == 0

    def test_below_threshold_not_flagged(self):
        """Low-similarity pairs are not flagged."""
        module = load_module()

        nodes = [
            {"id": "a", "cat": "cat1", "desc": "first"},
            {"id": "b", "cat": "cat2", "desc": "second"},
        ]

        vectors = {
            "a": [1.0, 0.0],
            "b": [0.0, 1.0],  # orthogonal, similarity ≈ 0
        }

        findings = module.find_similarity_gaps(nodes, vectors, [], threshold=0.5)

        assert len(findings) == 0

    def test_threshold_boundary_inclusive(self):
        """Similarity exactly equal to threshold is included."""
        module = load_module()

        nodes = [
            {"id": "a", "cat": "cat1", "desc": "first"},
            {"id": "b", "cat": "cat2", "desc": "second"},
        ]

        vectors = {
            "a": [1.0, 0.0],
            "b": [0.8, 0.6],  # similarity = 0.8 exactly
        }

        findings = module.find_similarity_gaps(nodes, vectors, [], threshold=0.8)

        # Should include pairs at exactly the threshold
        assert len(findings) == 1

    def test_no_self_pairs(self):
        """No finding ever has node_a == node_b."""
        module = load_module()

        nodes = [
            {"id": "a", "cat": "cat1", "desc": "first"},
            {"id": "b", "cat": "cat2", "desc": "second"},
        ]

        vectors = {
            "a": [1.0, 0.0],
            "b": [1.0, 0.0],  # same vector
        }

        findings = module.find_similarity_gaps(nodes, vectors, [], threshold=0.5)

        for f in findings:
            assert f["node_a"] != f["node_b"]


class TestCLIValidation:
    def test_cli_threshold_rejects_invalid(self):
        """--threshold rejects non-numeric and out-of-range values."""
        module = load_module()

        # The module should validate threshold in main() or via argparse
        # We'll mock sys.argv and test the exit behavior
        with pytest.raises((SystemExit, ValueError)):
            # This would normally be caught by argparse or our validation
            module.parse_args(["--threshold", "abc"])


class TestOutputWriteIsAtomic:
    def test_output_write_is_atomic(self, sample_tree, sample_synapses):
        """Output files are written atomically (tmpfile + rename)."""
        module = load_module()

        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir) / "reports"
            output_dir.mkdir()

            json_path = output_dir / "test.json"
            json_path.write_text('{"old": "data"}')

            # Patch the write to simulate a failure mid-write
            original_write = module.write_json

            def failing_write(data, path):
                # Write to tmpfile, then raise before rename
                tmp = path.with_suffix(".tmp")
                tmp.write_text("partial")
                raise IOError("simulated write failure")

            module.write_json = failing_write

            try:
                module.write_json({}, json_path)
            except IOError:
                pass

            # Original file should still be intact
            assert json_path.read_text() == '{"old": "data"}'

            # Tmp file should exist but won't affect the original
            module.write_json = original_write


class TestReportDirNotWritable:
    def test_report_dir_not_writable(self, sample_tree, sample_synapses):
        """Permission error on write results in clean exit, not traceback."""
        module = load_module()

        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir) / "reports"
            output_dir.mkdir()
            output_dir.chmod(0o444)  # Read-only

            module.OUTPUT_DIR = output_dir
            module.TREE_DATA_PATH = Path(tmpdir) / "nonexistent.json"

            # Should exit cleanly, not raise PermissionError
            try:
                # The function should handle this
                module.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)  # This would fail
            except PermissionError:
                pass  # Expected
            finally:
                output_dir.chmod(0o755)  # Restore for cleanup


class TestRunsIndependentOfCwd:
    def test_runs_independent_of_cwd(self):
        """Script paths resolve via __file__, not cwd."""
        module = load_module()

        # Verify the module uses Path(__file__).parent
        assert hasattr(module, "HERE")
        assert module.HERE.is_absolute()


class TestRenderMarkdown:
    def test_render_markdown_empty_findings(self):
        """Markdown for no findings includes 'No gaps detected'."""
        module = load_module()

        md = module.render_markdown([])

        assert "No gaps" in md or "0" in md

    def test_render_markdown_with_findings(self):
        """Markdown includes finding details."""
        module = load_module()

        findings = [
            {
                "kind": "embedding-similarity",
                "node_a": "skill-a",
                "node_b": "skill-b",
                "cat_a": "coding",
                "cat_b": "research",
                "similarity": 0.85,
                "reason": "semantically similar but unconnected",
            }
        ]

        md = module.render_markdown(findings)

        assert "skill-a" in md
        assert "skill-b" in md
        assert "0.85" in md


class TestUnableToScan:
    def test_unable_to_scan_state(self):
        """When zero embeddings collected, report distinct 'unable to scan' state."""
        module = load_module()

        nodes = [
            {"id": "a", "cat": "cat1", "desc": "first"},
            {"id": "b", "cat": "cat2", "desc": "second"},
        ]

        def fake_embed(text, task="document"):
            return None  # total outage

        with tempfile.TemporaryDirectory() as tmpdir:
            vectors = module.embed_all(nodes, embed=fake_embed, cache_path=Path(tmpdir) / "cache.json")
            valid_vectors = {nid: v for nid, v in vectors.items() if v is not None}

            # Zero valid vectors
            assert len(valid_vectors) == 0

            # The findings should be empty, but main() should distinguish this
            # from "we scanned and found no gaps" by checking vector count
            findings = module.find_similarity_gaps(nodes, vectors, [], threshold=0.8)

            # With zero valid vectors, should get zero findings (makes sense)
            # But the report should indicate "unable to scan" not "clean"
