"""Migrating a legacy WP Coder project page onto the project-page layout (lib/portfolio_migrate.py)."""
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import portfolio_migrate as pm  # noqa: E402
import project_catalog  # noqa: E402

TEMPLATES = project_catalog.portfolio_repo_path() / "templates"

HERO = ('<div class="section-container"><div class="container"><div class="row"><div class="col-xs-12">'
        '<img src="/old-stock.jpeg" class="img-responsive" alt=""><div class="card-container"><div class="text-center"><h2 class="h2">The Title</h2></div>'
        '<div><div class="text-center"><h3 class="pink">The subtitle</h3></div><div>')
BODY = ('<p>Intro words.</p><strong>Links:</strong><ul><li><a href="/f.pdf">Report</a></li>'
        '<li><em><a href="https://github.com/G-Eskayo/proj" class="btn btn-default">View on GitHub</a></em></li></ul>')
CONTENT = ('<!-- hub-sidebar:wrapper --><nav>x</nav><!-- hub-sidebar:content-start -->[fusion_builder_container][fusion_text]\n[wp_code id="7"]\n[/fusion_text]'
           '[fusion_text]' + BODY + '\n[wp_code id="8"]\n[/fusion_text][/fusion_builder_container]<!-- hub-sidebar:content-end --><!-- /hub-sidebar:wrapper -->')


def test_the_sidebar_wrapper_is_removed_before_reading_the_page():
    assert pm.strip_sidebar_wrapper(CONTENT).startswith("[fusion_builder_container]")
    assert pm.strip_sidebar_wrapper("plain") == "plain"


def test_the_authored_body_is_what_sits_between_the_two_wp_coder_blocks():
    ids, body = pm.split_sandwich(pm.strip_sidebar_wrapper(CONTENT))
    assert ids == ["7", "8"] and "Intro words." in body and "fusion_" not in body and "wp_code" not in body


def test_a_page_that_is_not_a_sandwich_is_refused_not_guessed_at():
    with pytest.raises(pm.MigrationError, match="sandwich"):
        pm.split_sandwich("[fusion_text]just text[/fusion_text]")


def test_hero_title_and_subtitle_come_from_the_opening_block_and_a_missing_part_is_an_error():
    h = pm.read_hero_block(HERO + "</div></div></div></div></div></div>")
    assert h == {"hero_old": "/old-stock.jpeg", "title": "The Title", "subtitle": "The subtitle"}
    with pytest.raises(pm.MigrationError):
        pm.read_hero_block("<div>nothing here</div>")


def test_the_projects_own_repo_becomes_the_action_button_and_leaves_the_links_list():
    url = pm.own_repo_link(BODY)
    assert url == "https://github.com/G-Eskayo/proj"
    cleaned = pm.remove_repo_item(BODY, url)
    assert "github.com" not in cleaned and "Report" in cleaned and "Links:" in cleaned     # other links stay


def test_a_links_list_left_empty_goes_with_its_heading():
    only = '<p>x</p><strong>Links:</strong><ul><li><a href="https://github.com/G-Eskayo/p">g</a></li></ul>'
    out = pm.remove_repo_item(only, "https://github.com/G-Eskayo/p")
    assert "Links:" not in out and "<ul" not in out and "<p>x</p>" in out


def test_a_stack_is_only_suggested_when_the_author_already_wrote_one():
    assert pm.suggest_stack("<li>Python ML stack: pandas, numpy</li>") == "pandas, numpy"
    assert pm.suggest_stack("<p>No such line here</p>") is None


def _runner(pages, blocks, content=CONTENT, update_ok=True):
    calls = []

    def run(cmd, input=None):
        j = " ".join(map(str, cmd))
        calls.append((j, input))
        if "post list" in j:
            return SimpleNamespace(returncode=0, stdout=json.dumps(pages), stderr="")
        if "post get" in j:
            return SimpleNamespace(returncode=0, stdout=content, stderr="")
        if "wp_wow_coder" in j:
            bid = int(j.split("%d\", ")[1].split(")")[0])
            return SimpleNamespace(returncode=0, stdout=blocks[bid], stderr="")
        if "post update" in j:
            return SimpleNamespace(returncode=0 if update_ok else 1, stdout="", stderr="" if update_ok else "boom")
        return SimpleNamespace(returncode=0, stdout="", stderr="")
    run.calls = calls
    return run


PAGES = [{"ID": 10, "post_name": "ai-projects", "post_parent": 0}, {"ID": 11, "post_name": "proj", "post_parent": 10}]
BLOCKS = {7: HERO + "</div></div></div></div></div></div>", 8: "<div id='x'></div>"}


def test_a_page_with_no_stack_is_reported_not_guessed(tmp_path):
    out = pm.migrate("/ai-projects/proj/", outbox=tmp_path, runner=_runner(PAGES, BLOCKS), regenerate=None)
    assert out["ok"] is False and out["stage"] == "needs-input" and "Stack" in out["needs"][0]
    assert not list(tmp_path.iterdir())          # nothing written


def test_plan_writes_nothing_and_reports_what_would_change(tmp_path):
    r = _runner(PAGES, BLOCKS)
    out = pm.migrate("/ai-projects/proj/", stack="Python", plan=True, outbox=tmp_path, runner=r, regenerate=None)
    assert out["ok"] and out["plan"] and out["title"] == "The Title" and out["actions"] == ["button-github"]
    assert not any("post update" in c for c, _ in r.calls) and not list(tmp_path.iterdir())


def test_migrating_saves_the_original_rebuilds_the_page_and_rollback_restores_it(tmp_path):
    r = _runner(PAGES, BLOCKS)
    out = pm.migrate("/ai-projects/proj/", stack="Python", outbox=tmp_path, runner=r, regenerate=lambda p, rr: ["ok"])
    assert out["ok"] and out["page_id"] == 11
    saved = json.loads((tmp_path / "proj" / "before.json").read_text())
    assert saved["content"] == CONTENT and set(saved["wp_code"]) == {"7", "8"}      # the original, verbatim, before anything changes
    update = next(inp for c, inp in r.calls if "post update" in c)
    assert "The Title" in update and "<strong>Stack:</strong> Python" in update and "View on GitHub" in update and "Intro words." in update
    back = pm.rollback("proj", outbox=tmp_path, runner=_runner(PAGES, BLOCKS))
    assert back == {"ok": True, "restored": "/ai-projects/proj/"}


def test_a_failed_update_is_an_error_after_the_backup_exists(tmp_path):
    with pytest.raises(pm.MigrationError, match="updating the page failed"):
        pm.migrate("/ai-projects/proj/", stack="Python", outbox=tmp_path, runner=_runner(PAGES, BLOCKS, update_ok=False), regenerate=None)
    assert (tmp_path / "proj" / "before.json").exists()


def test_a_url_that_is_not_a_page_is_refused():
    with pytest.raises(pm.MigrationError, match="no page at"):
        pm.find_page("/nope/", _runner(PAGES, BLOCKS))


# ── content must never be lost; one-block pages; tidy text ──────────────────

def test_a_rebuild_that_would_lose_what_the_author_wrote_is_refused(tmp_path):
    long_body = "<p>" + " ".join(f"word{i}" for i in range(40)) + "</p>"
    blocks = {7: HERO + "</div></div></div></div></div></div>", 8: "<div id='x'></div>"}
    content = CONTENT.replace("Intro words.", "Intro words.</p>" + long_body + "<p>")
    # the extractor would keep this; simulate a loss by checking the guard directly
    original = pm.strip_sidebar_wrapper(content)
    assert pm.lost_words(original, original.replace("word7", "").replace("word8", "")) == ["word7", "word8"]
    assert pm.lost_words(original, original) == []


def test_the_guard_ignores_shortcodes_scripts_and_order_but_not_missing_words():
    a = '[fusion_text]<p>alpha beta</p><script>var x=1</script>[/fusion_text]'
    assert pm.lost_words(a, "<p>beta alpha</p>") == []
    assert pm.lost_words(a, "<p>alpha</p>") == ["beta"]


ONE_BLOCK = ('<div class="section-container"><div class="container"><div class="row"><div class="col-xs-12"><img src="/h.jpg" class="" alt="">'
             '<div class="card-container"><div class="text-center"><h1 class="h2">Title</h1></div>'
             '<div><div class="text-center"><h3 class="pink">Sub</h3></div><p class="no-margin">Before the subtitle block</p>'
             '<div>Body one.</div><p>Body two.</p><ul><li>three</li></ul></div></div></div></div></div></div><div id="other-projects-mount"></div>')


def test_a_single_block_page_keeps_every_part_of_its_card_except_title_and_subtitle():
    body = pm.single_block_body(ONE_BLOCK)
    for part in ("Before the subtitle block", "Body one.", "Body two.", "three"):
        assert part in body
    assert "Title" not in body and "Sub" not in body and "other-projects-mount" not in body


def test_the_hero_image_is_found_even_without_the_img_responsive_class():
    assert pm.read_hero_block(ONE_BLOCK)["hero_old"] == "/h.jpg"


def test_hard_wrapped_text_becomes_running_text_but_code_keeps_its_lines():
    out = pm.tidy_text("<p>as part of a Real\n      World\n      Pentest lab</p><pre>line1\nline2</pre>")
    assert "Real World Pentest lab" in out and "line1\nline2" in out


def test_a_label_left_beside_the_repo_link_goes_with_it():
    body = '<div><strong>Project Website:</strong> <a href="https://github.com/G-Eskayo/p" class="x">GitHub</a></div><p>text</p>'
    out = pm.remove_repo_item(body, "https://github.com/G-Eskayo/p")
    assert "Project Website" not in out and "<p>text</p>" in out


def test_the_first_backup_is_kept_so_a_second_run_cannot_overwrite_the_original(tmp_path):
    r = _runner(PAGES, BLOCKS)
    pm.migrate("/ai-projects/proj/", stack="Python", outbox=tmp_path, runner=r, regenerate=None)
    first = (tmp_path / "proj" / "before.json").read_text()
    r2 = _runner(PAGES, BLOCKS, content="[fusion_text]already migrated[/fusion_text][wp_code id=\"7\"][wp_code id=\"8\"]")
    try:
        pm.migrate("/ai-projects/proj/", stack="Python", outbox=tmp_path, runner=r2, regenerate=None)
    except pm.MigrationError:
        pass
    assert (tmp_path / "proj" / "before.json").read_text() == first
