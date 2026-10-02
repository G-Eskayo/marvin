"""Deterministic visual-consistency evaluation for the portfolio site.

Pure rule functions over MEASURED element data (the browser collector is a thin layer
on top), so every rule is testable without a browser. Found 2026-10-02: the site's
project pages drift apart (footer cards of differing height overlapping their heading,
6 GitHub-link wordings, one thumbnail reused by 6 projects) because nothing checked.
The "Other Projects" pair is randomised per view, so rules measure each card against a
rule and never compare to a fixed expected layout.
"""
from __future__ import annotations
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import portfolio_eval as pe  # noqa: E402

RULES = pe.DEFAULT_RULES


def card(x=100, y=500, w=281, h=230):
    return {"x": x, "y": y, "w": w, "h": h}


HEADING = {"x": 300, "y": 420, "w": 330, "h": 50}


def rules_of(findings):
    return sorted(f["rule"] for f in findings)


# ── footer ("Other Projects") ───────────────────────────────────────────────

def test_clean_footer_has_no_findings():
    cards = [card(x=100, y=520), card(x=500, y=520)]
    assert pe.check_footer(cards, HEADING, RULES) == []


def test_unequal_card_heights_are_flagged_beyond_tolerance_but_not_within_it():
    assert "footer-card-height" in rules_of(pe.check_footer([card(y=520, h=230), card(x=500, y=520, h=290)], HEADING, RULES))
    assert pe.check_footer([card(y=520, h=230), card(x=500, y=520, h=231)], HEADING, RULES) == []


def test_cards_at_different_vertical_positions_are_flagged():
    assert "footer-card-alignment" in rules_of(pe.check_footer([card(y=520), card(x=500, y=700)], HEADING, RULES))


def test_a_card_overlapping_the_heading_is_flagged():
    overlapping = card(x=350, y=440)          # starts inside the heading's box
    assert "footer-heading-overlap" in rules_of(pe.check_footer([overlapping, card(x=700, y=520)], HEADING, RULES))


def test_a_card_beside_or_below_the_heading_does_not_overlap_it():
    assert "footer-heading-overlap" not in rules_of(pe.check_footer([card(x=100, y=470), card(x=500, y=470)], HEADING, RULES))
    assert "footer-heading-overlap" not in rules_of(pe.check_footer([card(x=700, y=430)], HEADING, RULES))  # right of heading


def test_wrong_number_of_footer_cards_is_flagged():
    assert "footer-card-count" in rules_of(pe.check_footer([card()], HEADING, RULES))
    assert "footer-card-count" in rules_of(pe.check_footer([], HEADING, RULES))


# ── grids (hub pages, All Projects) ─────────────────────────────────────────

def test_grid_rows_with_equal_heights_are_clean_even_when_rows_differ_from_each_other():
    cards = [card(x=0, y=100, h=250), card(x=300, y=100, h=250), card(x=0, y=400, h=300), card(x=300, y=400, h=300)]
    assert pe.check_grid(cards, RULES) == []


def test_a_row_with_unequal_card_heights_is_flagged_once_per_row():
    cards = [card(x=0, y=100, h=250), card(x=300, y=100, h=310), card(x=0, y=500, h=250), card(x=300, y=500, h=250)]
    f = pe.check_grid(cards, RULES)
    assert rules_of(f) == ["grid-row-height"]
    assert "310" in f[0]["detail"]


# ── GitHub link component ───────────────────────────────────────────────────

CANON = {"text": "View on GitHub", "cls": "btn btn-default"}


def test_canonical_github_button_passes():
    assert pe.check_github_links([CANON], RULES) == []
    assert pe.check_github_links([{"text": "VIEW ON GITHUB", "cls": "btn  btn-default"}], RULES) == []  # case/space-insensitive


def test_wrong_wording_or_a_bare_text_link_is_flagged():
    assert "github-button-text" in rules_of(pe.check_github_links([{"text": "GitHub Repository", "cls": "btn btn-default"}], RULES))
    assert "github-button-style" in rules_of(pe.check_github_links([{"text": "View on GitHub", "cls": ""}], RULES))


def test_page_with_no_github_link_is_fine_projects_without_a_repo_must_not_fabricate_one():
    assert pe.check_github_links([], RULES) == []


# ── images ──────────────────────────────────────────────────────────────────

def test_a_thumbnail_shared_by_several_projects_is_flagged_once_naming_them_all():
    thumbs = {"A": "/u/x.jpg", "B": "/u/x.jpg", "C": "/u/y.jpg", "D": "/u/x.jpg"}
    f = pe.check_unique_images(thumbs)
    assert rules_of(f) == ["image-reused"]
    assert all(name in f[0]["detail"] for name in ("A", "B", "D")) and "C" not in f[0]["detail"]


def test_all_distinct_images_are_clean():
    assert pe.check_unique_images({"A": "/a.jpg", "B": "/b.jpg"}) == []


# ── overflow ────────────────────────────────────────────────────────────────

def test_horizontal_overflow_is_flagged_only_when_the_page_is_wider_than_the_viewport():
    assert pe.check_overflow(1090, 1090) == []
    assert pe.check_overflow(1090, 1091) == []     # 1px rounding is not a defect
    assert "page-overflow" in rules_of(pe.check_overflow(1090, 1294))


# ── rules loading + report ──────────────────────────────────────────────────

def test_rules_can_be_overridden_from_a_json_file_without_losing_defaults(tmp_path):
    f = tmp_path / "design-rules.json"
    f.write_text('{"github_button": {"text": "Source on GitHub"}, "tolerance_px": 5}')
    r = pe.load_rules(f)
    assert r["github_button"]["text"] == "Source on GitHub"
    assert r["github_button"]["classes"] == ["btn", "btn-default"]     # default kept
    assert r["tolerance_px"] == 5 and r["footer"]["expected_cards"] == 2


def test_a_missing_or_corrupt_rules_file_falls_back_to_the_defaults(tmp_path):
    assert pe.load_rules(tmp_path / "nope.json") == pe.DEFAULT_RULES
    bad = tmp_path / "bad.json"; bad.write_text("{not json")
    assert pe.load_rules(bad) == pe.DEFAULT_RULES


def test_summary_counts_findings_by_rule_and_lists_clean_pages():
    findings = [{"page": "/a/", "rule": "footer-heading-overlap", "detail": "x"},
                {"page": "/b/", "rule": "footer-heading-overlap", "detail": "y"},
                {"page": "/b/", "rule": "github-button-text", "detail": "z"}]
    s = pe.summarize(findings, pages=["/a/", "/b/", "/c/"])
    assert s["by_rule"] == {"footer-heading-overlap": 2, "github-button-text": 1}
    assert s["pages_checked"] == 3 and s["pages_with_findings"] == 2 and s["clean_pages"] == ["/c/"]


# ── the canonical button is for the project's OWN repo, not references ──────
# 2026-10-02: the first run flagged "AIMA Python Reference" and a raw payloadbox URL --
# links to OTHER people's repositories cited as references. Only links into the owner's
# own account are subject to the canonical-button rule.

def test_links_to_other_peoples_repos_are_references_and_are_ignored():
    refs = [{"text": "AIMA Python Reference", "cls": "", "href": "https://github.com/aimacode/aima-python"},
            {"text": "https://github.com/payloadbox/x", "cls": "", "href": "https://github.com/payloadbox/x"}]
    assert pe.check_github_links(refs, RULES) == []


def test_a_link_into_the_owners_account_is_still_checked():
    own = {"text": "GitHub", "cls": "", "href": "https://github.com/G-Eskayo/AI-algorithms/tree/main/Mancala"}
    assert rules_of(pe.check_github_links([own], RULES)) == ["github-button-style", "github-button-text"]


def test_owner_matching_is_case_insensitive_and_exact_not_a_substring():
    assert pe.check_github_links([{"text": "x", "cls": "", "href": "https://github.com/g-eskayo/repo"}], RULES) != []
    assert pe.check_github_links([{"text": "x", "cls": "", "href": "https://github.com/not-G-Eskayo-fan/repo"}], RULES) == []


def test_the_owner_is_a_rule_that_can_be_changed():
    r = pe.load_rules(Path("/nonexistent")); r["github_button"]["owner"] = "someone-else"
    assert pe.check_github_links([{"text": "x", "cls": "", "href": "https://github.com/G-Eskayo/r"}], r) == []
