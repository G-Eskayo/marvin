"""The add-project pipeline: spec in, finished dev-site change out (lib/portfolio_add_project.py)."""
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import portfolio_add_project as ap  # noqa: E402
import portfolio_imagegen as ig  # noqa: E402

TEMPLATES = Path.home() / "Documents" / "Projects" / "portfolio-website-updater" / "templates"

MANIFEST = """[
  {
    "title": "Mancala",
    "url": "/ai-projects/mancala/",
    "category": "AI & Machine Learning",
    "secondary_categories": [],
    "thumbnail": "/t.jpg",
    "description": "Plays."
  }
]
"""

SPEC = {"title": "Weather Station", "slug": "weather-station", "category": "Software Engineering", "subtitle": "Predicts rain",
        "description": "A small Pi station.", "body_html": "<p>Hello.</p>", "stack_csv": "Python, Pi",
        "github_url": "https://github.com/G-Eskayo/weather", "download_url": "/wp-content/uploads/r.pdf"}


@pytest.fixture
def env(tmp_path):
    project = tmp_path / "proj"
    (project / "deploy/other-projects").mkdir(parents=True)
    (project / "deploy/other-projects/manifest.json").write_text(MANIFEST)
    return SimpleNamespace(project=project, html=tmp_path / "html", images=tmp_path / "images", registry=tmp_path / "reg.json", tmp=tmp_path)


def runner(created=None, pages=None, fail_create=False):
    calls = []
    pages = pages if pages is not None else [{"ID": 5957, "post_name": "software-engineering", "post_parent": 0}]

    def run(cmd, input=None):
        calls.append((cmd, input))
        joined = " ".join(map(str, cmd))
        if "post list" in joined:
            return SimpleNamespace(returncode=0, stdout=json.dumps(pages), stderr="")
        if "post create" in joined:
            if fail_create:
                return SimpleNamespace(returncode=1, stdout="", stderr="boom")
            return SimpleNamespace(returncode=0, stdout="6001\n", stderr="")
        return SimpleNamespace(returncode=0, stdout="", stderr="")
    run.calls = calls
    return run


def run_add(env, spec=SPEC, **kw):
    kw.setdefault("runner", runner())
    kw.setdefault("regenerate", lambda project, r: ["regenerated"])
    return ap.add_project(spec, project=env.project, html_dir=env.html, images_dir=env.images, registry_path=env.registry,
                          templates_root=TEMPLATES, **kw)


def test_normalise_orders_buttons_github_first_and_derives_image_urls():
    s = ap.normalise({**SPEC, "slug": "weather-station"})
    assert [a["template"] for a in s["actions"]] == ["button-github", "button-download"]
    assert s["hero_image_url"] == "/wp-content/uploads/generated/weather-station-hero.jpg"
    assert s["thumbnail"].endswith("weather-station-600w.jpg")


def test_a_project_without_a_repo_gets_no_button_never_an_invented_one():
    s = ap.normalise({k: v for k, v in SPEC.items() if k not in ("github_url", "download_url")})
    assert s["actions"] == []


def test_dry_run_validates_and_writes_nothing(env):
    out = run_add(env, dry_run=True)
    assert out["ok"] and out["dry_run"] and out["url"] == "/software-engineering/weather-station/"
    assert (env.project / "deploy/other-projects/manifest.json").read_text() == MANIFEST
    assert not env.images.exists() and not env.html.exists()


def test_a_bad_spec_is_reported_before_anything_is_written(env):
    out = run_add(env, spec={**SPEC, "category": "Cooking"})
    assert out["ok"] is False and out["stage"] == "plan" and any("category" in e for e in out["errors"])
    assert not env.images.exists()


def test_a_project_already_in_the_manifest_is_refused(env):
    out = run_add(env, spec={**SPEC, "slug": "mancala", "category": "AI & Machine Learning"})
    assert out["ok"] is False and "already in the manifest" in out["errors"][0]


def test_full_run_creates_page_image_manifest_entry_and_regenerates(env):
    r = runner()
    out = run_add(env, runner=r, evaluate=lambda: {"findings": [{"page": "/x/ @1440", "rule": "r"}, {"page": "/software-engineering/weather-station/ @1440", "rule": "github-button-style"}]})
    assert out["ok"] and out["page_id"] == 6001 and out["pages_regenerated"] == ["regenerated"]
    # the page is created under its category hub with the rendered content on stdin
    create = next(c for c in r.calls if "post create" in " ".join(map(str, c[0])))
    assert "--post_parent=5957" in create[0] and "--post_name=weather-station" in create[0]
    assert "Weather Station" in create[1] and "View on GitHub" in create[1]
    # the image exists on the dev site and the manifest (repo + dev copy) has exactly one new entry
    assert (env.html / "wp-content/uploads/generated/weather-station-600w.jpg").exists()
    repo = json.loads((env.project / "deploy/other-projects/manifest.json").read_text())
    dev = json.loads((env.html / "wp-content/other-projects/manifest.json").read_text())
    assert [p["url"] for p in repo] == ["/ai-projects/mancala/", "/software-engineering/weather-station/"] == [p["url"] for p in dev]
    assert repo[1]["thumbnail"].endswith("weather-station-600w.jpg")
    # only findings about the new page are reported back
    assert [f["rule"] for f in out["findings_for_new_page"]] == ["github-button-style"]
    assert json.loads(env.registry.read_text())["weather-station"]["chosen"] is True


def test_the_manifest_diff_is_exactly_the_new_entry():
    entry = {"title": "T", "url": "/a/b/", "category": "C", "secondary_categories": [], "thumbnail": "/t.jpg", "description": "é — d"}
    new = ap.append_manifest_entry(MANIFEST, entry)
    assert json.loads(new)[-1] == entry and "é — d" in new
    old_lines, new_lines = MANIFEST.splitlines(), new.splitlines()
    assert new_lines[: len(old_lines) - 2] == old_lines[:-2]            # everything before the join is untouched
    assert ap.append_manifest_entry("[\n]\n", entry).count('"url"') == 1  # an empty manifest works too


def test_a_missing_category_hub_or_an_existing_page_stops_before_the_manifest_changes(env):
    with pytest.raises(ap.AddProjectError, match="hub page"):
        run_add(env, runner=runner(pages=[]))
    assert (env.project / "deploy/other-projects/manifest.json").read_text() == MANIFEST
    existing = [{"ID": 5957, "post_name": "software-engineering", "post_parent": 0}, {"ID": 9, "post_name": "weather-station", "post_parent": 5957}]
    with pytest.raises(ap.AddProjectError, match="already exists"):
        run_add(env, runner=runner(pages=existing))
    assert (env.project / "deploy/other-projects/manifest.json").read_text() == MANIFEST


def test_a_failed_page_creation_leaves_the_manifest_alone(env):
    with pytest.raises(ap.AddProjectError, match="creating the page failed"):
        run_add(env, runner=runner(fail_create=True))
    assert (env.project / "deploy/other-projects/manifest.json").read_text() == MANIFEST


def test_new_images_are_unique_against_those_already_in_use(env):
    run_add(env)
    other = {**SPEC, "title": "Other", "slug": "other-thing", "github_url": None, "download_url": None}
    run_add(env, spec=other, runner=runner())
    reg = json.loads(env.registry.read_text())
    a, b = int(reg["weather-station"]["hash"], 16), int(reg["other-thing"]["hash"], 16)
    assert ig.hamming(a, b) >= ig.MIN_DISTANCE or "warning" in reg["other-thing"]
