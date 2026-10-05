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


def test_framing_puts_each_kind_of_element_in_the_context_it_has_on_the_site():
    assert pp.framing_for("project-card")["context"] == "grid"
    assert pp.framing_for("site-header")["context"] == "chrome" and pp.framing_for("hub-sidebar")["width"] == 260
    assert pp.framing_for("other-projects")["context"] == "page"       # it sits inside the page content, not around it
    assert pp.framing_for("button-github")["context"] == "page"


ELEMENT_IDS = ["project-card", "button-github", "site-header", "page-title-bar", "hub-sidebar", "other-projects", "site-footer"]


@pytest.mark.parametrize("element_id", ELEMENT_IDS)
@pytest.mark.skipif(not shutil.which("node") or not _live(), reason="needs node and the running dev site")
def test_the_dashboard_preview_of_every_captured_element_matches_the_live_site(element_id):
    if not (PROJECT / "templates" / "elements" / f"{element_id}.json").exists():
        pytest.skip("element not captured")
    result = pp.verify(element_id)
    assert result["ok"], result["differences"]
