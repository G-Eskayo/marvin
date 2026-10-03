"""Capturing elements from the live dev site into the element library (lib/portfolio_elements.py)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import portfolio_elements as pe  # noqa: E402

PROJECT = Path.home() / "Documents" / "Projects" / "portfolio-website-updater"

LIVE = ('<div class="col-md-6"><a href="/ai-projects/x/" class="black-image-project-hover"><img decoding="async" src="/u/x.jpg" data-orig-src="/u/x.jpg" alt="" class="img-responsive lazyloaded"></a>'
        '<div class="card-container card-container-lg"><a href="/ai-projects/x/" title="X Title"><h3 class="card-title fusion-responsive-typography-calculated" data-fontsize="26" data-lineheight="35.1px" style="--fontSize: 26; line-height: 1.35;">X Title</h3></a>'
        '<div class="equal"><p>X description.</p><p class="card-also">Also: Cybersecurity</p></div><a href="/ai-projects/x/" class="btn btn-default">Discover</a></div></div>')


def test_generalizing_a_live_card_swaps_content_for_placeholders_and_drops_theme_noise():
    g = pe.generalize_card(LIVE)
    assert g == ('<div class="col-md-6"><a href="{{URL}}" class="black-image-project-hover"><img src="{{THUMBNAIL}}" alt="" class="img-responsive"></a>'
                 '<div class="card-container card-container-lg"><a href="{{URL}}" title="{{TITLE}}"><h3 class="card-title">{{TITLE}}</h3></a>'
                 '<div class="equal"><p>{{DESCRIPTION}}</p>{{ALSO_HTML}}</div><a href="{{URL}}" class="btn btn-default">Discover</a></div></div>')


def test_something_that_is_not_a_card_is_rejected():
    import pytest
    with pytest.raises(ValueError):
        pe.generalize_card("<div class='col-md-6'>hello</div>")


def test_deviations_report_hand_built_markup_look_and_geometry_per_page():
    master = pe.generalize_card(LIVE)
    look, geo = {"title": {"color": "pink"}}, {"overlap": 56}
    good = {"html": LIVE, "look": look, "geometry": geo}
    hand = {"html": LIVE.replace('class="black-image-project-hover">', 'class="black-image-project-hover"><br>'), "look": look, "geometry": {"overlap": 34}}
    out = pe.find_deviations([("/ok/", good), ("/odd/", hand), ("/odd/", {**good, "look": {"title": {"color": "black"}}})], master, look, geo)
    assert [d["page"] for d in out] == ["/odd/"]
    assert any("hand-built" in w or "recognisable" in w for w in out[0]["why"]) and any("geometry" in w for w in out[0]["why"]) and any("look" in w for w in out[0]["why"])


def test_the_captured_card_equals_the_one_template_file_so_library_and_source_cannot_disagree():
    import json
    element = json.loads((PROJECT / "templates" / "elements" / "project-card.json").read_text())
    template = (PROJECT / "deploy/other-projects/project-card.html").read_text().split("-->", 1)[1]
    import re
    assert element["markup"] == re.sub(r">\s+<", "><", template).strip()


def test_the_captured_card_is_one_look_in_one_geometry_everywhere_it_appears():
    import json
    element = json.loads((PROJECT / "templates" / "elements" / "project-card.json").read_text())
    assert element["distinct_looks"] == 1 and element["distinct_geometries"] == 1
    assert element["deviations"] == []
    assert element["usage"]["placements"] >= 20 and element["geometry"] == {"photoHeight": 240, "boxHeight": 290, "overlap": 56}
