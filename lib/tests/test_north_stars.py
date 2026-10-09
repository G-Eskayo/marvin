"""The north stars have one source, docs/north-stars.md (marvin#274, ADR 0059)."""
import re
from pathlib import Path

import pytest

import north_stars

AGENTS = Path(__file__).resolve().parents[2]


def test_load_returns_all_three_north_stars_and_the_principles():
    text = north_stars.load()
    assert "Minimise tokens, maximise capability and quality" in text
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
