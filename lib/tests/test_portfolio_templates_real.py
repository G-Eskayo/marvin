"""Lint the REAL templates in the portfolio repo (templates/ + templates.json).

Templates rot silently: a placeholder nobody declares renders as an empty hole, a required field the
template never uses does nothing, a file gets renamed and the manifest still points at it. This
checks the real files, so the plug-and-play promise (supply data, get uniform markup) stays true.
Skipped where the portfolio repo is not on this machine.
"""
from __future__ import annotations
import json
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import portfolio_templates as pt  # noqa: E402

ROOT = pt.ROOT
pytestmark = pytest.mark.skipif(not (ROOT / "templates.json").exists(), reason="portfolio repo templates not on this machine")

SAMPLE = {"URL": "/ai-projects/mancala/", "TITLE": "Mancala", "THUMBNAIL": "/u/t.png", "DESCRIPTION": "A game.", "SUBTITLE": "Sub",
          "HERO_IMAGE_URL": "/u/h.png", "BODY_HTML": "<p>Body.</p>", "STACK_CSV": "Python", "CATEGORY": "AI & Machine Learning",
          "CARDS_HTML": "<div>cards</div>", "HEADING": "Other Projects", "LABEL": "Go", "REPO_URL": "https://github.com/G-Eskayo/mancala",
          "FILE_URL": "/wp-content/uploads/paper.pdf", "SECTIONS_HTML": "<div>sections</div>"}


def entries():
    return json.loads((ROOT / "templates.json").read_text())["templates"]


@pytest.mark.parametrize("e", entries(), ids=lambda e: e["id"])
def test_the_template_file_exists_and_every_placeholder_in_it_is_declared(e):
    text = (ROOT / e["file"]).read_text()
    declared = {f["name"] for f in e.get("fields", [])}
    used = set(re.findall(r"\{\{([A-Z0-9_]+)\}\}", text))
    assert used <= declared, f"{e['id']}: undeclared placeholders {sorted(used - declared)}"
    slots_used = set(re.findall(r"\{\{@([a-z0-9_-]+)\}\}", text))
    assert slots_used <= set(e.get("slots", {})), f"{e['id']}: undeclared slots {sorted(slots_used)}"


@pytest.mark.parametrize("e", entries(), ids=lambda e: e["id"])
def test_every_required_field_is_actually_used_by_the_template(e):
    used = set(re.findall(r"\{\{([A-Z0-9_]+)\}\}", (ROOT / e["file"]).read_text()))
    unused = [f["name"] for f in e.get("fields", []) if f.get("required") and f["name"] not in used]
    assert not unused, f"{e['id']}: required but never used: {unused}"


@pytest.mark.parametrize("e", entries(), ids=lambda e: e["id"])
def test_the_template_renders_cleanly_with_sample_data(e):
    r = pt.render(e["id"], {f["name"]: SAMPLE[f["name"]] for f in e.get("fields", []) if f["name"] in SAMPLE})
    assert r["ok"], r
    assert "{{" not in r["html"], "an unfilled placeholder leaked into the output"


def test_every_slot_alternative_names_a_real_template():
    ids = {e["id"] for e in entries()}
    for e in entries():
        for slot, spec in e.get("slots", {}).items():
            assert set(spec["options"]) <= ids, f"{e['id']}.{slot} offers unknown alternatives"


def test_the_project_page_takes_a_github_button_a_download_button_or_neither():
    base = {"TITLE": "T", "SUBTITLE": "S", "HERO_IMAGE_URL": "/h.png", "BODY_HTML": "<p>b</p>", "STACK_CSV": "Python"}
    none = pt.render("project-page", base)
    both = pt.render("project-page", base, {"actions": [
        {"template": "button-github", "data": {"REPO_URL": "https://github.com/G-Eskayo/x"}},
        {"template": "button-download", "data": {"FILE_URL": "/p.pdf", "LABEL": "Download paper"}}]})
    assert none["ok"] and both["ok"]
    assert "btn btn-default" not in none["html"] and "<p></p>" not in none["html"]      # no repo -> no button, no empty paragraph
    assert "View on GitHub" in both["html"] and "Download paper" in both["html"] and "download" in both["html"]


def test_every_existing_page_has_a_reference_template():
    index = json.loads((ROOT / "reference" / "index.json").read_text())
    assert len(index) >= 30
    for e in index:
        has_content = bool((ROOT / e["file"]).read_text().strip())
        assert has_content != e["empty"], f"{e['url']}: empty flag does not match the file"


# ── the decisions (Gil 2026-10-02): few buttons, one place each; a template for every page TYPE ──
# The site had 4 different GitHub buttons and three structural generations of "project page". These pin the
# decisions so the sprawl cannot quietly come back: adding a button or a page type is a deliberate act.

MAX_BUTTONS = 3        # Discover, View on GitHub, Download. Raise this deliberately, never by accident.
PAGE_TYPES = {"project", "hub", "all-projects", "content"}


def by_kind(kind):
    return [e for e in entries() if e["kind"] == kind]


def test_there_are_only_the_few_buttons_we_decided_on_and_each_has_one_job_and_one_place():
    buttons = by_kind("button")
    assert {b["id"] for b in buttons} == {"button-github", "button-download", "button-discover"}
    assert len(buttons) <= MAX_BUTTONS
    for b in buttons:
        assert b.get("role") and b.get("placement") and b.get("usedOn"), f"{b['id']} needs a role, a placement rule and the page types it is for"
        assert set(b["usedOn"]) <= {"project", "card"}


def test_every_page_type_has_exactly_one_plain_template_with_a_wireframe():
    pages = by_kind("page")
    assert {p["pageType"] for p in pages} == PAGE_TYPES
    assert len({p["pageType"] for p in pages}) == len(pages)          # one template per type, not several competing ones
    for p in pages:
        assert len(p.get("zones", [])) >= 2 and all(z.get("name") and z.get("note") for z in p["zones"]), p["id"]


def test_the_project_pages_action_row_only_offers_buttons_that_belong_on_a_project_page():
    project = next(p for p in by_kind("page") if p["pageType"] == "project")
    offered = project["slots"]["actions"]["options"]
    allowed = {b["id"] for b in by_kind("button") if "project" in b["usedOn"]}
    assert set(offered) == allowed
    assert 'class="action-row"' in project["slots"]["actions"]["wrap"]      # a fixed, findable place for them


def test_github_comes_before_download_in_the_action_row_order():
    project = next(p for p in by_kind("page") if p["pageType"] == "project")
    assert project["slots"]["actions"]["options"].index("button-github") < project["slots"]["actions"]["options"].index("button-download")


def test_every_template_has_a_specimen_that_renders_cleanly():
    """The Templates tab shows each template as what it is, using the sample content in the manifest."""
    import portfolio_templates as pt
    for t in pt.list_templates():
        r = pt.specimen(t["id"])
        assert r["ok"], (t["id"], r["missing"], r["errors"])
        assert r["html"].strip(), t["id"]


# ── ONE project card, everywhere ────────────────────────────────────────────
# Found 2026-10-02: the card markup was hand-copied into four places and the copies had drifted (stray WordPress
# paragraphs, a different button, inline styles), so the "same" card looked different on hub, All Projects and the
# footer. These pin it to one file.

PORTFOLIO = Path.home() / "Documents" / "Projects" / "portfolio-website-updater"


def _bin_card():
    import importlib.util
    spec = importlib.util.spec_from_file_location("_card", PORTFOLIO / "bin" / "_card.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_card_markup_exists_in_exactly_one_file():
    offenders = []
    for f in list((PORTFOLIO / "bin").glob("*.py")) + list((PORTFOLIO / "deploy").rglob("*.js")) + list((PORTFOLIO / "deploy").rglob("*.php")):
        if "card-container-lg" in f.read_text():
            offenders.append(f.name)
    assert offenders == [], f"card markup copied into: {offenders} (use deploy/other-projects/project-card.html)"
    template = PORTFOLIO / "templates" / "components" / "project-card.html"
    assert template.is_symlink() and template.resolve() == (PORTFOLIO / "deploy" / "other-projects" / "project-card.html").resolve()


def test_generators_render_the_same_card_as_the_template_renderer():
    import portfolio_templates as pt
    card = _bin_card()
    args = dict(url="/ai-projects/x/", title="A & B", thumbnail="/t.jpg", description="Does <things>.")
    via_generator = card.render_card(args["url"], args["title"], args["thumbnail"], args["description"])
    via_renderer = pt.render("project-card", {"URL": args["url"], "TITLE": args["title"], "THUMBNAIL": args["thumbnail"],
                                              "DESCRIPTION": args["description"]})["html"]
    assert via_generator == via_renderer
    also = card.render_card(args["url"], args["title"], args["thumbnail"], args["description"], ["Cybersecurity"])
    assert 'class="card-also">Also: Cybersecurity</p>' in also
    assert ">\n" not in via_generator and "> <" not in via_generator       # compact: nothing for WordPress to wrap in <p>


def test_footer_script_fills_the_same_card_as_the_generators():
    import json
    import shutil
    import subprocess
    import pytest
    if not shutil.which("node"):
        pytest.skip("node not available")
    card = _bin_card()
    manifest = json.loads((PORTFOLIO / "deploy/other-projects/manifest.json").read_text())
    js = (PORTFOLIO / "deploy/other-projects/other-projects.js").read_text()
    template = (PORTFOLIO / "deploy/other-projects/project-card.html").read_text()
    harness = """
      const vm = require('vm');
      const mount = {innerHTML: ''};
      let ready;
      const ctx = {
        window: {location: {pathname: '/ai-projects/mancala/'}},
        document: {addEventListener: (_e, f) => { ready = f; }, getElementById: () => mount},
        fetch: (u) => Promise.resolve(u.endsWith('.json') ? {json: () => Promise.resolve(%s)} : {text: () => Promise.resolve(%s)}),
        console,
      };
      vm.createContext(ctx);
      vm.runInContext(%s, ctx);
      ready();
      setTimeout(() => console.log(JSON.stringify(mount.innerHTML)), 50);
    """ % (json.dumps(manifest), json.dumps(template), json.dumps(js))
    out = json.loads(subprocess.run(["node", "-e", harness], capture_output=True, text=True, timeout=30, check=True).stdout)
    cards = [c for c in out.split('<div class="col-md-6">')[1:]]
    assert len(cards) == 2
    for chunk in cards:
        chunk = '<div class="col-md-6">' + chunk
        # the footer wraps cards in a row; cut each at the card's own closing tags
        chunk = chunk[: chunk.index("Discover</a></div></div>") + len("Discover</a></div></div>")]
        url = chunk.split('href="', 1)[1].split('"', 1)[0]
        p = next(p for p in manifest if p["url"] == url)
        others = [c for c in [p["category"]] + p.get("secondary_categories", []) if c != "AI & Machine Learning"]
        assert chunk == card.render_card(p["url"], p["title"], p["thumbnail"], p["description"], others)
