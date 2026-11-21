"""marvin#1054: MARVIN Term's pixel source lives in the repo, builds reproducibly, and covers what terminals show.

The characters below are the ones that fell back to other fonts in Claude Code sessions (Gil, 2026-11-16): ASCII
symbols, Claude Code's bullets, spinner and marks, quotes, arrows, keys and accented Latin.
"""
import subprocess
import sys
from pathlib import Path

import pytest

fontTools = pytest.importorskip("fontTools")
from fontTools.ttLib import TTFont  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
SRC = REPO / "design" / "fonts" / "src"
FONTS = REPO / "design" / "fonts"
CELL_PX, UNIT = 12, 40          # mono cell is 12 font pixels; one pixel is 40 units
ASCENT, DESCENT = 800, -240

ASCII = [chr(c) for c in range(33, 127)]
CLAUDE_CODE = list("⏺⎿✓✗✔✘·✢✳✶✻✽…•↑↓←→↳▸▶◀⏸●○◐◯■□▪★☆⚠✎⏎⇧⌘⌥")
TYPOGRAPHY = list("‘’“”–—×÷±≤≥≠€£°")
ACCENTS = list("áàâäãåéèêëíìîïóòôöõúùûüñçýÿÁÀÂÄÃÅÉÈÊËÍÌÎÏÓÒÔÖÕÚÙÛÜÑÇ")
LATIN_1 = list("ß§©¡¿Øæœ")
REQUIRED = ASCII + CLAUDE_CODE + TYPOGRAPHY + ACCENTS + LATIN_1


def _build(tmp_path, *args) -> TTFont:
    r = subprocess.run([sys.executable, str(SRC / "build.py"), *args, "--out", str(tmp_path)], capture_output=True,
                       text=True, timeout=120)
    assert r.returncode == 0, r.stdout + r.stderr
    name = "MarvinTermMono-Beam.ttf" if "mono" in args else "MarvinTerm-Beam.ttf"
    return TTFont(tmp_path / name)


@pytest.fixture(scope="module")
def mono(tmp_path_factory):
    return _build(tmp_path_factory.mktemp("mono"), "mono")


@pytest.fixture(scope="module")
def proportional(tmp_path_factory):
    return _build(tmp_path_factory.mktemp("prop"))


@pytest.mark.parametrize("which", ["mono", "proportional"])
def test_every_character_terminals_show_is_drawn(which, request):
    cmap = request.getfixturevalue(which).getBestCmap()
    missing = [ch for ch in REQUIRED if ord(ch) not in cmap]
    assert not missing, f"not drawn yet: {''.join(missing)}"


def test_every_mono_glyph_fits_its_cell_and_the_line(mono):
    glyf, hmtx = mono["glyf"], mono["hmtx"]
    too_wide, too_tall = [], []
    for code, name in mono.getBestCmap().items():
        g = glyf[name]
        if g.numberOfContours == 0:
            continue
        g.recalcBounds(glyf)
        if g.xMin < 0 or g.xMax > CELL_PX * UNIT or hmtx[name][0] != CELL_PX * UNIT:
            too_wide.append(chr(code))
        if g.yMax > ASCENT or g.yMin < DESCENT:
            too_tall.append(chr(code))
    assert not too_wide, f"wider than the 12-pixel cell: {''.join(too_wide)}"
    assert not too_tall, f"outside the line: {''.join(too_tall)}"


def test_accent_marks_sit_one_clear_row_above_the_letter():
    sys.path.insert(0, str(SRC))
    try:
        import glyphs
    finally:
        sys.path.remove(str(SRC))
    for ch, (_, mark) in glyphs.ACCENTED.items():
        rows = glyphs.G[ch][1]
        gap = rows[len(glyphs.MARKS[mark])]
        assert set(gap) == {"."}, f"{ch}: mark touches the letter"


@pytest.mark.parametrize("which,name", [("mono", "MarvinTermMono-Beam.ttf"), ("proportional", "MarvinTerm-Beam.ttf")])
def test_the_fonts_in_the_repo_are_built_from_this_source(which, name, request):
    built, shipped = request.getfixturevalue(which), TTFont(FONTS / name)
    assert built.getBestCmap() == shipped.getBestCmap(), f"rebuild {name}: python design/fonts/src/build.py"
    for gname in built.getGlyphOrder():
        a, b = built["glyf"][gname], shipped["glyf"][gname]
        assert a.getCoordinates(built["glyf"])[0] == b.getCoordinates(shipped["glyf"])[0], f"{name}: {gname} differs"


def test_wezterm_still_finds_the_mono_family_by_name(mono):
    families = {r.toUnicode() for r in mono["name"].names if r.nameID == 1}
    assert families == {"MARVIN Term Mono"}
    assert mono["post"].isFixedPitch == 1
