"""Tests for memory_lint.py (marvin#695): the memory folder's [[links]], index and frontmatter are checked, never edited.
All fixtures are temp folders; the real memory folder is never read.
    ~/.agents/venv/bin/python -m pytest lib/tests/test_memory_lint.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path

LIB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LIB))

import memory_lint as ml  # noqa: E402


def note(d: Path, stem: str, body: str = "", *, name: str | None = None, type_: str = "project",
         description: str = "a note", frontmatter: str | None = None) -> Path:
    fm = frontmatter if frontmatter is not None else (
        f"---\nname: {name or stem}\ndescription: {description}\nmetadata:\n  type: {type_}\n---\n")
    p = d / f"{stem}.md"
    p.write_text(fm + "\n" + body + "\n")
    return p


def index(d: Path, *stems: str, extra: str = "") -> None:
    lines = ["# Memory Index", ""] + [f"- [{s}]({s}.md) — hook" for s in stems]
    (d / "MEMORY.md").write_text("\n".join(lines) + "\n" + extra)


def healthy(tmp_path) -> Path:
    d = tmp_path / "memory"
    d.mkdir()
    note(d, "alpha", "Links to [[beta]].")
    note(d, "beta", "Back to [[alpha]].")
    index(d, "alpha", "beta")
    return d


# ── links ─────────────────────────────────────────────────────────────────

def test_a_sound_folder_is_clean_and_green(tmp_path):
    d = healthy(tmp_path)
    r = ml.lint(d)
    assert r["notes"] == 2 and r["links"] == 2
    assert not (r["dangling"] or r["orphans"] or r["conflicts"] or r["frontmatter"] or r["unindexed"] or r["index_missing"])
    assert ml.check(d)["severity"] == "green"


def test_dangling_link_is_reported_with_the_closest_real_name(tmp_path):
    d = healthy(tmp_path)
    note(d, "gamma", "See [[alpah]] and [[nothing-like-it-at-all]].")
    index(d, "alpha", "beta", "gamma")
    r = ml.lint(d)
    by_target = {x["target"]: x for x in r["dangling"]}
    assert by_target["alpah"]["suggestion"] == "alpha" and by_target["alpah"]["file"] == "gamma.md"
    assert by_target["nothing-like-it-at-all"]["suggestion"] is None
    assert ml.check(d)["severity"] == "yellow"


def test_no_suggestion_just_because_names_share_a_long_prefix(tmp_path):
    # found in the evidence sandbox: [[project-demo-deploy]] was "suggested" as project-demo-app, a different note
    d = healthy(tmp_path)
    note(d, "project-demo-app", "x")
    note(d, "feedback-catch-mistakes", "x")
    note(d, "gamma", "[[project-demo-deploy]] [[catch-mistakes]] [[project-demo-ap]]")
    index(d, "alpha", "beta", "project-demo-app", "feedback-catch-mistakes", "gamma")
    by_target = {x["target"]: x["suggestion"] for x in ml.lint(d)["dangling"]}
    assert by_target["project-demo-deploy"] is None
    assert by_target["catch-mistakes"] == "feedback-catch-mistakes"  # the type prefix was left off
    assert by_target["project-demo-ap"] == "project-demo-app"        # a typo


def test_links_resolve_by_name_or_by_filename(tmp_path):
    # four real notes have a `name:` that differs from their file stem; links use either
    d = healthy(tmp_path)
    note(d, "file_stem_form", "x", name="name-form")
    note(d, "gamma", "[[name-form]] and [[file_stem_form]] and [[Alpha]]")
    index(d, "alpha", "beta", "file_stem_form", "gamma")
    assert ml.lint(d)["dangling"] == []


def test_alias_and_heading_links_resolve_to_the_note(tmp_path):
    d = healthy(tmp_path)
    note(d, "gamma", "[[alpha|the first one]] and [[beta#Why]]")
    index(d, "alpha", "beta", "gamma")
    assert ml.lint(d)["dangling"] == []


def test_a_link_broken_across_a_line_is_flagged_as_split_not_just_missing(tmp_path):
    d = healthy(tmp_path)
    note(d, "gamma", "see [[alpha\n]] and [[be\nta]]")
    index(d, "alpha", "beta", "gamma")
    r = ml.lint(d)
    split = [x for x in r["dangling"] if x["split"]]
    assert {x["target"] for x in split} == {"beta"}  # joins to a real note: flagged so the line gets fixed
    assert all(x["suggestion"] == "beta" for x in split)


def test_links_inside_code_are_not_links(tmp_path):
    d = healthy(tmp_path)
    note(d, "gamma", "```\nif [[ -f x ]]; then echo; fi\n```\nand `[[not-a-link]]` inline")
    index(d, "alpha", "beta", "gamma")
    assert ml.lint(d)["dangling"] == []


def test_orphans_are_counted_but_do_not_change_severity(tmp_path):
    d = healthy(tmp_path)
    note(d, "lonely", "links out to [[alpha]] but nothing links here")
    index(d, "alpha", "beta", "lonely")
    r = ml.lint(d)
    assert r["orphans"] == ["lonely"]
    c = ml.check(d)
    assert c["severity"] == "green" and "1 with no inbound link" in c["detail"]


def test_a_self_link_does_not_rescue_an_orphan(tmp_path):
    d = healthy(tmp_path)
    note(d, "lonely", "see [[lonely]]")
    index(d, "alpha", "beta", "lonely")
    assert ml.lint(d)["orphans"] == ["lonely"]


# ── conflict markers ─────────────────────────────────────────────────────

CONFLICT = "<<<<<<< Updated upstream\nold line\n=======\nnew line\n>>>>>>> Stashed changes\n"


def test_conflict_markers_anywhere_are_red_with_file_and_line(tmp_path):
    d = healthy(tmp_path)
    (d / "MEMORY.md").write_text((d / "MEMORY.md").read_text() + CONFLICT)
    note(d, "beta", "Back to [[alpha]].\n" + CONFLICT)
    r = ml.lint(d)
    assert {(c["file"]) for c in r["conflicts"]} == {"MEMORY.md", "beta.md"}
    assert all(c["line"] > 0 for c in r["conflicts"])
    c = ml.check(d)
    assert c["severity"] == "red" and "conflict" in c["detail"]


def test_a_markdown_rule_of_equals_signs_alone_is_not_a_conflict(tmp_path):
    d = healthy(tmp_path)
    note(d, "beta", "Back to [[alpha]].\n\nTitle\n=======\n")
    assert ml.lint(d)["conflicts"] == []


# ── frontmatter ──────────────────────────────────────────────────────────

def test_frontmatter_problems_are_named(tmp_path):
    d = healthy(tmp_path)
    note(d, "no_fm", "[[alpha]]", frontmatter="")
    note(d, "bad_type", "[[alpha]]", type_="opinion")
    note(d, "no_desc", "[[alpha]]", frontmatter="---\nname: no_desc\nmetadata:\n  type: user\n---\n")
    index(d, "alpha", "beta", "no_fm", "bad_type", "no_desc")
    probs = {(x["file"], x["problem"]) for x in ml.lint(d)["frontmatter"]}
    assert ("no_fm.md", "no frontmatter") in probs
    assert ("bad_type.md", "type 'opinion' is not user/feedback/project/reference") in probs
    assert ("no_desc.md", "missing description") in probs


def test_optional_fields_like_node_type_are_not_required(tmp_path):
    d = healthy(tmp_path)
    note(d, "gamma", "[[alpha]]", frontmatter="---\nname: gamma\ndescription: d\nmetadata:\n  type: user\n  node_type: memory\n  modified: x\n---\n")
    index(d, "alpha", "beta", "gamma")
    assert ml.lint(d)["frontmatter"] == []


# ── the index ────────────────────────────────────────────────────────────

def test_index_drift_both_ways(tmp_path):
    d = healthy(tmp_path)
    note(d, "unlisted", "[[alpha]]")
    index(d, "alpha", "beta", "gone")
    r = ml.lint(d)
    assert r["unindexed"] == ["unlisted"]
    assert r["index_missing"] == ["gone.md"]
    assert ml.check(d)["severity"] == "yellow"


def test_index_links_do_not_count_as_inbound_links(tmp_path):
    # MEMORY.md lists everything; counting it would hide every orphan
    d = healthy(tmp_path)
    note(d, "listed_only")
    index(d, "alpha", "beta", "listed_only")
    assert ml.lint(d)["orphans"] == ["listed_only"]


# ── robustness ───────────────────────────────────────────────────────────

def test_missing_folder_is_reported_not_crashed(tmp_path):
    c = ml.check(tmp_path / "nope")
    assert c["severity"] == "yellow" and "no memory folder" in c["detail"]


def test_lint_never_writes(tmp_path):
    d = healthy(tmp_path)
    note(d, "gamma", "[[alpah]]\n" + CONFLICT)
    before = {p.name: p.read_bytes() for p in d.iterdir()}
    ml.lint(d)
    ml.lint(d)  # run twice
    assert {p.name: p.read_bytes() for p in d.iterdir()} == before


def test_unreadable_bytes_do_not_crash(tmp_path):
    d = healthy(tmp_path)
    (d / "binary.md").write_bytes(b"\xff\xfe---\x00[[alpha]]")
    index(d, "alpha", "beta", "binary")
    r = ml.lint(d)
    assert any(x["file"] == "binary.md" for x in r["frontmatter"])


def test_check_shape_for_the_health_tab(tmp_path):
    c = ml.check(healthy(tmp_path))
    assert c["id"] == "memory:lint" and c["label"] == "Memory links and index are sound"
    assert isinstance(c["value"], int)


def test_quoted_descriptions_lose_their_quotes(tmp_path):
    d = healthy(tmp_path)
    note(d, "gamma", "[[alpha]]", frontmatter='---\nname: gamma\ndescription: "a quoted one"\nmetadata:\n  type: user\n---\n')
    assert ml.lint(d)["meta"]["gamma"]["description"] == "a quoted one"
