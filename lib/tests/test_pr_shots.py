"""Tests for lib/pr_shots.py (marvin #735): images pinned by full SHA, pushed, written into the PR body. Run via:
    ~/.agents/venv/bin/python -m pytest lib/tests/test_pr_shots.py -v
"""
from __future__ import annotations
import json
import os
import stat
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "lib"))
import pr_images  # noqa: E402
import pr_shots  # noqa: E402

PNG = bytes.fromhex("89504e470d0a1a0a") + b"\0" * 32


def sh(cwd, *args):
    return subprocess.run(args, cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


def repo_with_remote(tmp_path, name="o/r"):
    """A checkout on a feature branch whose origin looks like GitHub but pushes to a local bare repo."""
    bare = tmp_path / "origin.git"
    sh(tmp_path, "git", "init", "-q", "--bare", str(bare))
    work = tmp_path / "work"
    work.mkdir()
    sh(work, "git", "init", "-q", "-b", "main")
    sh(work, "git", "config", "user.email", "t@example.com")
    sh(work, "git", "config", "user.name", "T")
    (work / "a.txt").write_text("a")
    sh(work, "git", "add", "a.txt")
    sh(work, "git", "commit", "-q", "-m", "init")
    sh(work, "git", "remote", "add", "origin", f"https://github.com/{name}.git")
    sh(work, "git", "config", "remote.origin.pushurl", str(bare))
    sh(work, "git", "checkout", "-q", "-b", "feat/2-icon")
    (work / "site").mkdir()
    (work / "site" / "page.html").write_text("<p>new look</p>")
    sh(work, "git", "add", "-A")
    sh(work, "git", "commit", "-q", "-m", "look")
    return work, bare


def fake_gh(tmp_path, pr_number="", body="Intro.\n\n## Decisions\n- [ ] yes"):
    """Answers `pr view` (number, body), records `pr edit --body-file` contents."""
    f = tmp_path / "gh"
    edited = tmp_path / "edited.md"
    f.write_text(f"""#!/bin/sh
case "$*" in
  "auth token") echo tok ;;
  *"--json number"*) echo "{pr_number}" ;;
  *"--json body"*) cat <<'EOF'
{body}
EOF
  ;;
  "pr edit"*) for last; do :; done; cp "$last" {edited} ;;
esac
""")
    f.chmod(f.stat().st_mode | stat.S_IEXEC)
    return f, edited


def run(work, gh, *args, monkeypatch):
    monkeypatch.chdir(work)
    monkeypatch.setattr(pr_shots, "GH", str(gh))
    return pr_shots.main(["--no-verify", *args])


def test_it_commits_pushes_and_pins_the_images_to_the_full_sha_in_the_pr(tmp_path, monkeypatch):
    work, bare = repo_with_remote(tmp_path)
    shot = tmp_path / "phone-light.png"
    shot.write_bytes(PNG)
    gh, edited = fake_gh(tmp_path, pr_number="11")
    run(work, gh, f"{shot}::The menu-bar M while listening", monkeypatch=monkeypatch)

    sha = sh(work, "git", "rev-parse", "HEAD")
    assert sh(work, "git", "show", "--name-only", "--format=", "HEAD") == "docs/images/pr/feat-2-icon/phone-light.png"
    assert sh(bare, "git", "rev-parse", "feat/2-icon") == sha  # pushed
    body = edited.read_text()
    url = f"https://raw.githubusercontent.com/o/r/{sha}/docs/images/pr/feat-2-icon/phone-light.png"
    assert f"![The menu-bar M while listening]({url})" in body
    assert body.index(pr_images.SHOTS_START) < body.index("## Decisions")
    # The gate agrees: a UI PR with these images, nothing changed since, goes through.
    assert pr_images.verdict(["site/page.html"], body, changed_since=lambda s: []) == []


def test_running_it_again_re_pins_instead_of_adding_a_second_section(tmp_path, monkeypatch):
    work, _ = repo_with_remote(tmp_path)
    shot = tmp_path / "a.png"
    shot.write_bytes(PNG)
    gh, edited = fake_gh(tmp_path, pr_number="11")
    run(work, gh, str(shot), monkeypatch=monkeypatch)
    first = edited.read_text()

    shot.write_bytes(PNG + b"retaken")
    gh2, edited2 = fake_gh(tmp_path / ".." / tmp_path.name, pr_number="11", body=first)
    run(work, gh2, str(shot), monkeypatch=monkeypatch)
    second = edited2.read_text()
    assert second.count(pr_images.SHOTS_START) == 1
    assert sh(work, "git", "rev-parse", "HEAD") in second and sh(work, "git", "rev-parse", "HEAD~1") not in second


def test_with_no_pr_yet_it_writes_the_section_into_the_body_file(tmp_path, monkeypatch):
    work, _ = repo_with_remote(tmp_path)
    shot = tmp_path / "a.png"
    shot.write_bytes(PNG)
    gh, edited = fake_gh(tmp_path, pr_number="")
    body_file = tmp_path / "body.md"
    body_file.write_text("What this does.")
    run(work, gh, str(shot), "--body-file", str(body_file), monkeypatch=monkeypatch)
    text = body_file.read_text()
    assert text.startswith("What this does.") and pr_images.SHOTS_START in text and not edited.exists()


def test_a_missing_image_stops_before_anything_is_committed(tmp_path, monkeypatch):
    work, _ = repo_with_remote(tmp_path)
    head = sh(work, "git", "rev-parse", "HEAD")
    gh, _ = fake_gh(tmp_path, pr_number="11")
    try:
        run(work, gh, str(tmp_path / "nope.png"), monkeypatch=monkeypatch)
        raise AssertionError("should have stopped")
    except SystemExit as e:
        assert "no such image" in str(e)
    assert sh(work, "git", "rev-parse", "HEAD") == head


def test_it_only_commits_the_images_not_other_work_in_progress(tmp_path, monkeypatch):
    work, _ = repo_with_remote(tmp_path)
    (work / "wip.txt").write_text("half done")
    sh(work, "git", "add", "wip.txt")
    shot = tmp_path / "a.png"
    shot.write_bytes(PNG)
    gh, _ = fake_gh(tmp_path, pr_number="11")
    run(work, gh, str(shot), monkeypatch=monkeypatch)
    assert "wip.txt" not in sh(work, "git", "show", "--name-only", "--format=", "HEAD")


def test_links_that_dont_answer_200_are_reported():
    class Resp:
        def __init__(self, status): self.status = status
        def __enter__(self): return self
        def __exit__(self, *a): return False
    import urllib.error
    def opener(req, timeout):
        assert req.headers.get("Authorization") == "token tok"
        if "bad" in req.full_url:
            raise urllib.error.HTTPError(req.full_url, 404, "nf", {}, None)
        return Resp(200)
    assert pr_shots.verify(["https://x/good.png", "https://x/bad.png"], "tok", opener=opener) == ["https://x/bad.png (404)"]
