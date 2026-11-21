"""Inventory of what is ACTUALLY on the portfolio site: every distinct button and every page.

Gil 2026-10-02: the Portfolio tab's components must be "representative of what is actually on the
website" -- all the buttons across the site and the full page templates -- not a few hand-written
examples. The collector crawls the dev site in a headless browser; these tests pin the pure parts:
how raw button records become distinct variants, and how pages are classified.
"""
from __future__ import annotations
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import portfolio_inventory as inv  # noqa: E402


def rec(page="/a/", text="Discover", cls="btn btn-default", href="/p/", kind="button", **styles):
    base = {"color": "rgb(25, 143, 217)", "backgroundColor": "rgba(0, 0, 0, 0)", "borderTopWidth": "1px",
            "borderTopStyle": "solid", "borderTopColor": "rgb(0, 0, 0)", "borderRadius": "0px",
            "paddingTop": "8px", "paddingLeft": "20px", "fontSize": "13px", "fontWeight": "700",
            "fontFamily": "Roboto Mono", "textTransform": "uppercase", "display": "inline-block",
            "letterSpacing": "normal", "textDecorationLine": "none"}
    base.update(styles)
    return {"page": page, "text": text, "cls": cls, "href": href, "tag": "a", "kind": kind, "region": "content",
            "html": f'<a class="{cls}">{text}</a>', "styles": base}


# ── signatures ──────────────────────────────────────────────────────────────

def test_identical_styling_gives_the_same_signature_regardless_of_text_page_or_href():
    assert inv.button_signature(rec(page="/a/", text="Discover")["styles"]) == inv.button_signature(rec(page="/b/", text="Other", href="/z/")["styles"])


def test_any_visible_style_difference_changes_the_signature():
    base = inv.button_signature(rec()["styles"])
    for change in ({"color": "rgb(1, 1, 1)"}, {"fontSize": "14px"}, {"borderTopWidth": "0px"}, {"paddingTop": "0px"},
                   {"textTransform": "none"}, {"backgroundColor": "rgb(255, 0, 0)"}):
        assert inv.button_signature(rec(**change)["styles"]) != base, change


def test_variant_id_is_stable_and_short():
    sig = inv.button_signature(rec()["styles"])
    assert inv.variant_id("button", sig) == inv.variant_id("button", sig)
    assert len(inv.variant_id("button", sig)) == 10
    assert inv.variant_id("button", sig) != inv.variant_id("github-link", sig)


# ── grouping ────────────────────────────────────────────────────────────────

def test_records_with_the_same_look_collapse_into_one_variant_with_a_count_and_the_pages_using_it():
    records = [rec(page="/a/"), rec(page="/b/"), rec(page="/a/", text="Discover more")]
    [v] = inv.group_buttons(records)
    assert v["count"] == 3 and v["pages"] == ["/a/", "/b/"]
    assert v["texts"] == ["Discover", "Discover more"]


def test_different_looks_stay_separate_and_the_most_used_comes_first():
    records = [rec(color="rgb(9, 9, 9)", page="/x/"), rec(page="/a/"), rec(page="/b/"), rec(page="/c/")]
    variants = inv.group_buttons(records)
    assert [v["count"] for v in variants] == [3, 1]


def test_github_links_are_their_own_kind_even_when_styled_like_a_button():
    variants = inv.group_buttons([rec(kind="github-link", text="GitHub"), rec(kind="button")])
    assert sorted(v["kind"] for v in variants) == ["button", "github-link"]


def test_a_variant_keeps_a_real_example_for_previewing_and_its_dominant_classes():
    records = [rec(cls="btn btn-default"), rec(cls="btn btn-default"), rec(cls="btn btn-default extra")]
    [v] = inv.group_buttons(records)
    assert v["example"]["html"].startswith("<a")
    assert v["classes"] == "btn btn-default"


def test_empty_input_gives_no_variants():
    assert inv.group_buttons([]) == []


# ── page classification ─────────────────────────────────────────────────────

MANIFEST = ["/ai-projects/mancala/", "/ai-projects/mitre/"]
HUBS = ["/ai-projects/", "/cybersecurity-projects/", "/software-engineering/"]


def test_project_hub_all_projects_and_ordinary_pages_are_told_apart():
    assert inv.classify_page("/ai-projects/mancala/", MANIFEST, HUBS) == "project"
    assert inv.classify_page("/ai-projects/", MANIFEST, HUBS) == "hub"
    assert inv.classify_page("/all-projects/", MANIFEST, HUBS) == "all-projects"
    assert inv.classify_page("/skills/", MANIFEST, HUBS) == "page"
    assert inv.classify_page("/", MANIFEST, HUBS) == "home"


def test_classification_ignores_a_missing_trailing_slash_and_the_host():
    assert inv.classify_page("http://localhost:8080/ai-projects/mancala", MANIFEST, HUBS) == "project"


# ── summary ─────────────────────────────────────────────────────────────────

def test_summary_counts_variants_and_flags_how_many_distinct_looks_each_kind_has():
    variants = inv.group_buttons([rec(), rec(color="rgb(9, 9, 9)"), rec(kind="github-link", text="GitHub")])
    s = inv.summarize(pages=[{"type": "project"}, {"type": "project"}, {"type": "hub"}], buttons=variants)
    assert s["pages"] == 3 and s["pages_by_type"] == {"project": 2, "hub": 1}
    assert s["button_variants"] == 2 and s["github_link_variants"] == 1


def test_chrome_catalogue_covers_every_part_that_wraps_a_page():
    import portfolio_inventory as inv
    ids = [c["id"] for c in inv.CHROME]
    assert ids == ["site-header", "page-title-bar", "hub-sidebar", "other-projects", "site-footer"]
    for c in inv.CHROME:
        assert c["selector"] and c["source"], c["id"]      # each says where it comes from, so nobody rebuilds it per page


# ── a crawl that could not reach WordPress must not replace a good inventory (marvin#585) ──
# Found 2026-10-21: on 2026-10-16 the dev site's wp-cli listing failed, the crawl carried on with only the "/" fallback,
# wrote a 1-page inventory over the real one, and the reference index was then rewritten as [] from it.

def test_collect_refuses_to_crawl_when_wordpress_cannot_list_its_pages(tmp_path, monkeypatch):
    import pytest
    import portfolio_apply as pa
    out = tmp_path / "inventory"; out.mkdir()
    (out / "inventory.json").write_text('{"pages": ["the good one"]}')
    manifest = tmp_path / "manifest.json"; manifest.write_text("[]")
    for listing in (None, "", "[]"):                       # wp-cli failed, printed nothing, or listed no pages
        monkeypatch.setattr(inv, "_wpcli", lambda args, _l=listing: _l)
        # Mock restart_wpcli_container to avoid real docker calls in the test
        monkeypatch.setattr(pa, "restart_wpcli_container", lambda runner=None: (False, "container unavailable"))
        with pytest.raises(RuntimeError, match="could not list"):
            inv.collect(out_dir=out, manifest_path=manifest)
        assert (out / "inventory.json").read_text() == '{"pages": ["the good one"]}'


# ── pure navigation and finalization ────────────────────────────────────────

def test_resolve_page_targets_converts_wp_pages_to_navigation_tuples():
    wp_pages = [
        {"post_title": "Home", "url": "/"},
        {"post_title": "Mancala", "url": "/ai-projects/mancala/", "ID": 1},
    ]
    targets = inv.resolve_page_targets(wp_pages)
    urls = [t[0] for t in targets if t[0] is not None]
    assert "/" in urls
    assert "/ai-projects/mancala/" in urls
    assert any(t[0] == "/" and t[1] == "Home" for t in targets)


def test_resolve_page_targets_adds_home_as_fallback():
    wp_pages = [{"post_title": "About", "url": "/about/"}]
    targets = inv.resolve_page_targets(wp_pages)
    assert any(t[0] == "/" and t[1] == "Home" for t in targets)


def test_collect_handles_absolute_urls_from_wp_cli():
    """wp-cli's post list --fields=url returns absolute URLs; missing_pages must handle them.

    When collect() gets pages with absolute URLs from wp-cli like
    'http://localhost:8080/ai-projects/mancala/', missing_pages() must extract
    the path and normalize it to match captured_urls.
    """
    # Simulate what wp-cli returns: absolute URLs from WordPress
    wp_pages = [
        {"url": "http://localhost:8080/ai-projects/mancala/"},
        {"url": "http://localhost:8080/ai-projects/marvin/"},
    ]
    # Simulate what collect() stores: extracted paths
    captured = {"/", "/ai-projects/mancala/"}

    # missing_pages must handle absolute URLs from wp-cli and correctly
    # identify which pages were not captured
    missing = inv.missing_pages(wp_pages, captured)
    assert "/ai-projects/marvin/" in missing
    assert "/ai-projects/mancala/" not in missing
    assert "/" not in missing  # home is always captured


def test_missing_pages_detects_wordpress_pages_not_captured():
    # wp-cli returns absolute URLs, not paths
    wp_pages = [
        {"url": "http://localhost:8080/ai-projects/mancala/"},
        {"url": "http://localhost:8080/ai-projects/marvin/"},
    ]
    captured = {"/", "/ai-projects/mancala/"}
    missing = inv.missing_pages(wp_pages, captured)
    assert "/ai-projects/marvin/" in missing
    assert "/" not in missing  # home is always required but should be in captured


def test_missing_pages_ignores_trailing_slash_normalization():
    # wp-cli returns absolute URLs; _norm should handle trailing slash normalization
    wp_pages = [{"url": "http://localhost:8080/ai-projects/mancala"}]  # no trailing slash
    captured = {"/ai-projects/mancala/"}  # with trailing slash (as stored by collect)
    missing = inv.missing_pages(wp_pages, captured)
    assert "/ai-projects/mancala/" not in missing


def test_finalize_backs_up_and_writes_inventory(tmp_path):
    result = {
        "pages": [{"url": "/", "title": "Home"}, {"url": "/about/", "title": "About"}],
        "buttons": [],
        "summary": {},
    }
    # wp-cli returns absolute URLs
    wp_pages = [
        {"url": "http://localhost:8080/"},
        {"url": "http://localhost:8080/about/"},
    ]
    inv.finalize(result, wp_pages, tmp_path)
    assert (tmp_path / "inventory.json").exists()
    assert (tmp_path / "inventory.json").read_text().startswith("{")


def test_finalize_creates_prev_backup_if_inventory_exists(tmp_path):
    old_result = {"pages": [{"url": "/"}], "buttons": []}
    (tmp_path / "inventory.json").write_text('{"old": "data"}')
    new_result = {"pages": [{"url": "/"}, {"url": "/about/"}], "buttons": [], "summary": {}}
    # wp-cli returns absolute URLs
    wp_pages = [
        {"url": "http://localhost:8080/"},
        {"url": "http://localhost:8080/about/"}
    ]
    inv.finalize(new_result, wp_pages, tmp_path)
    assert (tmp_path / "inventory.prev.json").exists()
    assert (tmp_path / "inventory.prev.json").read_text() == '{"old": "data"}'


def test_finalize_refuses_when_pages_are_missing(tmp_path):
    result = {"pages": [{"url": "/"}], "buttons": [], "summary": {}}
    # wp-cli returns absolute URLs
    wp_pages = [
        {"url": "http://localhost:8080/"},
        {"url": "http://localhost:8080/about/"}  # /about/ expected but not captured
    ]
    with pytest.raises(RuntimeError, match="incomplete"):
        inv.finalize(result, wp_pages, tmp_path)
    assert not (tmp_path / "inventory.json").exists()
