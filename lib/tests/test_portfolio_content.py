"""Content templates and content checks for portfolio pages (lib/portfolio_content.py, ADR 0051)."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import portfolio_content as pc  # noqa: E402

TEMPLATE = {"id": "skill-tool", "sections": [
    {"role": "evidence", "required": True, "evidence": ["real-output"]},
    {"role": "setup", "required": True, "evidence": ["diagram"]},
    {"role": "extras", "required": False, "evidence": []},
    {"role": "marvin", "required": True, "evidence": ["diagram", "link"], "only_if": "built_with_marvin"}]}
FIG = '<figure class="longform-figure"><img src="/wp-content/longform/figures/x/{f}" alt="{a}"></figure>'


def page(sections, **extra):
    return {"content_type": "skill-tool", "lead_html": "<p>Lead.</p>", "sections": sections, **extra}


# ── coverage against the template ──

def test_a_page_with_every_required_role_and_its_evidence_is_covered():
    p = page([{"role": "evidence", "body_html": FIG.format(f="out.png", a="output")},
              {"role": "setup", "body_html": FIG.format(f="setup.svg", a="setup")}])
    assert pc.coverage(p, TEMPLATE) == {"type": "skill-tool", "missing_roles": [], "missing_evidence": []}


def test_missing_required_roles_and_evidence_are_listed_but_optional_ones_are_not():
    p = page([{"role": "evidence", "body_html": "<p>No picture here.</p>"}])
    cov = pc.coverage(p, TEMPLATE)
    assert cov["missing_roles"] == ["setup"]                       # extras is optional
    assert cov["missing_evidence"] == [{"role": "evidence", "evidence": "real-output"}]


def test_a_conditional_section_is_required_only_when_its_condition_holds():
    sections = [{"role": "evidence", "body_html": FIG.format(f="o.png", a="o")}, {"role": "setup", "body_html": FIG.format(f="s.svg", a="s")}]
    assert pc.coverage(page(sections), TEMPLATE)["missing_roles"] == []
    assert pc.coverage(page(sections, built_with_marvin=True), TEMPLATE)["missing_roles"] == ["marvin"]


def test_evidence_kinds_are_recognised_from_the_markup():
    html = (FIG.format(f="d.svg", a="d") + FIG.format(f="s.png", a="s") + '<a href="/ai-projects/marvin/">MARVIN</a>'
            + "<p>2,102 tests and 30 pull requests.</p>")
    kinds = pc.evidence_in(html)
    assert {"diagram", "chart", "screenshot", "real-output", "link", "numbers"} <= kinds
    assert pc.evidence_in("<p>Words only, one number: 3.</p>") == set()


# ── copy that reads as AI-written ──

def test_ai_writing_phrases_and_em_dashes_are_flagged_with_the_phrase():
    found = pc.check_copy("<p>This project aims to revolutionize gaming — a seamless journey.</p>")
    rules = sorted({f["rule"] for f in found})
    assert rules == ["copy-ai-phrase", "copy-em-dash"]
    assert any("revolutionize" in f["detail"] for f in found) and any("seamless" in f["detail"] for f in found)


def test_plain_confident_copy_passes():
    assert pc.check_copy("<p>I built it for my mom. It works offline and costs nothing.</p>") == []


def test_phrases_inside_attributes_and_code_are_ignored():
    assert pc.check_copy('<p><img alt="a seamless pipeline" src="x.png"> <code>leverage()</code></p>') == []


# ── media on long-form pages ──

def test_images_without_alt_text_are_flagged():
    found = pc.check_media_markup('<img src="a.png" alt="A chart"><img src="b.png"><img src="c.png" alt="  ">')
    assert [f["rule"] for f in found] == ["image-no-alt", "image-no-alt"] and "b.png" in found[0]["detail"]


def test_a_long_form_page_with_no_figure_is_flagged():
    assert [f["rule"] for f in pc.check_has_figure(page([{"role": "evidence", "body_html": "<p>x</p>"}]))] == ["no-evidence-figure"]
    assert pc.check_has_figure(page([{"role": "evidence", "body_html": FIG.format(f="a.png", a="a")}])) == []


# ── MARVIN links both ways ──

def test_marvin_built_pages_must_link_to_marvin_and_marvin_must_link_back():
    urls = {"marvin": "/ai-projects/marvin/", "tool": "/ai-projects/tool/", "other": "/x/other/"}
    contents = {
        "marvin": {"content_type": "system", "sections": [{"role": "built-with", "body_html": '<a href="/ai-projects/other/">no</a>'}]},
        "tool": page([{"role": "marvin", "body_html": "<p>No link.</p>"}], built_with_marvin=True),
        "other": page([{"role": "evidence", "body_html": "<p>Not built with MARVIN.</p>"}]),
    }
    found = pc.check_marvin_links(contents, urls)
    assert sorted((f["page"], f["rule"]) for f in found) == [("marvin", "marvin-missing-backlink"), ("tool", "marvin-link-missing")]


# ── reading the real files ──

def test_evaluate_reads_templates_and_content_files_from_a_project(tmp_path):
    (tmp_path / "templates" / "content").mkdir(parents=True)
    (tmp_path / "content" / "longform").mkdir(parents=True)
    (tmp_path / "deploy" / "other-projects").mkdir(parents=True)
    (tmp_path / "templates" / "content" / "skill-tool.json").write_text(json.dumps(TEMPLATE))
    (tmp_path / "content" / "longform" / "tool.json").write_text(json.dumps(page([{"role": "evidence", "body_html": "<p>A seamless tool.</p>"}])))
    (tmp_path / "content" / "longform" / "legacy.json").write_text(json.dumps({"lead_html": "<p>x</p>", "sections": []}))
    (tmp_path / "deploy" / "other-projects" / "manifest.json").write_text(json.dumps([{"title": "Tool", "url": "/ai-projects/tool/"}]))
    report = pc.evaluate(tmp_path)
    tool = report["pages"]["tool"]
    assert tool["template"] == "skill-tool" and tool["coverage"]["missing_roles"] == ["setup"]
    assert {f["rule"] for f in tool["findings"]} >= {"copy-ai-phrase", "no-evidence-figure"}
    assert report["pages"]["legacy"]["template"] is None            # not on a template yet: reported, not failed
    assert report["templates"] == ["skill-tool"]


def test_an_evidence_requirement_can_accept_alternatives():
    # Paper Dive's real output is a chart drawn from real data, not a screenshot.
    tpl = {"id": "t", "sections": [{"role": "evidence", "required": True, "evidence": ["real-output|chart"]}]}
    chart_only = page([{"role": "evidence", "body_html": FIG.format(f="map.svg", a="map")}])
    words_only = page([{"role": "evidence", "body_html": "<p>x</p>"}])
    assert pc.coverage(chart_only, tpl)["missing_evidence"] == []
    assert pc.coverage(words_only, tpl)["missing_evidence"] == [{"role": "evidence", "evidence": "real-output|chart"}]


def test_the_evaluation_can_leave_copy_to_its_own_rendered_page_check(tmp_path):
    (tmp_path / "templates" / "content").mkdir(parents=True)
    (tmp_path / "content" / "longform").mkdir(parents=True)
    (tmp_path / "templates" / "content" / "skill-tool.json").write_text(json.dumps(TEMPLATE))
    (tmp_path / "content" / "longform" / "tool.json").write_text(json.dumps(page([{"role": "evidence", "body_html": "<p>A seamless tool.</p>"}])))
    rules = {r["rule"] for r in pc.findings_for_evaluation(tmp_path, include_copy=False)}
    assert "copy-ai-phrase" not in rules and "template-missing-section" in rules


def test_manifest_pages_without_a_content_file_are_listed_as_not_on_a_template(tmp_path):
    (tmp_path / "templates" / "content").mkdir(parents=True)
    (tmp_path / "content" / "longform").mkdir(parents=True)
    (tmp_path / "deploy" / "other-projects").mkdir(parents=True)
    (tmp_path / "deploy" / "other-projects" / "manifest.json").write_text(json.dumps([{"title": "Old Page", "url": "/a/old-page/"}]))
    report = pc.evaluate(tmp_path)
    assert report["pages"]["old-page"] == {"template": None, "url": "/a/old-page/", "title": "Old Page", "coverage": None, "findings": []}
