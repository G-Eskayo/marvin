#!/usr/bin/env python3
"""
Tests for generate.py's precomputed layout (#183, ADR 0049): the generator
places every node ahead of time, the same every run, so the browser runs no
layout of its own.
"""
import copy
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import generate  # noqa: E402


def node(id_: str, *children: dict, **extra) -> dict:
    return {"id": id_, "cat": "other", "children": list(children), **extra}


def sample_tree() -> dict:
    """A small tree shaped like the real one: trunks, categories, leaves and a collapsed forest."""
    skills = node("Skills", *[node(f"cat-{c}", *[node(f"skill-{c}-{i}") for i in range(6)]) for c in range(5)])
    forest = node("forest", *[node(f"forest-{i}") for i in range(4)], expandable=True, expanded=False)
    agents = node("Agents", forest, *[node(f"agent-{i}") for i in range(7)])
    return node("MARVIN", skills, agents, *[node(f"trunk-{i}", node(f"leaf-{i}")) for i in range(6)])


def all_ids(tree: dict) -> set:
    out: set = set()
    generate.collect_ids(tree, out)
    return out


def test_same_tree_gives_the_same_layout():
    first = generate.compute_layout(sample_tree())
    second = generate.compute_layout(copy.deepcopy(sample_tree()))
    assert first == second


def test_every_node_has_a_position_including_collapsed_forest_children():
    tree = sample_tree()
    layout = generate.compute_layout(tree)
    assert set(layout) == all_ids(tree)
    assert all(len(p) == 3 and all(math.isfinite(c) for c in p) for p in layout.values())
    assert layout["MARVIN"] == [0, 0, 0]


def test_no_two_nodes_sit_closer_than_the_minimum_spacing_even_in_a_crowded_category():
    crowded = node("crowded", *[node(f"skill-{i}") for i in range(30)])
    tree = node("MARVIN", node("Skills", crowded, node("quiet", node("lone"))), node("Agents", node("a")))
    layout = generate.compute_layout(tree)
    ids = sorted(layout)
    closest = min(math.dist(layout[a], layout[b]) for i, a in enumerate(ids) for b in ids[i + 1:])
    assert closest >= generate.MIN_SPACING - 0.05  # positions are rounded to 0.01


def test_spacing_moves_only_crowded_nodes():
    """An already well-spaced tree comes out exactly where the dendrite layout put it."""
    tree = node("MARVIN", *[node(f"trunk-{i}", node(f"leaf-{i}")) for i in range(4)])
    layout = generate.compute_layout(tree)
    assert layout["trunk-0"] == [round(c, 2) for c in generate._scale((0, 1, 0), generate.SEG[0])]


def test_each_node_carries_its_position_so_a_live_tree_update_arrives_placed():
    tree = sample_tree()
    layout = generate.compute_layout(copy.deepcopy(tree))
    generate.attach_layout(tree)
    seen: dict = {}
    (walk := lambda n: (seen.__setitem__(n["id"], n["pos"]), [walk(c) for c in n["children"]]))(tree)
    assert seen == layout
