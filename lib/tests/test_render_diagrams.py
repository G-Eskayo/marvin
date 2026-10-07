"""The diagram renderer's output must be usable as an <img> (lib/render_diagrams.py)."""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import project_catalog  # noqa: E402

FIGS = project_catalog.portfolio_repo_path() / "deploy" / "longform" / "figures"


def test_every_committed_figure_svg_is_well_formed_xml_with_an_intrinsic_size_and_no_external_references():
    import xml.etree.ElementTree as ET
    svgs = list(FIGS.rglob("*.svg"))
    assert svgs, "no figures found"
    for f in svgs:
        text = f.read_text()
        root = ET.fromstring(text)                              # a file loaded as an image must be well-formed XML
        # Read the size from the parsed element, not by matching text: a figure written with single quotes (speed.svg)
        # has the same intrinsic size as one with double quotes, and the old pattern only recognised the latter.
        w, h = root.get("width", ""), root.get("height", "")
        assert re.fullmatch(r"\d+", w) and re.fullmatch(r"\d+", h), f"{f.name}: needs a whole-number width and height, got {w!r} x {h!r}"
        assert "https://" not in re.sub(r'xmlns[^=]*="[^"]*"', "", text), f.name


def test_the_size_check_accepts_single_quoted_attributes_and_still_rejects_a_percentage_width():
    """The check must judge the parsed size, not the quote style (the bug that blocked every marvin merge on 2026-10-07)."""
    import xml.etree.ElementTree as ET

    def sized(svg):
        root = ET.fromstring(svg)
        return bool(re.fullmatch(r"\d+", root.get("width", "")) and re.fullmatch(r"\d+", root.get("height", "")))

    assert sized("<svg width='720' height='250' xmlns='http://www.w3.org/2000/svg'/>")
    assert sized('<svg width="720" height="250" xmlns="http://www.w3.org/2000/svg"/>')
    assert not sized('<svg width="100%" height="250" xmlns="http://www.w3.org/2000/svg"/>')
    assert not sized('<svg viewBox="0 0 10 10" xmlns="http://www.w3.org/2000/svg"/>')
