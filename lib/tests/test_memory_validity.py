"""Tests for marvin#698: a memory fact that changed is marked replaced (superseded_by / invalid_at), never deleted or
left contradicting its replacement. Temp fixture folders only.
    ~/.agents/venv/bin/python -m pytest lib/tests/test_memory_validity.py -v
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

LIB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LIB))
sys.path.insert(0, str(LIB / "tests"))

import memory_graph as mg  # noqa: E402
import memory_lint as ml  # noqa: E402
from test_memory_lint import index, note  # noqa: E402

TODAY = date(2026, 10, 26)


def fm(name, desc, *extra):
    lines = [f"name: {name}", f"description: {desc}", "metadata:", "  type: project"] + [f"  {x}" for x in extra]
    return "---\n" + "\n".join(lines) + "\n---\n"


def folder(tmp_path):
    d = tmp_path / "memory"
    d.mkdir()
    note(d, "host-address-old", "The host is at 10.0.0.5.",
         frontmatter=fm("host-address-old", "host address", "valid_from: 2026-09-01", "superseded_by: host-address"))
    note(d, "host-address", "The host is at 10.0.0.9. Replaces [[host-address-old]].",
         frontmatter=fm("host-address", "host address", "valid_from: 2026-10-20"))
    note(d, "watch-app", "A watch companion is planned.",
         frontmatter=fm("watch-app", "watch companion plan", "invalid_at: 2026-10-01"))
    note(d, "planned-later", "Starts next year.",
         frontmatter=fm("planned-later", "a later plan", "invalid_at: 2027-01-01"))
    index(d, *[p.stem for p in d.glob("*.md")])
    return d


def test_validity_fields_are_read_from_the_metadata_block(tmp_path):
    meta = ml.lint(folder(tmp_path))["meta"]
    assert meta["host-address-old"]["superseded_by"] == "host-address"
    assert meta["host-address-old"]["valid_from"] == "2026-09-01"
    assert meta["watch-app"]["invalid_at"] == "2026-10-01"


def test_current_or_replaced(tmp_path):
    meta = ml.lint(folder(tmp_path))["meta"]
    assert ml.is_current(meta["host-address"], today=TODAY)
    assert not ml.is_current(meta["host-address-old"], today=TODAY)
    assert not ml.is_current(meta["watch-app"], today=TODAY)
    assert ml.is_current(meta["planned-later"], today=TODAY)  # invalid_at still in the future


def test_a_superseded_by_target_that_does_not_exist_is_flagged(tmp_path):
    d = folder(tmp_path)
    note(d, "orphaned-old", "x", frontmatter=fm("orphaned-old", "d", "superseded_by: never-written"))
    index(d, *[p.stem for p in d.glob("*.md")])
    probs = {(x["file"], x["problem"]) for x in ml.lint(d)["frontmatter"]}
    assert ("orphaned-old.md", "superseded_by 'never-written' is not a note") in probs


def test_two_notes_replacing_each_other_is_flagged(tmp_path):
    d = folder(tmp_path)
    note(d, "a", "x", frontmatter=fm("a", "d", "superseded_by: b"))
    note(d, "b", "x", frontmatter=fm("b", "d", "superseded_by: a"))
    index(d, *[p.stem for p in d.glob("*.md")])
    probs = {x["problem"] for x in ml.lint(d)["frontmatter"]}
    assert any("replace each other" in p for p in probs)


def test_bad_dates_are_flagged(tmp_path):
    d = folder(tmp_path)
    note(d, "bad-date", "x", frontmatter=fm("bad-date", "d", "invalid_at: last tuesday"))
    index(d, *[p.stem for p in d.glob("*.md")])
    probs = {(x["file"], x["problem"]) for x in ml.lint(d)["frontmatter"]}
    assert ("bad-date.md", "invalid_at 'last tuesday' is not YYYY-MM-DD") in probs


def test_superseded_by_counts_as_a_link_so_the_replacement_is_not_an_orphan(tmp_path):
    d = folder(tmp_path)
    r = ml.lint(d)
    assert ("host-address-old", "host-address") in [tuple(e) for e in r["edges"]]


def test_related_ranks_a_replaced_note_below_its_replacement_and_marks_it(tmp_path):
    g = mg.load(folder(tmp_path))
    out = mg.related(g, "host address", k=10, today=TODAY)
    order = [r["note"] for r in out]
    assert order.index("host-address") < order.index("host-address-old")
    old = next(r for r in out if r["note"] == "host-address-old")
    assert old["replaced_by"] == "host-address" and old["current"] is False
    assert next(r for r in out if r["note"] == "host-address")["current"] is True
