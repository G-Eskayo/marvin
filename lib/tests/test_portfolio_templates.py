"""Deterministic template rendering for portfolio pages and components.

Gil 2026-10-02: uniformity across the site, and plug-and-play so MARVIN supplies DATA instead of
regenerating markup (fewer tokens, no drift). Templates are real markup copied from the site; each
declares its fields and the alternatives its slots accept (a GitHub button, a download button...).
Rendering is pure string work: no model, no network.
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import portfolio_templates as pt  # noqa: E402

MANIFEST = {
    "version": 1,
    "templates": [
        {"id": "card", "kind": "component", "file": "components/card.html", "fields": [
            {"name": "TITLE", "type": "text", "required": True},
            {"name": "URL", "type": "url", "required": True},
            {"name": "NOTE", "type": "text", "default": "no note"}]},
        {"id": "body", "kind": "component", "file": "components/body.html", "fields": [
            {"name": "BODY_HTML", "type": "html", "required": True}]},
        {"id": "button-github", "kind": "button", "file": "components/button-github.html", "fields": [
            {"name": "REPO_URL", "type": "url", "required": True, "pattern": "^https://github\\.com/G-Eskayo/[^\\s]+$"},
            {"name": "LABEL", "type": "text", "default": "View on GitHub"}]},
        {"id": "button-download", "kind": "button", "file": "components/button-download.html", "fields": [
            {"name": "FILE_URL", "type": "url", "required": True},
            {"name": "LABEL", "type": "text", "default": "Download"}]},
        {"id": "page", "kind": "page", "file": "page.html", "fields": [
            {"name": "TITLE", "type": "text", "required": True}],
         "slots": {"actions": {"label": "Action buttons", "options": ["button-github", "button-download"]}}},
    ],
}
FILES = {
    "components/card.html": '<div class="card"><h3>{{TITLE}}</h3><a href="{{URL}}">{{NOTE}}</a></div>',
    "components/body.html": "<section>{{BODY_HTML}}</section>",
    "components/button-github.html": '<a href="{{REPO_URL}}" class="btn btn-default">{{LABEL}}</a>',
    "components/button-download.html": '<a href="{{FILE_URL}}" download class="btn btn-default">{{LABEL}}</a>',
    "page.html": "<main><h1>{{TITLE}}</h1><p>{{@actions}}</p></main>",
}


@pytest.fixture
def root(tmp_path):
    for rel, text in FILES.items():
        f = tmp_path / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(text)
    (tmp_path / "templates.json").write_text(json.dumps(MANIFEST))
    return tmp_path


def render(root, tid, field_values=None, options=None):
    return pt.render(tid, field_values or {}, options, root=root)


# ── filling ─────────────────────────────────────────────────────────────────

def test_fills_placeholders_and_applies_defaults_for_optional_fields(root):
    r = render(root, "card", {"TITLE": "Mancala", "URL": "/ai-projects/mancala/"})
    assert r["ok"] and r["html"] == '<div class="card"><h3>Mancala</h3><a href="/ai-projects/mancala/">no note</a></div>'


def test_text_is_html_escaped_but_html_fields_are_inserted_as_given(root):
    r = render(root, "card", {"TITLE": "<script>alert(1)</script> & co", "URL": "/x/"})
    assert "<script>" not in r["html"] and "&lt;script&gt;" in r["html"] and "&amp; co" in r["html"]
    r2 = render(root, "body", {"BODY_HTML": "<p>real <strong>markup</strong></p>"})
    assert r2["html"] == "<section><p>real <strong>markup</strong></p></section>"


def test_missing_required_fields_are_listed_and_the_result_is_not_ok(root):
    r = render(root, "card", {"TITLE": "x"})
    assert not r["ok"] and r["missing"] == ["URL"]
    assert render(root, "card", {"TITLE": "  ", "URL": "/x/"})["missing"] == ["TITLE"]   # blank counts as missing


def test_unfilled_optional_text_without_a_default_renders_empty_not_as_a_raw_placeholder(root):
    r = render(root, "button-download", {"FILE_URL": "/f.pdf"})
    assert "{{" not in r["html"]


def test_unknown_data_keys_are_reported_as_warnings_not_silently_dropped(root):
    r = render(root, "card", {"TITLE": "x", "URL": "/x/", "TYPO": "oops"})
    assert r["ok"] and any("TYPO" in w for w in r["warnings"])


# ── url + pattern validation ────────────────────────────────────────────────

@pytest.mark.parametrize("bad", ["javascript:alert(1)", "data:text/html,x", "  javascript:x", "ftp://x/y", "not a url"])
def test_url_fields_reject_dangerous_or_malformed_values(root, bad):
    r = render(root, "card", {"TITLE": "x", "URL": bad})
    assert not r["ok"] and r["errors"]


@pytest.mark.parametrize("good", ["https://example.com/a", "http://localhost:8080/x", "/relative/path/", "mailto:a@b.co"])
def test_url_fields_accept_http_relative_and_mailto(root, good):
    assert render(root, "card", {"TITLE": "x", "URL": good})["ok"]


def test_a_field_pattern_is_enforced_the_github_button_only_accepts_the_owners_repos(root):
    assert render(root, "button-github", {"REPO_URL": "https://github.com/G-Eskayo/paper-dive"})["ok"]
    bad = render(root, "button-github", {"REPO_URL": "https://github.com/aimacode/aima-python"})
    assert not bad["ok"] and any("REPO_URL" in e for e in bad["errors"])


def test_a_leading_space_in_a_url_is_rejected_not_passed_through(root):
    # the real site has an href=" https://github.com/..." with a leading space (anomaly-detection)
    assert not render(root, "button-github", {"REPO_URL": " https://github.com/G-Eskayo/x"})["ok"]


# ── slots / alternatives ────────────────────────────────────────────────────

def test_a_slot_renders_the_chosen_alternatives_in_order(root):
    r = render(root, "page", {"TITLE": "P"}, {"actions": [
        {"template": "button-github", "data": {"REPO_URL": "https://github.com/G-Eskayo/p"}},
        {"template": "button-download", "data": {"FILE_URL": "/p.pdf", "LABEL": "Download paper"}}]})
    assert r["ok"]
    assert r["html"].index("View on GitHub") < r["html"].index("Download paper")
    assert 'download' in r["html"] and r["used_options"] == ["button-github", "button-download"]


def test_no_options_means_an_empty_slot_never_a_raw_placeholder(root):
    r = render(root, "page", {"TITLE": "P"})
    assert r["ok"] and r["html"] == "<main><h1>P</h1><p></p></main>"


def test_an_alternative_the_slot_does_not_accept_is_an_error(root):
    r = render(root, "page", {"TITLE": "P"}, {"actions": [{"template": "card", "data": {"TITLE": "x", "URL": "/x/"}}]})
    assert not r["ok"] and any("not allowed" in e.lower() for e in r["errors"])


def test_errors_inside_an_alternative_make_the_whole_page_not_ok_and_name_it(root):
    r = render(root, "page", {"TITLE": "P"}, {"actions": [{"template": "button-github", "data": {"REPO_URL": "https://evil.example/x"}}]})
    assert not r["ok"] and any("button-github" in e for e in r["errors"])


# ── safety ──────────────────────────────────────────────────────────────────

def test_an_unknown_template_id_is_an_error_not_a_crash(root):
    r = render(root, "nope")
    assert not r["ok"] and r["errors"]


def test_a_manifest_entry_cannot_point_outside_the_templates_root(root):
    m = json.loads((root / "templates.json").read_text())
    m["templates"].append({"id": "evil", "kind": "page", "file": "../secrets.txt", "fields": []})
    (root / "templates.json").write_text(json.dumps(m))
    (root.parent / "secrets.txt").write_text("TOP SECRET")
    r = render(root, "evil")
    assert not r["ok"] and "TOP SECRET" not in (r["html"] or "")


def test_listing_templates_groups_by_kind_with_their_fields_and_slots(root):
    listing = pt.list_templates(root=root)
    assert {t["id"] for t in listing} == {"card", "body", "button-github", "button-download", "page"}
    page = next(t for t in listing if t["id"] == "page")
    assert page["slots"]["actions"]["options"] == ["button-github", "button-download"]


# ── reference pages (every existing page, for reference) ────────────────────

WRAPPED = ("<!-- hub-sidebar:wrapper -->\n<div>sidebar stuff</div>\n<!-- hub-sidebar:content-start -->\n"
           "[fusion_text]REAL CONTENT[/fusion_text]\n<!-- hub-sidebar:content-end -->\n</div>\n<!-- /hub-sidebar:wrapper -->")


def test_the_hub_sidebar_wrapper_is_stripped_to_the_pages_own_content():
    assert pt.extract_page_content(WRAPPED) == "[fusion_text]REAL CONTENT[/fusion_text]"


def test_an_unwrapped_page_is_returned_unchanged():
    assert pt.extract_page_content("[fusion_text]x[/fusion_text]") == "[fusion_text]x[/fusion_text]"


def test_export_reference_writes_one_file_per_page_and_an_index(tmp_path):
    inv = tmp_path / "inv"; (inv / "raw").mkdir(parents=True)
    (inv / "raw" / "ai-projects--mancala.html").write_text(WRAPPED)
    (inv / "inventory.json").write_text(json.dumps({"pages": [
        {"slug": "ai-projects--mancala", "url": "/ai-projects/mancala/", "title": "Mancala", "type": "project", "raw": "raw/ai-projects--mancala.html"},
        {"slug": "no-raw", "url": "/x/", "title": "X", "type": "page", "raw": None}]}))
    out = tmp_path / "templates"
    index = pt.export_reference(inv, out)
    assert (out / "reference" / "ai-projects--mancala.html").read_text() == "[fusion_text]REAL CONTENT[/fusion_text]"
    assert [e["slug"] for e in index] == ["ai-projects--mancala"]            # pages with no raw markup are skipped, not faked
    assert json.loads((out / "reference" / "index.json").read_text())[0]["url"] == "/ai-projects/mancala/"


# ── plug-and-play: a whole new project in one call ──────────────────────────

def test_plan_new_project_returns_the_page_card_and_manifest_entry_from_one_data_set(tmp_path):
    for rel, text in {
        "project-page.html": "<h1>{{TITLE}}</h1><h3>{{SUBTITLE}}</h3><img src=\"{{HERO_IMAGE_URL}}\">{{BODY_HTML}}<p>{{@actions}}</p>",
        "components/project-card.html": '<a href="{{URL}}">{{TITLE}}</a><img src="{{THUMBNAIL}}"><p>{{DESCRIPTION}}</p>',
        "components/button-github.html": '<a href="{{REPO_URL}}" class="btn btn-default">View on GitHub</a>'}.items():
        f = tmp_path / rel; f.parent.mkdir(parents=True, exist_ok=True); f.write_text(text)
    (tmp_path / "templates.json").write_text(json.dumps({"version": 1, "templates": [
        {"id": "project-page", "kind": "page", "file": "project-page.html", "fields": [
            {"name": n, "type": "html" if n == "BODY_HTML" else "url" if n == "HERO_IMAGE_URL" else "text", "required": True}
            for n in ("TITLE", "SUBTITLE", "HERO_IMAGE_URL", "BODY_HTML")],
         "slots": {"actions": {"options": ["button-github"]}}},
        {"id": "project-card", "kind": "component", "file": "components/project-card.html", "fields": [
            {"name": n, "type": "url" if n in ("URL", "THUMBNAIL") else "text", "required": True} for n in ("URL", "TITLE", "THUMBNAIL", "DESCRIPTION")]},
        {"id": "button-github", "kind": "button", "file": "components/button-github.html", "fields": [
            {"name": "REPO_URL", "type": "url", "required": True, "pattern": "^https://github\\.com/G-Eskayo/\\S+$"}]}]}))
    plan = pt.plan_new_project({
        "title": "Resume Tailor", "slug": "resume-tailor", "category": "AI & Machine Learning", "subtitle": "Tailors resumes",
        "description": "Fits a resume to a job description.", "body_html": "<p>Body.</p>", "hero_image_url": "/u/hero.png",
        "thumbnail": "/u/thumb.png", "actions": [{"template": "button-github", "data": {"REPO_URL": "https://github.com/G-Eskayo/resume-tailor"}}]},
        root=tmp_path)
    assert plan["ok"], plan
    assert plan["manifest_entry"] == {"title": "Resume Tailor", "url": "/ai-projects/resume-tailor/", "category": "AI & Machine Learning",
                                      "secondary_categories": [], "thumbnail": "/u/thumb.png", "description": "Fits a resume to a job description."}
    assert "Resume Tailor" in plan["page_html"] and "View on GitHub" in plan["page_html"]
    assert 'href="/ai-projects/resume-tailor/"' in plan["card_html"]


def test_plan_new_project_reports_what_is_missing_and_never_returns_half_a_plan(tmp_path):
    (tmp_path / "templates.json").write_text(json.dumps({"version": 1, "templates": []}))
    plan = pt.plan_new_project({"title": "X"}, root=tmp_path)
    assert not plan["ok"] and "slug" in " ".join(plan["errors"]) and plan["page_html"] is None


# ── slot wrapper only when something is in it ───────────────────────────────

def _wrapped_root(tmp_path, wrap):
    (tmp_path / "components").mkdir(parents=True, exist_ok=True)
    (tmp_path / "components/b.html").write_text('<a href="{{URL}}">go</a>')
    (tmp_path / "p.html").write_text("<main>{{@actions}}</main>")
    (tmp_path / "templates.json").write_text(json.dumps({"version": 1, "templates": [
        {"id": "b", "kind": "button", "file": "components/b.html", "fields": [{"name": "URL", "type": "url", "required": True}]},
        {"id": "p", "kind": "page", "file": "p.html", "fields": [], "slots": {"actions": {"options": ["b"], "wrap": wrap}}}]}))
    return tmp_path


def test_a_slot_wrapper_appears_only_when_the_slot_has_content(tmp_path):
    root = _wrapped_root(tmp_path, "<p>{content}</p>")
    empty = pt.render("p", {}, None, root)
    full = pt.render("p", {}, {"actions": [{"template": "b", "data": {"URL": "/x/"}}]}, root)
    assert empty["html"] == "<main></main>"                    # no stray empty paragraph for a project with no repo
    assert full["html"] == '<main><p><a href="/x/">go</a></p></main>'


def test_a_page_with_genuinely_empty_content_is_listed_and_flagged_empty_not_faked(tmp_path):
    # e.g. the real /education/ page is only a navigation parent: its content is a blank line.
    inv = tmp_path / "inv"; (inv / "raw").mkdir(parents=True)
    (inv / "raw" / "education.html").write_text("\n")
    (inv / "inventory.json").write_text(json.dumps({"pages": [
        {"slug": "education", "url": "/education/", "title": "Education", "type": "page", "raw": "raw/education.html"}]}))
    index = pt.export_reference(inv, tmp_path / "templates")
    assert index[0]["empty"] is True


def test_a_page_with_content_is_not_flagged_empty(tmp_path):
    inv = tmp_path / "inv"; (inv / "raw").mkdir(parents=True)
    (inv / "raw" / "a.html").write_text("[fusion_text]<p>A real page with a real paragraph of content.</p>[/fusion_text]")
    (inv / "inventory.json").write_text(json.dumps({"pages": [{"slug": "a", "url": "/a/", "title": "A", "type": "page", "raw": "raw/a.html"}]}))
    assert pt.export_reference(inv, tmp_path / "templates")[0]["empty"] is False


# ── a template's leading documentation comment is not page content ──────────

def test_the_leading_doc_comment_of_a_template_is_not_emitted_but_later_comments_are(tmp_path):
    (tmp_path / "t.html").write_text("<!--\n  Authoring notes for humans.\n-->\n<div>{{X}}</div>\n<!-- keep me -->\n<p/>")
    (tmp_path / "templates.json").write_text(json.dumps({"version": 1, "templates": [
        {"id": "t", "kind": "component", "file": "t.html", "fields": [{"name": "X", "type": "text"}]}]}))
    out = pt.render("t", {"X": "hi"}, None, tmp_path)["html"]
    assert "Authoring notes" not in out          # documentation for template authors never lands in a live page
    assert "<div>hi</div>" in out and "<!-- keep me -->" in out


def test_a_template_without_a_leading_comment_is_unchanged(tmp_path):
    (tmp_path / "t.html").write_text("<div>{{X}}</div>")
    (tmp_path / "templates.json").write_text(json.dumps({"version": 1, "templates": [
        {"id": "t", "kind": "component", "file": "t.html", "fields": [{"name": "X", "type": "text"}]}]}))
    assert pt.render("t", {"X": "a"}, None, tmp_path)["html"] == "<div>a</div>"


# ── legacy pages: the useful reference is what visitors get, not a 17-character shortcode ──
# 12 of the 33 pages (the WP-Coder generations) store [wp_wow_coder id="..."] and nothing else; their real
# markup lives in the database. A reference template that is only a shortcode tells nobody anything.

def test_a_page_that_is_only_shortcodes_is_detected():
    assert pt.is_shortcode_only('[wp_wow_coder id="5"]')
    assert pt.is_shortcode_only('\n[fusion_builder_container][wp_wow_coder id="5"][/fusion_builder_container]\n')
    assert pt.is_shortcode_only("")
    assert not pt.is_shortcode_only("[fusion_text]<div class=\"section-container\">Real content here</div>[/fusion_text]")


def test_a_shortcode_only_page_uses_its_rendered_content_as_the_reference_and_says_so(tmp_path):
    inv = tmp_path / "inv"; (inv / "raw").mkdir(parents=True); (inv / "rendered").mkdir()
    (inv / "raw" / "mancala.html").write_text('[wp_wow_coder id="5"]')
    (inv / "rendered" / "mancala.html").write_text('<div class="card-container"><h1>Mancala</h1></div>')
    (inv / "raw" / "modern.html").write_text('[fusion_text]<div class="section-container"><div class="container">real</div></div>[/fusion_text]')
    (inv / "rendered" / "modern.html").write_text("<div>rendered modern</div>")
    (inv / "inventory.json").write_text(json.dumps({"pages": [
        {"slug": "mancala", "url": "/m/", "title": "M", "type": "project", "raw": "raw/mancala.html", "rendered": "rendered/mancala.html"},
        {"slug": "modern", "url": "/n/", "title": "N", "type": "project", "raw": "raw/modern.html", "rendered": "rendered/modern.html"}]}))
    index = {e["slug"]: e for e in pt.export_reference(inv, tmp_path / "templates")}
    assert index["mancala"]["source"] == "rendered" and (tmp_path / "templates/reference/mancala.html").read_text() == '<div class="card-container"><h1>Mancala</h1></div>'
    assert index["modern"]["source"] == "raw" and "section-container" in (tmp_path / "templates/reference/modern.html").read_text()


def test_a_shortcode_only_page_with_no_rendered_capture_is_flagged_not_faked(tmp_path):
    inv = tmp_path / "inv"; (inv / "raw").mkdir(parents=True)
    (inv / "raw" / "x.html").write_text('[wp_wow_coder id="5"]')
    (inv / "inventory.json").write_text(json.dumps({"pages": [{"slug": "x", "url": "/x/", "title": "X", "type": "page", "raw": "raw/x.html"}]}))
    [e] = pt.export_reference(inv, tmp_path / "templates")
    assert e["empty"] is True and e["source"] == "raw"
