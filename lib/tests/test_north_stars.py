"""The north stars have one source, docs/north-stars.md (marvin#274, ADR 0059)."""
import re
from pathlib import Path

import pytest

import north_stars

AGENTS = Path(__file__).resolve().parents[2]


def test_load_returns_all_three_north_stars_and_the_principles():
    text = north_stars.load()
    assert "Minimise resources, maximise capability and quality" in text
    assert "MARVIN becomes the OS" in text
    assert "MARVIN raises the human experience" in text
    assert "Compounding leverage" in text


def test_load_drops_the_title_and_the_note_meant_for_editors():
    text = north_stars.load()
    assert not text.startswith("# ")
    assert "The single source for" not in text


def test_missing_file_fails_loudly(tmp_path):
    with pytest.raises(FileNotFoundError):
        north_stars.load(tmp_path / "nope.md")


def test_every_kind_with_the_north_stars_layer_gets_the_file():
    # The daily digest is a Background analyst, so the launcher hands it the north stars (marvin#303).
    import marvin_launcher as ml
    for name, kind in ml.KINDS.items():
        if "north-stars" in kind.layers and name != "interactive":
            assert north_stars.load() in ml.assemble_context(name)


# Phrases that only appear when someone pastes a north star into a prompt.
_COPIED = [r"MINIMI[SZ]E token usage", r"OS of Gil's own phone", r"raises the human experience"]


def test_no_north_star_text_is_hardcoded_in_any_script():
    offenders = []
    for path in list((AGENTS / "lib").rglob("*.py")) + list((AGENTS / "skills").rglob("*.py")):
        if "tests" in path.parts or path.name == "north_stars.py":
            continue
        src = path.read_text(errors="ignore")
        offenders += [f"{path.relative_to(AGENTS)}: {p}" for p in _COPIED if re.search(p, src)]
    assert offenders == []


# marvin#556: delegated design/fix work skipped CONTEXT.md "Triggers over polling" (#554). One preamble, one source.
def test_delegation_preamble_requires_the_reading_and_the_reused_pattern():
    text = north_stars.delegation_preamble()
    assert "docs/north-stars.md" in text
    assert "CONTEXT.md" in text and "docs/adr" in text
    assert "existing pattern" in text and "reused" in text
    assert len(text) < 900  # short: it rides on every delegated prompt


def test_delegation_preamble_names_the_target_repo_when_given():
    assert "G-Eskayo/finance-os" in north_stars.delegation_preamble("G-Eskayo/finance-os")


def test_delegation_preamble_cli_prints_it(capsys):
    north_stars.main(["preamble", "o/r"])
    assert capsys.readouterr().out.strip() == north_stars.delegation_preamble("o/r")


def test_manual_dispatch_and_the_planner_use_the_preamble():
    assert re.search(r'north_stars\.py"? preamble', (AGENTS / "lib" / "dispatch_ticket.sh").read_text())
    assert "delegation_preamble(" in (AGENTS / "lib" / "sandbox_orchestration.py").read_text()
    assert "north_stars.py preamble" in (AGENTS / "docs" / "north-stars.md").read_text()


def test_titles_are_read_from_the_doc_in_order(tmp_path):
    doc = tmp_path / "ns.md"
    doc.write_text("# North stars\n\nnote\n\n## North stars\n\n1. **First one.** *How.* body\n2. **Second, with a comma.** *Why.*\n\n3. **Third** no dot\n")
    assert north_stars.titles(doc) == ["First one", "Second, with a comma", "Third"]


def test_the_real_doc_has_four_titles():
    assert len(north_stars.titles()) == 4
