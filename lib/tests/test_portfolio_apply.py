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
    out = pa.apply(project, html, images, regenerate=False)
    assert out == {"images": 1, "manifest_changed": 1, "pages": []}
    repo = json.loads((project / "deploy/other-projects/manifest.json").read_text())
    dev = json.loads((html / "wp-content/other-projects/manifest.json").read_text())
    assert repo[0]["thumbnail"] == dev[0]["thumbnail"] == "/wp-content/uploads/generated/mancala-600w.jpg"


def _runner(fail_on=None):
    calls = []

    def run(cmd, **_):
        calls.append(cmd)
        joined = " ".join(map(str, cmd))
        if "post list" in joined:
            out = json.dumps([{"ID": 1, "post_name": n} for n in ("ai-projects", "cybersecurity-projects", "software-engineering", "all-projects")])
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
