"""The dashboard's element preview must match the live dev site (lib/portfolio_parity.py)."""
import json
import shutil
import sys
import urllib.request
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import portfolio_parity as pp  # noqa: E402
import project_catalog  # noqa: E402

PROJECT = project_catalog.portfolio_repo_path()
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


def _has_playwright():
    import importlib.util
    return importlib.util.find_spec("playwright") is not None


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
@pytest.mark.skipif(not shutil.which("node") or not _has_playwright() or not _live(), reason="needs node, playwright and the running dev site")
def test_the_dashboard_preview_of_every_captured_element_matches_the_live_site(element_id):
    if not (PROJECT / "templates" / "elements" / f"{element_id}.json").exists():
        pytest.skip("element not captured")
    result = pp.verify(element_id)
    assert result["ok"], result["differences"]


def test_samples_that_differ_in_size_from_each_other_are_reported(monkeypatch):
    a, b = {"boxWidth": 280, "boxHeight": 290}, {"boxWidth": 280, "boxHeight": 250}
    assert pp.pe.geometry_close(a, a) and not pp.pe.geometry_close(a, b)


# ── a dev site serving some other folder makes every preview look wrong (marvin#585) ──
# Found 2026-10-21: the Mini's WordPress container had been recreated without compose.local.yml, so it served the repo's
# stale wordpress/html (a 1,359-byte card stylesheet from 2026-10-02) while the pipeline kept syncing ~/portfolio-dev.
# project-card parity then failed on a dozen properties with no hint why. Name the cause instead.

def test_dev_site_drift_is_empty_when_the_site_serves_the_synced_files(tmp_path):
    d = tmp_path / "wp-content" / "other-projects"; d.mkdir(parents=True)
    (d / "other-projects.css").write_bytes(b".card{}")
    served = {"http://dev/wp-content/other-projects/other-projects.css": b".card{}"}
    assert pp.dev_site_drift(tmp_path, "http://dev", fetch=served.get) == []


def test_dev_site_drift_names_a_file_the_site_serves_differently_and_how_to_fix_it(tmp_path):
    d = tmp_path / "wp-content" / "other-projects"; d.mkdir(parents=True)
    (d / "other-projects.css").write_bytes(b".card{ new }")
    (d / "project-card.html").write_bytes(b"<div></div>")
    served = {"http://dev/wp-content/other-projects/other-projects.css": b".card{ old }"}      # card html: not served at all
    out = pp.dev_site_drift(tmp_path, "http://dev", fetch=served.get)
    assert len(out) == 2 and all("dev-up.sh" in d for d in out)
    assert any("other-projects.css" in d for d in out) and any("project-card.html" in d for d in out)


def test_dev_site_drift_says_nothing_when_there_is_no_synced_copy_to_compare(tmp_path):
    assert pp.dev_site_drift(tmp_path / "absent", "http://dev", fetch=lambda u: None) == []
