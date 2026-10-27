"""Tests for memory_graph.py (marvin#696): follow memory's [[links]] instead of grepping for them.
Temp fixture folders only; the real memory folder is never read.
    ~/.agents/venv/bin/python -m pytest lib/tests/test_memory_graph.py -v
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

LIB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LIB))
sys.path.insert(0, str(LIB / "tests"))

import memory_graph as mg  # noqa: E402
from test_memory_lint import index, note  # noqa: E402


def folder(tmp_path) -> Path:
    """seed-topic -> step-one -> step-two (a chain); a popular hub with five unrelated fans; one note on its own;
    a cycle; a dangling link."""
    d = tmp_path / "memory"
    d.mkdir()
    note(d, "seed-topic", "About solar inverters. Next: [[step-one]]. Also [[does-not-exist]].",
         description="solar inverter sizing notes")
    note(d, "step-one", "Then [[step-two]].", description="wiring checklist")
    note(d, "step-two", "Done.", description="final commissioning")
    note(d, "popular-hub", "Everyone links here.", description="general tips")
    for i in range(5):
        note(d, f"fan-{i}", "[[popular-hub]]", description="unrelated chatter")
    note(d, "island", "No links at all.", description="standalone fact")
    note(d, "cycle-a", "[[cycle-b]]", description="loop one")
    note(d, "cycle-b", "[[cycle-a]]", description="loop two")
    index(d, *[p.stem for p in d.glob("*.md")])
    return d


def test_neighbors_lists_both_directions(tmp_path):
    g = mg.load(folder(tmp_path))
    n = mg.neighbors(g, "step-one")
    assert n["out"] == ["step-two"] and n["in"] == ["seed-topic"]


def test_neighbors_accepts_a_name_case_insensitively(tmp_path):
    d = folder(tmp_path)
    note(d, "file_form", "[[island]]", name="name-form", description="x")
    g = mg.load(d)
    assert mg.neighbors(g, "NAME-FORM")["out"] == ["island"]


def test_unknown_note_is_a_clear_error_not_a_crash(tmp_path):
    g = mg.load(folder(tmp_path))
    try:
        mg.neighbors(g, "nope")
    except mg.UnknownNote as e:
        assert "nope" in str(e)
    else:
        raise AssertionError("expected UnknownNote")


def test_path_follows_links_either_way(tmp_path):
    g = mg.load(folder(tmp_path))
    assert mg.path(g, "step-two", "seed-topic") == ["step-two", "step-one", "seed-topic"]
    assert mg.path(g, "cycle-a", "cycle-b") == ["cycle-a", "cycle-b"]


def test_no_path_to_a_disconnected_note(tmp_path):
    g = mg.load(folder(tmp_path))
    assert mg.path(g, "seed-topic", "island") is None


def test_dangling_links_are_ignored_not_turned_into_nodes(tmp_path):
    g = mg.load(folder(tmp_path))
    assert "does-not-exist" not in g


def test_related_ranks_a_two_hop_neighbour_above_an_unrelated_popular_note(tmp_path):
    # Personalized PageRank seeded from the query's matches: closeness beats raw popularity
    g = mg.load(folder(tmp_path))
    ranked = [r["note"] for r in mg.related(g, "solar inverter", k=20)]
    assert ranked[0] == "seed-topic"
    assert ranked.index("step-two") < ranked.index("popular-hub") if "popular-hub" in ranked else True
    assert "island" not in ranked  # unreachable from the seed: no score


def test_related_with_no_matching_note_returns_nothing(tmp_path):
    g = mg.load(folder(tmp_path))
    assert mg.related(g, "quantum chromodynamics", k=5) == []


def test_related_results_carry_description_and_score(tmp_path):
    g = mg.load(folder(tmp_path))
    top = mg.related(g, "wiring", k=3)[0]
    assert top["note"] == "step-one" and top["description"] == "wiring checklist" and 0 < top["score"] <= 1


def test_cli_end_to_end(tmp_path):
    d = folder(tmp_path)
    run = lambda *a: subprocess.run([sys.executable, str(LIB / "memory_graph.py"), "--dir", str(d), *a],
                                    capture_output=True, text=True)
    r = run("neighbors", "step-one")
    assert r.returncode == 0 and "seed-topic" in r.stdout and "step-two" in r.stdout
    r = run("path", "step-two", "seed-topic")
    assert r.returncode == 0 and "step-two → step-one → seed-topic" in r.stdout
    r = run("related", "solar inverter")
    assert r.returncode == 0 and r.stdout.splitlines()[0].split()[1] == "seed-topic"
    r = run("neighbors", "nope")
    assert r.returncode == 1 and "nope" in r.stderr
