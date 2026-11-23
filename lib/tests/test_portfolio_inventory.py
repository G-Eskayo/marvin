"""Inventory of what is ACTUALLY on the portfolio site: every distinct button and every page.

Gil 2026-10-02: the Portfolio tab's components must be "representative of what is actually on the
website" -- all the buttons across the site and the full page templates -- not a few hand-written
examples. The collector crawls the dev site in a headless browser; these tests pin the pure parts:
how raw button records become distinct variants, and how pages are classified.
"""
from __future__ import annotations
import sys
from pathlib import Path

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
    out = tmp_path / "inventory"; out.mkdir()
    (out / "inventory.json").write_text('{"pages": ["the good one"]}')
    manifest = tmp_path / "manifest.json"; manifest.write_text("[]")
    for listing in (None, "", "[]"):                       # wp-cli failed, printed nothing, or listed no pages
        monkeypatch.setattr(inv, "_wpcli", lambda args, _l=listing: _l)
        with pytest.raises(RuntimeError, match="could not list"):
            inv.collect(out_dir=out, manifest_path=manifest)
        assert (out / "inventory.json").read_text() == '{"pages": ["the good one"]}'


# ── pure functions: page_path, missing_pages, rotate_inventory ──

def test_page_path_extracts_path_from_wordpress_page_url():
    page = {"ID": 1, "post_name": "mancala", "url": "/ai-projects/mancala/"}
    assert inv.page_path(page) == "/ai-projects/mancala/"
    page_no_slash = {"ID": 1, "post_name": "mancala", "url": "/ai-projects/mancala"}
    assert inv.page_path(page_no_slash) == "/ai-projects/mancala/"


def test_page_path_handles_missing_url():
    page = {"ID": 1, "post_name": "mancala"}
    assert inv.page_path(page) == "/"


def test_missing_pages_finds_uncrawled_wordpress_pages():
    wp_pages = [
        {"ID": 1, "post_name": "home", "url": "/"},
        {"ID": 2, "post_name": "mancala", "url": "/ai-projects/mancala/"},
        {"ID": 3, "post_name": "marvin", "url": "/ai-projects/marvin/"},
    ]
    captured = {1, 2}
    missing = inv.missing_pages(wp_pages, captured)
    assert len(missing) == 1
    assert missing[0]["id"] == 3
    assert missing[0]["path"] == "/ai-projects/marvin/"


def test_missing_pages_returns_empty_when_all_pages_crawled():
    wp_pages = [{"ID": 1, "post_name": "home", "url": "/"}]
    captured = {1}
    assert inv.missing_pages(wp_pages, captured) == []


def test_rotate_inventory_backs_up_existing_inventory_to_old(tmp_path):
    out_dir = tmp_path
    inv_file = out_dir / "inventory.json"
    old_file = out_dir / "inventory.old.json"
    inv_file.write_text('{"new": "inventory"}')
    inv.rotate_inventory(out_dir)
    assert old_file.read_text() == '{"new": "inventory"}'


def test_rotate_inventory_is_idempotent(tmp_path):
    out_dir = tmp_path
    inv_file = out_dir / "inventory.json"
    old_file = out_dir / "inventory.old.json"
    inv_file.write_text('{"new": "inventory"}')
    inv.rotate_inventory(out_dir)
    inv.rotate_inventory(out_dir)  # Second call should not error
    assert old_file.read_text() == '{"new": "inventory"}'


def test_rotate_inventory_handles_missing_inventory_file(tmp_path):
    out_dir = tmp_path
    # Should not error even if inventory.json doesn't exist
    inv.rotate_inventory(out_dir)
    assert not (out_dir / "inventory.old.json").exists()


# ── defects that must stay fixed (code review 2026-11-20) ──

def test_collect_does_not_capture_id_when_redirect_collapses_to_root(tmp_path, monkeypatch):
    """When collect() navigates to a page but it redirects to /, that page's ID should not be captured.
    This exercises the redirect-collapse detection at collect():228-230: `landed_path == _norm(url)`.
    Without this check, deleting the `if landed_path == _norm(url):` line would leave the test green.
    """
    import pytest
    import json
    from unittest.mock import Mock, patch

    out = tmp_path / "inventory"
    out.mkdir()
    manifest = tmp_path / "manifest.json"
    manifest.write_text("[]")

    # WordPress has two pages: home and a broken page that redirects to /
    wp_pages_response = json.dumps([
        {"ID": 1, "post_name": "home", "post_title": "Home", "post_parent": 0, "url": "/"},
        {"ID": 123, "post_name": "broken", "post_title": "Broken", "post_parent": 0, "url": "/projects/broken/"},
    ])

    # Mock _wpcli to return the page list
    monkeypatch.setattr(inv, "_wpcli", lambda args, _list=wp_pages_response: _list)

    # Mock Playwright: page simulates redirect collapse for ID 123
    mock_page = Mock()
    visited = {}

    def mock_goto(url, wait_until=None):
        # Track visits and simulate: navigating to /projects/broken/ actually lands on /
        if "/projects/broken/" in url:
            mock_page.url = "http://localhost:8080/"  # Redirect to root
        else:
            mock_page.url = url  # Normal: page stays where requested
        visited[url] = mock_page.url

    mock_page.goto = mock_goto
    mock_page.evaluate.return_value = []  # No buttons
    mock_page.screenshot = Mock()
    mock_page.locator = Mock()

    mock_browser = Mock()
    mock_browser.new_page.return_value = mock_page
    mock_pw = Mock()
    mock_pw.chromium.launch.return_value = mock_browser

    # Create a mock Image for PIL.Image (used for screenshot resizing)
    mock_image = Mock()
    mock_image.size = (1280, 900)
    mock_image.resize.return_value = Mock()

    # sync_playwright is imported inside collect(), patch where it's imported
    with patch("playwright.sync_api.sync_playwright") as mock_sync_pw:
        mock_sync_pw.return_value.__enter__.return_value = mock_pw
        with patch("PIL.Image.open", return_value=mock_image):
            # collect() should raise because ID 123 was not captured (due to redirect)
            # and thus missing_pages() will find it missing
            with pytest.raises(RuntimeError, match="crawl incomplete.*broken"):
                inv.collect(base="http://localhost:8080", out_dir=out, manifest_path=manifest)


def test_norm_path_handles_missing_trailing_slash():
    """_norm() should normalize paths consistently (add trailing slash if missing)."""
    assert inv._norm("/projects/broken") == "/projects/broken/"
    assert inv._norm("/projects/broken/") == "/projects/broken/"
    assert inv._norm("http://example.com/projects/broken") == "/projects/broken/"


def test_norm_path_converts_root_to_slash():
    """_norm() should convert root URLs to '/'."""
    assert inv._norm("http://example.com") == "/"
    assert inv._norm("http://example.com/") == "/"
