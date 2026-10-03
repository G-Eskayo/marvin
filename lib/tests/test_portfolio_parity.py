"""The dashboard's element preview must match the live dev site (lib/portfolio_parity.py)."""
import json
import shutil
import sys
import urllib.request
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import portfolio_parity as pp  # noqa: E402

PROJECT = Path.home() / "Documents" / "Projects" / "portfolio-website-updater"
ELEMENT = {"look": {"title": {"fontFamily": '"Roboto Slab"', "color": "rgb(255, 0, 153)"}}, "geometry": {"photoHeight": 240, "boxHeight": 290, "overlap": 56}}


def test_compare_passes_when_the_preview_matches_the_site():
    assert pp.compare(ELEMENT, {"look": {"title": dict(ELEMENT["look"]["title"])}, "geometry": dict(ELEMENT["geometry"])}) == []


def test_compare_names_each_property_that_has_drifted():
    # the real failure this guards against: the preview fell back to Arial and lost the pink because fonts/CSS were missing
    out = pp.compare(ELEMENT, {"look": {"title": {"fontFamily": "Arial", "color": "rgb(255, 0, 153)"}}, "geometry": {"photoHeight": 240, "boxHeight": 290, "overlap": 36}})
    assert any("title.fontFamily" in d for d in out) and any("geometry" in d for d in out)
    assert not any("color" in d for d in out)


def test_a_missing_part_in_the_preview_is_a_difference():
    assert pp.compare(ELEMENT, {"look": {}, "geometry": ELEMENT["geometry"]})


def _live():
    try:
        urllib.request.urlopen("http://localhost:8080/", timeout=3)
        return True
    except OSError:
        return False


@pytest.mark.skipif(not shutil.which("node") or not _live() or not (PROJECT / "templates/elements/project-card.json").exists(),
                    reason="needs node, the running dev site and a captured element")
def test_the_dashboard_preview_of_the_project_card_matches_the_live_site():
    result = pp.verify("project-card")
    assert result["ok"], result["differences"]
