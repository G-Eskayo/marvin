"""Tests for code_sync.py's push(). Run via:
    ~/.agents/venv/bin/python -m pytest lib/tests/test_code_sync_push.py -v

Uses real temp git repos (a bare "origin" plus a working clone) rather than
mocking `git` — push()'s whole job is orchestrating real git state, so a
mocked subprocess wouldn't catch the class of bug this file guards against.
"""
from __future__ import annotations
import subprocess
import sys
from pathlib import Path

LIB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LIB))

import code_sync as cs  # noqa: E402


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


def _make_origin_and_clone(tmp_path: Path) -> Path:
    origin = tmp_path / "origin.git"
    origin.mkdir()
    _git(origin, "init", "--bare", "-b", "main")

    seed = tmp_path / "seed"
    seed.mkdir()
    _git(seed, "init", "-b", "main")
    _git(seed, "config", "user.email", "test@example.com")
    _git(seed, "config", "user.name", "Test")
    (seed / "sync-log.md").write_text("# log\n")
    (seed / "file.md").write_text("v1\n")
    _git(seed, "add", "-A")
    _git(seed, "commit", "-m", "seed")
    _git(seed, "push", str(origin), "main")

    clone = tmp_path / "clone"
    subprocess.run(["git", "clone", str(origin), str(clone)], check=True, capture_output=True)
    _git(clone, "config", "user.email", "test@example.com")
    _git(clone, "config", "user.name", "Test")
    return clone


def test_push_ships_a_clean_tree_with_unpushed_commits(tmp_path, monkeypatch):
    """Reproduces the real bug: a manual `git commit` (e.g. resolving a
    stash conflict by hand) leaves the working tree clean, but the commit
    itself was never pushed. push() must not silently no-op in that case."""
    monkeypatch.setattr(cs, "LOG_PATH", tmp_path / "unused-log.md")
    monkeypatch.setattr(cs, "notify", lambda *a, **kw: None)

    clone = _make_origin_and_clone(tmp_path)
    (clone / "file.md").write_text("v2 — resolved by hand\n")
    _git(clone, "add", "-A")
    _git(clone, "commit", "-m", "manual resolution commit")

    assert subprocess.run(["git", "status", "--porcelain"], cwd=clone, capture_output=True, text=True).stdout == ""

    cs.push(clone)

    origin_head = subprocess.run(["git", "rev-parse", "main"], cwd=clone.parent / "origin.git", capture_output=True, text=True).stdout.strip()
    clone_head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=clone, capture_output=True, text=True).stdout.strip()
    assert origin_head == clone_head, "push() left an already-committed, unpushed change stranded on a clean working tree"


def test_push_no_ops_when_truly_nothing_to_do(tmp_path, monkeypatch):
    monkeypatch.setattr(cs, "LOG_PATH", tmp_path / "unused-log.md")
    monkeypatch.setattr(cs, "notify", lambda *a, **kw: None)

    clone = _make_origin_and_clone(tmp_path)
    before = subprocess.run(["git", "rev-parse", "HEAD"], cwd=clone, capture_output=True, text=True).stdout.strip()

    cs.push(clone)

    after = subprocess.run(["git", "rev-parse", "HEAD"], cwd=clone, capture_output=True, text=True).stdout.strip()
    assert before == after
