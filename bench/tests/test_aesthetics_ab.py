"""Tests for aesthetics_ab.py (marvin#1116): the blind A/B for the prototype skill's aesthetics guidance.
Pure parts only (no model calls, no browser).
    ~/.agents/venv/bin/python -m pytest bench/tests/test_aesthetics_ab.py -v
"""
from __future__ import annotations

import json
import random
import sys
from pathlib import Path

import pytest

BENCH = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BENCH))

import aesthetics_ab as ab  # noqa: E402


# ── the treatment is the shipped text, not a copy ────────────────────────────

def test_guidance_is_mode_2_of_the_real_skill_file():
    g = ab.guidance()
    assert "<frontend_aesthetics>" in g and "Vary across variants" in g
    assert "Mode 1" not in g and "Seal Speak" not in g  # brand lock is not part of the treatment
    assert not g.startswith("## Mode 2")


def test_guidance_fails_loudly_when_the_section_is_missing(tmp_path):
    f = tmp_path / "AESTHETICS.md"
    f.write_text("# nothing here\n")
    with pytest.raises(SystemExit):
        ab.guidance(f)


# ── extracting the page from a reply ────────────────────────────────────────

def test_extracts_the_fenced_html():
    reply = "Here you go.\n```html\n<!doctype html><html><body>x</body></html>\n```\nEnjoy."
    assert ab.extract_html(reply) == "<!doctype html><html><body>x</body></html>"


def test_takes_the_longest_block_when_there_are_several():
    reply = "```html\n<b>tiny</b>\n```\n```html\n<html><body>the real page</body></html>\n```"
    assert "the real page" in ab.extract_html(reply)


def test_accepts_an_unfenced_document_and_rejects_prose():
    assert ab.extract_html("<!DOCTYPE html><html></html>").startswith("<!DOCTYPE")
    assert ab.extract_html("Sorry, I can't do that.") is None
    assert ab.extract_html("") is None


def test_an_unterminated_fence_still_yields_the_page():
    # a reply cut off at max tokens has no closing fence
    assert ab.extract_html("```html\n<html><body>cut") == "<html><body>cut"


# ── the deterministic "default look" check ──────────────────────────────────

@pytest.mark.parametrize("css,font", [
    ("body{font-family:'Inter',sans-serif}", "inter"),
    ('body { font-family: "Playfair Display", serif; }', "playfair display"),
    ("h1{font-family:x}body{font:16px/1.5 Roboto, Arial}", "roboto"),
    ("body{font-family:-apple-system,BlinkMacSystemFont,sans-serif}", "-apple-system"),
])
def test_primary_font_is_the_first_family_on_body(css, font):
    assert ab.primary_font(f"<style>{css}</style>") == font


def test_tailwind_font_sans_with_no_override_counts_as_system():
    assert ab.primary_font('<body class="font-sans bg-white">') == "system"


def test_tailwind_config_font_wins_over_the_class():
    html = "<script>tailwind.config={theme:{extend:{fontFamily:{sans:['Fraunces','serif']}}}}</script><body class='font-sans'>"
    assert ab.primary_font(html) == "fraunces"


def test_no_font_at_all_is_the_browser_default():
    assert ab.primary_font("<html><body>hi</body></html>") == "default"


@pytest.mark.parametrize("font,generic", [
    ("inter", True), ("roboto", True), ("system", True), ("default", True), ("-apple-system", True),
    ("arial", True), ("helvetica", True), ("open sans", True), ("lato", True),
    ("fraunces", False), ("inter tight", False), ("space grotesk", False),
])
def test_generic_fonts(font, generic):
    assert ab.is_generic_font(font) is generic


def test_purple_gradient_detection():
    assert ab.has_purple_gradient("background: linear-gradient(135deg, #667eea 0%, #764ba2 100%)")
    assert ab.has_purple_gradient('<div class="bg-gradient-to-r from-purple-600 to-indigo-600">')
    assert not ab.has_purple_gradient("background: linear-gradient(#0f1012, #1a1b1e)")
    assert not ab.has_purple_gradient("color: purple")  # purple text is not a purple gradient


# ── blind judging: order swap and the verdict tally ─────────────────────────

def test_parse_verdict():
    assert ab.parse_verdict("reasoning...\nWINNER: B") == "B"
    assert ab.parse_verdict("WINNER: tie") == "TIE"
    assert ab.parse_verdict("winner:a") == "A"
    assert ab.parse_verdict("I like both") is None


def test_tally_counts_a_pair_only_when_both_orders_agree():
    # each judged pair: (verdict with treatment shown as A, verdict with treatment shown as B)
    pairs = [("A", "B"),   # treatment won both ways
             ("B", "A"),   # control won both ways
             ("A", "A"),   # position bias: the judge always picked the left one
             ("TIE", "B"),  # one tie: counts as a tie
             (None, "B")]  # a failed call: counts as a tie, never a win
    t = ab.tally(pairs)
    assert t == {"treatment": 1, "control": 1, "tie": 3, "n": 5}


def test_tally_of_nothing():
    assert ab.tally([]) == {"treatment": 0, "control": 0, "tie": 0, "n": 0}


# ── the blind sheet for Gil ─────────────────────────────────────────────────

def _pairs():
    return [{"prompt": "landing", "rep": 1, "control": "landing/control-1.png", "treatment": "landing/treatment-1.png"},
            {"prompt": "settings", "rep": 1, "control": "settings/control-1.png", "treatment": "settings/treatment-1.png"}]


def test_sheet_hides_the_conditions_and_the_key_unblinds_it():
    html, key = ab.blind_sheet(_pairs(), random.Random(3))
    for word in ("control", "treatment", "with guidance", "without"):
        assert word not in html.lower()
    # images are referenced by neutral names only
    assert len(key) == 2 and all({k["left"], k["right"]} == {"control", "treatment"} for k in key)
    assert html.count("<img") == 4 and "control-1" not in html and "treatment-1" not in html


def test_unblind_maps_left_right_picks_to_conditions():
    key = [{"pair": 1, "left": "treatment", "right": "control"},
           {"pair": 2, "left": "control", "right": "treatment"},
           {"pair": 3, "left": "control", "right": "treatment"}]
    assert ab.unblind("LRT", key) == {"treatment": 2, "control": 0, "tie": 1, "n": 3}


def test_unblind_rejects_a_wrong_length_or_bad_letter():
    key = [{"pair": 1, "left": "treatment", "right": "control"}]
    with pytest.raises(SystemExit):
        ab.unblind("LR", key)
    with pytest.raises(SystemExit):
        ab.unblind("X", key)


def test_sheet_assignment_is_not_always_the_same_side():
    pairs = _pairs() * 10
    _, key = ab.blind_sheet(pairs, random.Random(0))
    lefts = {k["left"] for k in key}
    assert lefts == {"control", "treatment"}


def test_the_key_round_trips_through_json(tmp_path):
    _, key = ab.blind_sheet(_pairs(), random.Random(1))
    p = tmp_path / "key.json"
    p.write_text(json.dumps(key))
    assert json.loads(p.read_text()) == key


def test_a_css_variable_font_is_resolved():
    html = "<style>:root{--font-body:'Fraunces', serif}body{font-family:var(--font-body)}</style>"
    assert ab.primary_font(html) == "fraunces"
    assert ab.primary_font("<style>body{font-family:var(--missing)}</style>") == "var(--missing)"
