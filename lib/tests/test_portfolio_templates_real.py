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
          "FILE_URL": "/wp-content/uploads/paper.pdf"}


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
