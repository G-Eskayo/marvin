"""Applying generated images to the portfolio DEV site (lib/portfolio_apply.py)."""
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import portfolio_apply as pa  # noqa: E402

MANIFEST = """[
  {
    "title": "Mancala — Game AI",
    "url": "/ai-projects/mancala/",
    "thumbnail": "/wp-content/uploads/2024/03/work001-01.jpg",
    "description": "Plays Mancala."
  },
  {
    "title": "Other",
    "url": "/ai-projects/other/",
    "thumbnail": "/wp-content/uploads/2024/03/work001-01.jpg",
    "description": "x"
  }
]
"""


def _png(path, size=(2200, 600)):
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, (10, 40, 90)).save(path)


def test_publish_writes_a_thumbnail_and_hero_for_each_project_that_has_an_image(tmp_path):
    images, html = tmp_path / "images", tmp_path / "html"
    _png(images / "mancala.png")
    urls = pa.publish_images(json.loads(MANIFEST), images, html)
    assert urls == {"mancala": "/wp-content/uploads/generated/mancala-600w.jpg"}       # "other" has no image: left alone
    thumb = Image.open(html / "wp-content/uploads/generated/mancala-600w.jpg")
    assert thumb.size == pa.THUMB_SIZE                                                  # card-shaped, not the wide banner
    assert Image.open(html / "wp-content/uploads/generated/mancala-hero.jpg").size == (2200, 600)


def test_manifest_update_edits_only_the_thumbnail_values_and_keeps_formatting():
    new, changed = pa.update_manifest_text(MANIFEST, {"mancala": "/wp-content/uploads/generated/mancala-600w.jpg"})
    assert changed == 1
    assert json.loads(new)[0]["thumbnail"] == "/wp-content/uploads/generated/mancala-600w.jpg"
    assert json.loads(new)[1]["thumbnail"] == "/wp-content/uploads/2024/03/work001-01.jpg"     # untouched
    # nothing but that one line differs, so the repo diff is a one-line change per project
    diff = [(a, b) for a, b in zip(MANIFEST.splitlines(), new.splitlines()) if a != b]
    assert len(diff) == 1 and "thumbnail" in diff[0][0] and "—" in new                       # non-ASCII preserved too


def test_applying_twice_changes_nothing_the_second_time():
    urls = {"mancala": "/wp-content/uploads/generated/mancala-600w.jpg"}
    once, _ = pa.update_manifest_text(MANIFEST, urls)
    twice, changed = pa.update_manifest_text(once, urls)
    assert twice == once and changed == 0


def test_apply_updates_the_repo_manifest_and_the_dev_copy(tmp_path):
    project, html, images = tmp_path / "proj", tmp_path / "html", tmp_path / "images"
    (project / "deploy/other-projects").mkdir(parents=True)
    (project / "deploy/other-projects/manifest.json").write_text(MANIFEST)
    _png(images / "mancala.png")
    fake_runner = _runner()
    out = pa.apply(project, html, images, fake_runner, regenerate=False)
    assert out["images"] == 1
    assert out["manifest_changed"] == 1
    assert out["pages"] == []
    repo = json.loads((project / "deploy/other-projects/manifest.json").read_text())
    dev = json.loads((html / "wp-content/other-projects/manifest.json").read_text())
    assert repo[0]["thumbnail"] == dev[0]["thumbnail"] == "/wp-content/uploads/generated/mancala-600w.jpg"


def _runner(fail_on=None):
    calls = []

    def run(cmd, **_):
        calls.append(cmd)
        joined = " ".join(map(str, cmd))
        if "post list" in joined:
            out = json.dumps([{"ID": 1, "post_name": n, "post_parent": 0} for n in ("ai-projects", "cybersecurity-projects", "software-engineering", "all-projects")])
        elif "user list" in joined:
            out = "admin\n"
        elif "application-password create" in joined:
            out = "SECRET-PW\n"
        else:
            out = "ok\n"
        if fail_on and fail_on in joined:
            return SimpleNamespace(returncode=1, stdout="", stderr="boom SECRET-PW")
        return SimpleNamespace(returncode=0, stdout=out, stderr="")
    run.calls = calls
    return run


def test_regeneration_runs_every_generator_and_revokes_the_temporary_password(tmp_path):
    r = _runner()
    log = pa.regenerate_pages(tmp_path, r)
    scripts = [Path(c[1]).name for c in r.calls if len(c) > 1 and str(c[1]).endswith(".py")]
    assert scripts == ["generate-hub-page.py"] * 3 + ["generate-all-projects-page.py"] + ["generate-hub-sidebar-pages.py"] * 3
    assert len(log) == 7
    assert any("application-password" in " ".join(map(str, c)) and "delete" in c for c in r.calls)


def test_a_failing_generator_still_revokes_the_password_and_never_leaks_it(tmp_path):
    r = _runner(fail_on="generate-all-projects-page.py")
    with pytest.raises(RuntimeError) as e:
        pa.regenerate_pages(tmp_path, r)
    assert "SECRET-PW" not in str(e.value)
    assert any("delete" in c and "application-password" in " ".join(map(str, c)) for c in r.calls)


def test_best_cut_follows_the_subject_not_the_middle():
    import numpy as np
    img = Image.new("RGB", (2200, 600), (0, 0, 0))
    img.paste(Image.new("RGB", (300, 300), (255, 255, 255)), (1800, 150))     # the subject sits far to the right
    cut = pa.best_cut(img, 800 / 500)
    assert cut.size == (960, 600)
    assert np.asarray(cut.convert("L")).max() == 255                          # the subject is inside the cut


def test_best_cut_of_an_empty_banner_is_the_centre_and_a_narrow_image_is_returned_whole():
    flat = Image.new("RGB", (2200, 600), (20, 20, 20))
    cut = pa.best_cut(flat, 1.6)
    assert cut.size == (960, 600)
    square = Image.new("RGB", (500, 600))
    assert pa.best_cut(square, 1.6).size == (500, 600)


def test_published_images_also_go_into_deploy_because_only_deploy_ships_to_production(tmp_path):
    images, html, deploy = tmp_path / "images", tmp_path / "html", tmp_path / "deploy"
    _png(images / "mancala.png")
    pa.publish_images(json.loads(MANIFEST), images, html, deploy)
    for base in (html / "wp-content" / "uploads" / "generated", deploy / "uploads" / "generated"):
        assert (base / "mancala-600w.jpg").exists() and (base / "mancala-hero.jpg").exists()


# ── every wp-cli call runs as an admin, so WordPress's HTML filter can't strip tags ──
# Without a user, wp-cli writes go through kses, which allows <video> but drops <source>: that is how the SkineeDipping
# page lost its video (2026-10-06). An admin has unfiltered_html, so content is stored exactly as written.

def test_wp_base_runs_as_the_admin_user():
    cmd = pa.wp_base()
    assert cmd[0].endswith("docker") and cmd[1] == "exec" and pa.WPCLI in cmd
    assert f"--user={pa.WP_USER}" in cmd and "--path=/var/www/html" in cmd
    assert "-i" not in cmd and "-i" in pa.wp_base(interactive=True)


def test_no_portfolio_tool_builds_its_own_wp_cli_command():
    import re
    offenders = []
    for f in sorted(Path(pa.__file__).parent.glob("portfolio_*.py")):
        for n, line in enumerate(f.read_text().splitlines(), 1):
            if re.search(r'"docker",\s*"exec"', line) and "def wp_base" not in line and f.name != "portfolio_apply.py":
                offenders.append(f"{f.name}:{n}")
            if f.name == "portfolio_apply.py" and re.search(r'(?:"docker"|DOCKER),\s*"exec"', line) and "return" not in line:
                offenders.append(f"{f.name}:{n}")
    assert offenders == [], f"use portfolio_apply.wp_base() instead: {offenders}"


# ── hero sync ────────────────────────────────────────────────────────────────────

def test_page_hero_extracts_hero_src_from_fusion_code_block():
    import base64
    html = '<div class="col-xs-12"><img src="/old-hero.jpg" alt="x"/></div>'
    wrapped = f"[fusion_code]{base64.b64encode(html.encode()).decode()}[/fusion_code]"
    src = pa.page_hero(wrapped)
    assert src == "/old-hero.jpg"


def test_page_hero_returns_none_when_no_hero_image_found():
    html = '<div>no image here</div>'
    import base64
    wrapped = f"[fusion_code]{base64.b64encode(html.encode()).decode()}[/fusion_code]"
    src = pa.page_hero(wrapped)
    assert src is None


def test_page_hero_uses_col_xs_12_selector_first_then_img_responsive_then_any_img():
    import base64
    # Prioritize .col-xs-12 > img
    html1 = '<div class="col-xs-12"><img src="/preferred.jpg"/></div><img src="/fallback.jpg"/>'
    wrapped1 = f"[fusion_code]{base64.b64encode(html1.encode()).decode()}[/fusion_code]"
    assert pa.page_hero(wrapped1) == "/preferred.jpg"
    # Fallback to .img-responsive
    html2 = '<img class="img-responsive" src="/responsive.jpg"/><img src="/fallback.jpg"/>'
    wrapped2 = f"[fusion_code]{base64.b64encode(html2.encode()).decode()}[/fusion_code]"
    assert pa.page_hero(wrapped2) == "/responsive.jpg"
    # Fallback to first img
    html3 = '<img src="/first.jpg"/><img src="/second.jpg"/>'
    wrapped3 = f"[fusion_code]{base64.b64encode(html3.encode()).decode()}[/fusion_code]"
    assert pa.page_hero(wrapped3) == "/first.jpg"


def test_set_page_hero_rewrites_only_the_hero_src_and_reports_if_changed():
    import base64
    import re
    html = '<div class="col-xs-12"><img src="/old.jpg" alt="hero" title="x"/></div><p>body text</p>'
    wrapped = f"[fusion_code]{base64.b64encode(html.encode()).decode()}[/fusion_code]\nMore content"
    new_content, changed = pa.set_page_hero(wrapped, "/new-hero.jpg")
    assert changed is True
    assert "/new-hero.jpg" in new_content
    assert "/old.jpg" not in new_content
    # Verify body text is still in the base64-encoded fusion_code block
    m = re.search(r"\[fusion_code\]([^\[]+)\[/fusion_code\]", new_content)
    assert m
    decoded_html = base64.b64decode(m.group(1)).decode()
    assert "body text</p>" in decoded_html
    assert "More content" in new_content


def test_set_page_hero_is_idempotent():
    import base64
    html = '<div class="col-xs-12"><img src="/hero.jpg"/></div>'
    wrapped = f"[fusion_code]{base64.b64encode(html.encode()).decode()}[/fusion_code]"
    new_content1, changed1 = pa.set_page_hero(wrapped, "/hero.jpg")
    assert changed1 is False
    new_content2, changed2 = pa.set_page_hero(new_content1, "/hero.jpg")
    assert changed2 is False
    assert new_content1 == new_content2


def test_set_page_hero_returns_none_when_no_hero_found():
    import base64
    html = '<div>no image</div>'
    wrapped = f"[fusion_code]{base64.b64encode(html.encode()).decode()}[/fusion_code]"
    new_content, changed = pa.set_page_hero(wrapped, "/new-hero.jpg")
    assert changed is False
    assert new_content == wrapped  # unchanged when no hero found


def test_sync_hero_finds_page_and_updates_it():
    def fake_runner(cmd, **kw):
        joined = " ".join(map(str, cmd))
        if "post list" in joined:
            out = json.dumps([
                {"ID": 10, "post_name": "ai-projects", "post_parent": 0},
                {"ID": 123, "post_name": "marvin", "post_parent": 10}
            ])
        elif "post get" in joined and "123" in joined:
            import base64
            html = '<div class="col-xs-12"><img src="/old-hero.jpg"/></div>'
            wrapped = f"[fusion_code]{base64.b64encode(html.encode()).decode()}[/fusion_code]"
            out = wrapped
        else:
            out = "ok"
        return SimpleNamespace(returncode=0, stdout=out, stderr="")
    result = pa.sync_hero("marvin", "/ai-projects/marvin/", fake_runner)
    assert result["slug"] == "marvin"
    assert "page_hero_changed" in result


def test_sync_hero_warns_when_page_not_found():
    def fake_runner(cmd, **kw):
        joined = " ".join(map(str, cmd))
        if "post list" in joined:
            out = json.dumps([{"ID": 123, "post_name": "other", "post_parent": 0}])
        else:
            out = ""
        return SimpleNamespace(returncode=0, stdout=out, stderr="")
    result = pa.sync_hero("marvin", "/ai-projects/marvin/", fake_runner)
    assert "warning" in result
    assert result["slug"] == "marvin"


def test_sync_hero_does_not_update_when_hero_already_matches():
    call_count = {"post_update": 0}
    def fake_runner(cmd, **kw):
        joined = " ".join(map(str, cmd))
        if "post list" in joined:
            out = json.dumps([
                {"ID": 10, "post_name": "ai-projects", "post_parent": 0},
                {"ID": 123, "post_name": "marvin", "post_parent": 10}
            ])
        elif "post get" in joined:
            import base64
            html = '<div class="col-xs-12"><img src="/wp-content/uploads/generated/marvin-hero.jpg"/></div>'
            wrapped = f"[fusion_code]{base64.b64encode(html.encode()).decode()}[/fusion_code]"
            out = wrapped
        elif "post update" in joined:
            call_count["post_update"] += 1
            out = "ok"
        else:
            out = "ok"
        return SimpleNamespace(returncode=0, stdout=out, stderr="")
    result = pa.sync_hero("marvin", "/ai-projects/marvin/", fake_runner)
    assert result["page_hero_changed"] is False
    assert call_count["post_update"] == 0  # no update call when already matching


def test_apply_now_includes_hero_sync():
    call_log = []
    def fake_runner(cmd, **kw):
        joined = " ".join(map(str, cmd))
        call_log.append(joined)
        if "post list" in joined:
            out = json.dumps([
                {"ID": 1, "post_name": "ai-projects", "post_parent": 0},
                {"ID": 2, "post_name": "mancala", "post_parent": 1},
                {"ID": 3, "post_name": "other", "post_parent": 1},
                {"ID": 4, "post_name": "cybersecurity-projects", "post_parent": 0},
                {"ID": 5, "post_name": "software-engineering", "post_parent": 0},
                {"ID": 6, "post_name": "all-projects", "post_parent": 0}
            ])
        elif "post get" in joined:
            import base64
            html = '<div class="col-xs-12"><img src="/old.jpg"/></div>'
            wrapped = f"[fusion_code]{base64.b64encode(html.encode()).decode()}[/fusion_code]"
            out = wrapped
        elif "user list" in joined:
            out = "admin\n"
        elif "application-password create" in joined:
            out = "SECRET-PW\n"
        else:
            out = "ok"
        return SimpleNamespace(returncode=0, stdout=out, stderr="")

    project, html, images = Path("/tmp/proj"), Path("/tmp/html"), Path("/tmp/images")
    (project / "deploy/other-projects").mkdir(parents=True, exist_ok=True)
    (project / "deploy/other-projects/manifest.json").write_text(MANIFEST)
    _png(images / "mancala.png")

    out = pa.apply(project, html, images, fake_runner, regenerate=False)
    assert "hero_changed" in out
    assert out["images"] == 1


def test_hero_status_reports_matches_and_mismatches():
    def fake_runner(cmd, **kw):
        joined = " ".join(map(str, cmd))
        if "post list" in joined:
            out = json.dumps([
                {"ID": 1, "post_name": "ai-projects", "post_parent": 0},
                {"ID": 123, "post_name": "mancala", "post_parent": 1}
            ])
        elif "post get" in joined:
            import base64
            html = '<div class="col-xs-12"><img src="/wp-content/uploads/generated/mancala-hero.jpg"/></div>'
            wrapped = f"[fusion_code]{base64.b64encode(html.encode()).decode()}[/fusion_code]"
            out = wrapped
        else:
            out = "ok"
        return SimpleNamespace(returncode=0, stdout=out, stderr="")

    manifest = json.loads(MANIFEST)
    result = pa.hero_status(manifest, fake_runner)
    # mancala has no generated image, so it won't appear in the result
    assert "mancala" not in result
    # other has no generated image either
    assert "other" not in result
