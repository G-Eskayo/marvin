"""Tests for same_category_gap.py. Run via:
    ~/.agents/venv/bin/python -m pytest brain-map/scripts/tests/test_same_category_gap.py -v
"""
from __future__ import annotations
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))

import same_category_gap as scg  # noqa: E402


def _leaf_node(node_id: str, cat: str, desc: str = "") -> dict:
    return {
        "id": node_id,
        "cat": cat,
        "desc": desc,
        "children": [],
        "expandable": False,
        "expanded": True,
    }


def _container_node(node_id: str, cat: str, children: list[dict]) -> dict:
    return {
        "id": node_id,
        "cat": cat,
        "desc": "",
        "children": children,
        "expandable": False,
        "expanded": True,
    }


def _root_node(children: list[dict]) -> dict:
    return {
        "id": "root",
        "cat": "root",
        "desc": "MARVIN",
        "children": children,
        "expandable": False,
        "expanded": True,
    }


def test_find_gaps_detects_leaf_nodes_in_same_category_with_no_synapse():
    research_node_a = _leaf_node("research", "research")
    research_node_b = _leaf_node("research-colony", "research")
    container = _container_node("Research", "research-category", [research_node_a, research_node_b])
    root = _root_node([container])

    tree_data = {"tree": root, "synapses": []}

    gaps = scg.find_gaps(tree_data)

    # Should find the gap between research and research-colony
    pair_ids = {(g["a"], g["b"]) for g in gaps}
    # Either direction is fine (undirected)
    assert ("research", "research-colony") in pair_ids or ("research-colony", "research") in pair_ids


def test_find_gaps_does_not_flag_pair_when_synapse_exists():
    research_node_a = _leaf_node("research", "research")
    research_node_b = _leaf_node("research-colony", "research")
    container = _container_node("Research", "research-category", [research_node_a, research_node_b])
    root = _root_node([container])

    # Add a synapse connecting the two nodes
    synapses = [{"a": "research", "b": "research-colony", "label": "calls", "type": "calls"}]
    tree_data = {"tree": root, "synapses": synapses}

    gaps = scg.find_gaps(tree_data)

    # Should not find any gaps since the pair is connected
    pair_ids = {(g["a"], g["b"]) for g in gaps}
    assert ("research", "research-colony") not in pair_ids
    assert ("research-colony", "research") not in pair_ids


def test_find_gaps_does_not_flag_pair_when_synapse_exists_reverse_direction():
    research_node_a = _leaf_node("research", "research")
    research_node_b = _leaf_node("research-colony", "research")
    container = _container_node("Research", "research-category", [research_node_a, research_node_b])
    root = _root_node([container])

    # Add synapse in reverse direction
    synapses = [{"a": "research-colony", "b": "research", "label": "calls", "type": "calls"}]
    tree_data = {"tree": root, "synapses": synapses}

    gaps = scg.find_gaps(tree_data)

    # Synapses are treated as undirected, so this should still not be flagged
    pair_ids = {(g["a"], g["b"]) for g in gaps}
    assert ("research", "research-colony") not in pair_ids
    assert ("research-colony", "research") not in pair_ids


def test_find_gaps_never_compares_nodes_in_different_categories():
    node_research = _leaf_node("research", "research")
    node_tdd = _leaf_node("tdd", "development")

    container1 = _container_node("Research", "research-category", [node_research])
    container2 = _container_node("Development", "development-category", [node_tdd])
    root = _root_node([container1, container2])

    tree_data = {"tree": root, "synapses": []}

    gaps = scg.find_gaps(tree_data)

    # Should find no gaps since they're in different categories
    pair_ids = {(g["a"], g["b"]) for g in gaps}
    assert ("research", "tdd") not in pair_ids
    assert ("tdd", "research") not in pair_ids


def test_find_gaps_excludes_non_leaf_container_nodes():
    leaf_research = _leaf_node("research", "research")
    leaf_research_colony = _leaf_node("research-colony", "research")
    research_container = _container_node("research-sub", "research", [leaf_research, leaf_research_colony])

    # Create a parent container that has the same category as the leaf nodes
    parent_container = _container_node("Research", "research", [research_container])
    root = _root_node([parent_container])

    tree_data = {"tree": root, "synapses": []}

    gaps = scg.find_gaps(tree_data)

    # Only leaf nodes should be compared. The container node (research-sub) with
    # children should not be included, even though it has cat="research"
    # Should only find gap between leaf_research and leaf_research_colony
    pair_ids = [(g["a"], g["b"]) for g in gaps]

    # Check that container node is not in any gap
    for a, b in pair_ids:
        assert a != "research-sub"
        assert b != "research-sub"

    # Check that we still find the gap between the leaf nodes
    found_leaf_gap = any(
        (a == "research" and b == "research-colony") or
        (a == "research-colony" and b == "research")
        for a, b in pair_ids
    )
    assert found_leaf_gap


def test_find_gaps_handles_empty_tree():
    tree_data = {"tree": {"id": "root", "cat": "root", "desc": "", "children": [], "expandable": False, "expanded": True}, "synapses": []}

    gaps = scg.find_gaps(tree_data)

    # Should return empty list for empty tree
    assert gaps == []


def test_find_gaps_handles_single_leaf_node():
    leaf = _leaf_node("research", "research")
    root = _root_node([leaf])

    tree_data = {"tree": root, "synapses": []}

    gaps = scg.find_gaps(tree_data)

    # Single node means no pairs to compare
    assert gaps == []


def test_find_gaps_returns_gap_dict_with_expected_fields():
    research_node_a = _leaf_node("research", "research")
    research_node_b = _leaf_node("research-colony", "research")
    container = _container_node("Research", "research-category", [research_node_a, research_node_b])
    root = _root_node([container])

    tree_data = {"tree": root, "synapses": []}

    gaps = scg.find_gaps(tree_data)

    assert len(gaps) > 0
    gap = gaps[0]
    assert "a" in gap
    assert "b" in gap
    assert "cat" in gap
    assert isinstance(gap["a"], str)
    assert isinstance(gap["b"], str)
    assert isinstance(gap["cat"], str)


def test_format_gap_produces_readable_output():
    gap = {"a": "research", "b": "research-colony", "cat": "research"}

    output = scg.format_gap(gap)

    assert "research" in output
    assert "research-colony" in output
    assert "research:" in output.lower() or "<->" in output


def test_find_gaps_handles_multiple_categories():
    # Two separate categories with gaps in each
    skills_a = _leaf_node("skill_a", "skills")
    skills_b = _leaf_node("skill_b", "skills")
    agents_a = _leaf_node("agent_a", "agents")
    agents_b = _leaf_node("agent_b", "agents")

    skills_container = _container_node("Skills", "skills-category", [skills_a, skills_b])
    agents_container = _container_node("Agents", "agents-category", [agents_a, agents_b])
    root = _root_node([skills_container, agents_container])

    tree_data = {"tree": root, "synapses": []}

    gaps = scg.find_gaps(tree_data)

    # Should find two gaps: one in skills, one in agents
    pair_ids = {(g["a"], g["b"]) for g in gaps}

    # Check skills gap
    skills_gap = any(
        (a == "skill_a" and b == "skill_b") or (a == "skill_b" and b == "skill_a")
        for a, b in pair_ids
    )
    assert skills_gap

    # Check agents gap
    agents_gap = any(
        (a == "agent_a" and b == "agent_b") or (a == "agent_b" and b == "agent_a")
        for a, b in pair_ids
    )
    assert agents_gap
