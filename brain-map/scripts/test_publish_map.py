#!/usr/bin/env python3
"""publish_map.py (ADR 0057): only deploy/marvin-map/ ever reaches the portfolio repo's main, from its own checkout."""
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
import publish_map  # noqa: E402


def git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def origin(tmp_path):
    """A bare 'portfolio repo' with an existing site under deploy/ and a workflow, like the real one."""
    bare = tmp_path / "origin.git"
    git(tmp_path, "init", "-q", "--bare", "-b", "main", str(bare))
    seed = tmp_path / "seed"
    git(tmp_path, "clone", "-q", str(bare), str(seed))
    git(seed, "config", "user.email", "t@t"); git(seed, "config", "user.name", "t")
    (seed / "deploy" / "longform").mkdir(parents=True)
    (seed / "deploy" / "longform" / "page.css").write_text("body{}\n")
    (seed / "README.md").write_text("site\n")
    git(seed, "add", "-A"); git(seed, "commit", "-q", "-m", "site"); git(seed, "push", "-q", "origin", "main")
    return bare


@pytest.fixture
def snapshot(tmp_path):
    s = tmp_path / "snapshot"
    (s / "vendor").mkdir(parents=True)
    (s / "index.html").write_text("<html>map v1</html>\n")
    (s / "tree-data.json").write_text("{}\n")
    (s / "vendor" / "motion.js").write_text("//m\n")
    return s


def files_on_main(bare, tmp_path):
    out = tmp_path / "check"
    if out.exists():
        git(out, "pull", "-q")
    else:
        git(tmp_path, "clone", "-q", str(bare), str(out))
    return sorted(str(p.relative_to(out)) for p in out.rglob("*") if p.is_file() and ".git" not in p.parts)


def test_publishes_only_the_map_folder(origin, snapshot, tmp_path):
    result = publish_map.publish(snapshot, tmp_path / "checkout", remote=str(origin))
    assert result.startswith("published")
    assert files_on_main(origin, tmp_path) == [
        "README.md", "deploy/longform/page.css",
        "deploy/marvin-map/index.html", "deploy/marvin-map/tree-data.json", "deploy/marvin-map/vendor/motion.js"]


def test_nothing_changed_means_no_commit(origin, snapshot, tmp_path):
    publish_map.publish(snapshot, tmp_path / "checkout", remote=str(origin))
    head = git(tmp_path, "--git-dir", str(origin), "rev-parse", "main")
    assert publish_map.publish(snapshot, tmp_path / "checkout", remote=str(origin)) == "unchanged"
    assert git(tmp_path, "--git-dir", str(origin), "rev-parse", "main") == head


def test_removed_snapshot_files_are_removed_and_others_kept(origin, snapshot, tmp_path):
    publish_map.publish(snapshot, tmp_path / "checkout", remote=str(origin))
    (snapshot / "vendor" / "motion.js").unlink()
    (snapshot / "index.html").write_text("<html>map v2</html>\n")
    publish_map.publish(snapshot, tmp_path / "checkout", remote=str(origin))
    files = files_on_main(origin, tmp_path)
    assert "deploy/marvin-map/vendor/motion.js" not in files
    assert "deploy/longform/page.css" in files


def test_someone_elses_push_in_between_is_kept(origin, snapshot, tmp_path):
    publish_map.publish(snapshot, tmp_path / "checkout", remote=str(origin))
    other = tmp_path / "gil"
    git(tmp_path, "clone", "-q", str(origin), str(other))
    git(other, "config", "user.email", "g@g"); git(other, "config", "user.name", "g")
    (other / "deploy" / "longform" / "page.css").write_text("body{color:red}\n")
    git(other, "commit", "-qam", "Gil's edit"); git(other, "push", "-q")
    (snapshot / "index.html").write_text("<html>map v3</html>\n")
    assert publish_map.publish(snapshot, tmp_path / "checkout", remote=str(origin)).startswith("published")
    assert git(tmp_path, "--git-dir", str(origin), "log", "-1", "--format=%s", "main~1") == "Gil's edit"


def test_refuses_a_commit_touching_anything_else(origin, snapshot, tmp_path, monkeypatch):
    monkeypatch.setattr(publish_map, "TARGET", "deploy/longform")  # simulates a bug pointing it elsewhere
    with pytest.raises(publish_map.PublishRefused):
        publish_map.publish(snapshot, tmp_path / "checkout", remote=str(origin))


def test_refuses_an_empty_snapshot(origin, tmp_path):
    empty = tmp_path / "empty"; empty.mkdir()
    with pytest.raises(publish_map.PublishRefused):
        publish_map.publish(empty, tmp_path / "checkout", remote=str(origin))


def test_the_checkout_is_not_somewhere_the_catalog_looks_for_projects():
    """2026-10-08: it lived in ~/Developer, the catalog took it for the portfolio repo, and page authoring broke."""
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lib"))
    import project_catalog
    for root in project_catalog.LOCAL_ROOTS:
        assert root not in publish_map.CHECKOUT.parents, f"{publish_map.CHECKOUT} is under catalog root {root}"
