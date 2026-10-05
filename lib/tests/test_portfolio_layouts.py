"""Page layouts captured from the live dev site and the pages that follow them (lib/portfolio_layouts.py)."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import portfolio_layouts as pl  # noqa: E402

PROJECT = Path.home() / "Documents" / "Projects" / "portfolio-website-updater"

PAGE = ('<div class="section-container"><div class="container"><div class="row"><div class="col-xs-12">'
        '<img src="/h.jpg" class="img-responsive" alt=""><div class="card-container"><div class="text-center"><h1 class="h2">T</h1></div>'
        '<div><div class="text-center"><h3 class="pink">S</h3></div><div>{BODY}<p><strong>Stack:</strong> Python.</p>{ACTIONS}</div></div>'
        '</div></div></div></div></div><div id="other-projects-mount"></div>')


def page(body="<p>one</p><p>two</p>", actions=""):
    return PAGE.replace("{BODY}", body).replace("{ACTIONS}", actions)


def test_only_structure_matters_not_words_or_how_many_body_blocks():
    a = pl.skeleton(page("<p>one</p>"))
    b = pl.skeleton(page("<p>one</p><ul><li>x</li></ul><h4>more</h4><p>words</p>"))
    assert a == b and "{body} {stack}" in a


def test_the_embedded_footer_mount_counts_even_while_empty_and_its_filled_cards_are_not_part_of_the_layout():
    empty = pl.skeleton(page())
    filled = pl.skeleton(page().replace('<div id="other-projects-mount"></div>', '<div id="other-projects-mount"><div class="container"><div class="row"><div class="col-md-6"><div class="card-container-lg">x</div></div></div></div></div>'))
    assert "{other-projects}" in empty and empty == filled


def test_an_action_row_is_optional_but_a_bare_button_paragraph_counts_as_one():
    none, row = pl.skeleton(page()), pl.skeleton(page(actions='<p class="action-row"><a class="btn btn-default" href="#">View on GitHub</a></p>'))
    bare = pl.skeleton(page(actions='<p><a class="btn btn-default" href="#">View on GitHub</a></p>'))
    assert row == bare and "{actions}" in row and "{actions}" not in none
    assert pl.diff_summary(none, row) == ""             # a page without an action row follows the layout too


def test_a_missing_stack_line_and_extra_elements_are_named():
    legacy = pl.skeleton(page().replace('<p><strong>Stack:</strong> Python.</p>', '<ul><li><a class="btn btn-default" href="#">x</a></li></ul>'))
    why = pl.diff_summary(pl.skeleton(page()), legacy)
    assert "missing {stack}" in why


def test_a_repeated_category_section_is_one_zone_whatever_the_number_of_categories():
    def section(n):
        return '<div class="text-center"><h2 class="h2">C</h2></div><div class="col-md-12 sm-2-items"><div class="row">' + '<div class="col-md-6"><div class="card-container-lg"></div></div>' * n + '</div></div>'
    wrap = lambda inner: f'<div class="other"><div class="container"><div class="row">{inner}</div></div></div>'
    assert pl.skeleton(wrap(section(2) * 2)) == pl.skeleton(wrap(section(3) * 3)) == pl.skeleton(wrap(section(1) * 5))


def test_the_captured_layouts_record_which_pages_follow_them():
    for lid in ("layout-project-page", "layout-hub-page", "layout-all-projects-page"):
        f = PROJECT / "templates" / "elements" / f"{lid}.json"
        if not f.exists():
            continue
        rec = json.loads(f.read_text())
        assert rec["kind"] == "layout" and rec["master_skeleton"] and rec["total"] == len(rec["pages"])
        assert rec["conforming"] == sum(1 for v in rec["pages"].values() if v["conforms"])
        for v in rec["pages"].values():
            assert v["conforms"] or v["why"]               # every page that does not follow the layout says why
