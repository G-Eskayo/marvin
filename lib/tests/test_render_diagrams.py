"""The diagram renderer's output must be usable as an <img> (lib/render_diagrams.py)."""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

FIGS = Path.home() / "Documents" / "Projects" / "portfolio-website-updater" / "deploy" / "longform" / "figures"


def test_every_committed_figure_svg_is_well_formed_xml_with_an_intrinsic_size_and_no_external_references():
    import xml.etree.ElementTree as ET
    svgs = list(FIGS.rglob("*.svg"))
    assert svgs, "no figures found"
    for f in svgs:
        text = f.read_text()
        ET.fromstring(text)                                     # a file loaded as an image must be well-formed XML
        root = re.match(r"<svg\b[^>]*>", text).group(0)
        assert 'width="100%"' not in root and re.search(r'width="\d+"', root) and re.search(r'height="\d+"', root), f.name
        assert "https://" not in re.sub(r'xmlns[^=]*="[^"]*"', "", text), f.name
