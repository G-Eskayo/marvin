"""Converting a short project page into a long-form page (lib/portfolio_longform.py)."""
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import portfolio_longform as lf  # noqa: E402
import portfolio_migrate as pm  # noqa: E402

SHORT = ('[fusion_builder_container][fusion_text]<div class="section-container"><div class="container"><div class="row"><div class="col-xs-12">'
         '<img src="/h.jpg" class="img-responsive" alt=""><div class="card-container"><div class="text-center"><h1 class="h2">Title</h1></div>'
         '<div><div class="text-center"><h3 class="pink">Sub</h3></div><div>{BODY}<p><strong>Stack:</strong> Python, Flask.</p>'
         '<p class="action-row"><a href="https://github.com/G-Eskayo/p" class="btn btn-default">View on GitHub</a></p></div></div></div></div></div></div></div>'
         '<div id="other-projects-mount"></div>[/fusion_text][/fusion_builder_container]')
BODY = ('Lead words here.<strong>Key Contributions:</strong><ul><li>one</li><li>two</li></ul>'
        '<section><strong>Skills Demonstrated:</strong><ul><li>skill</li></ul></section>'
        '<div class="s12"><strong>Links:</strong><ul><li><a href="/f.pdf">Report</a></li></ul></div>')


def short(body=BODY):
    return SHORT.replace("{BODY}", body)


def test_the_parts_of_a_short_page_are_read_back_out_of_its_markup():
    p = lf.parse_short_page(short())
    assert (p["title"], p["subtitle"], p["hero"], p["stack"]) == ("Title", "Sub", "/h.jpg", "Python, Flask")
    assert p["actions"] == [{"template": "button-github", "data": {"REPO_URL": "https://github.com/G-Eskayo/p"}}]
    assert p["lead_html"] == "<p>Lead words here.</p>"          # loose text becomes a paragraph
    assert [h for h, _ in p["sections"]] == ["Key Contributions", "Skills Demonstrated", "Links"]


def test_headings_are_found_as_strong_with_a_colon_heading_tags_and_blocks_that_start_with_one():
    p = lf.parse_short_page(short('<p>Lead.</p><h3>A real heading</h3><p>under it</p><section><strong>Second:</strong><p>more</p></section>'))
    assert [h for h, _ in p["sections"]] == ["A real heading", "Second"]
    assert "under it" in p["sections"][0][1] and "more" in p["sections"][1][1]


def test_a_body_inside_one_wrapper_div_is_unwrapped():
    p = lf.parse_short_page(short('<div class="s12"><p>Lead.</p><strong>Alpha:</strong><p>a</p><strong>Beta:</strong><p>b</p></div>'))
    assert [h for h, _ in p["sections"]] == ["Alpha", "Beta"] and p["lead_html"] == "<p>Lead.</p>"


def test_too_few_or_repeated_headings_are_left_alone_with_the_reason():
    with pytest.raises(lf.ConversionError, match="not enough structure"):
        lf.build_spec(lf.parse_short_page(short("<p>Lead.</p><strong>Only one:</strong><p>x</p>")))
    with pytest.raises(lf.ConversionError, match="repeat"):
        lf.build_spec(lf.parse_short_page(short("<strong>Notes:</strong><p>a</p><strong>Notes:</strong><p>b</p>")))


def test_a_page_that_is_not_the_project_layout_is_refused():
    with pytest.raises(lf.ConversionError, match="not a project-page layout"):
        lf.parse_short_page("<div>nothing</div>")


def test_the_built_page_keeps_every_word_and_the_frame():
    spec = lf.build_spec(lf.parse_short_page(short()))
    html = pm.render_page(spec, raw=False)["html"]
    assert pm.lost_words(pm.strip_sidebar_wrapper(short()), html) == []
    assert html.count('class="longform-section"') == 3 and "<strong>Stack:</strong> Python, Flask." in html and "View on GitHub" in html


PAGES = [{"ID": 10, "post_name": "ai-projects", "post_parent": 0}, {"ID": 11, "post_name": "p", "post_parent": 10}]


def _runner(content):
    calls = []

    def run(cmd, input=None):
        j = " ".join(map(str, cmd))
        calls.append((j, input))
        if "post list" in j:
            return SimpleNamespace(returncode=0, stdout=json.dumps(PAGES), stderr="")
        if "post get" in j:
            return SimpleNamespace(returncode=0, stdout=content, stderr="")
        return SimpleNamespace(returncode=0, stdout="", stderr="")
    run.calls = calls
    return run


def test_plan_writes_nothing_and_lists_the_sections(tmp_path):
    r = _runner(short())
    out = lf.convert("/ai-projects/p/", plan=True, outbox=tmp_path, runner=r, regenerate=None)
    assert out["ok"] and out["sections"] == ["Key Contributions", "Skills Demonstrated", "Links"]
    assert not any("post update" in c for c, _ in r.calls) and not list(tmp_path.iterdir())


def test_converting_saves_the_short_page_first_and_rollback_restores_it(tmp_path):
    r = _runner(short())
    out = lf.convert("/ai-projects/p/", outbox=tmp_path, runner=r, regenerate=lambda p, rr: ["ok"])
    assert out["ok"]
    saved = json.loads((tmp_path / "p" / "before-longform.json").read_text())
    assert saved["content"] == short()
    update = next(inp for c, inp in r.calls if "post update" in c)
    assert "[fusion_code]" in update                                   # a long-form page is emitted raw
    assert lf.rollback("p", outbox=tmp_path, runner=_runner("")) == {"ok": True, "restored": "/ai-projects/p/"}


def test_a_page_without_structure_is_skipped_not_failed(tmp_path):
    out = lf.convert("/ai-projects/p/", outbox=tmp_path, runner=_runner(short("<p>Just prose.</p>")), regenerate=None)
    assert out["ok"] is False and out["stage"] == "skipped" and "heading" in out["reason"]


# ── authored long-form content on an existing page ──────────────────────────

CONTENT = {"lead_html": "<p>New lead.</p>", "stack": "Swift", "sections": [{"heading": "Why", "body_html": "<p>because</p>"}, {"heading": "How", "body_html": "<p>so</p>"}]}


def test_authoring_keeps_the_frame_and_replaces_the_body(tmp_path):
    r = _runner(short())
    out = lf.author("/ai-projects/p/", CONTENT, outbox=tmp_path, runner=r, regenerate=lambda p, rr: ["ok"])
    assert out["ok"] and out["sections"] == ["Why", "How"]
    update = next(inp for c, inp in r.calls if "post update" in c)
    assert "[fusion_code]" in update
    saved = json.loads((tmp_path / "p" / "before-longform.json").read_text())
    assert saved["content"] == short()                                   # the old page is saved first


def test_authoring_can_override_the_subtitle_hero_stack_and_buttons_and_otherwise_keeps_them():
    import base64, re
    r = _runner(short())
    lf.author("/ai-projects/p/", {**CONTENT, "subtitle": "New sub", "hero": "/new.jpg", "actions": []}, plan=False, outbox=Path("/tmp/lf-test-outbox"), runner=r, regenerate=None)
    update = next(inp for c, inp in r.calls if "post update" in c)
    html = base64.b64decode(re.search(r"\[fusion_code\]([A-Za-z0-9+/=]+)\[/fusion_code\]", update).group(1)).decode()
    assert "New sub" in html and "/new.jpg" in html and "Swift." in html and "action-row" not in html


def test_authoring_requires_a_lead_and_sections_and_leaves_the_page_alone_otherwise(tmp_path):
    r = _runner(short())
    out = lf.author("/ai-projects/p/", {"lead_html": "", "sections": []}, outbox=tmp_path, runner=r, regenerate=None)
    assert out["ok"] is False and out["stage"] == "invalid"
    assert not any("post update" in c for c, _ in r.calls)
