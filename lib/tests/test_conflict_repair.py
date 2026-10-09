"""Tests for conflict_repair.py (the cheap fix before any rebuild, #314). Real git: a bare origin and a clone.
    ~/.agents/venv/bin/python -m pytest lib/tests/test_conflict_repair.py -v
"""
from __future__ import annotations
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import conflict_repair as cr  # noqa: E402


def git(cwd, *a):
    return subprocess.run(["git", *a], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def origin_and_clone(tmp_path):
    origin, clone = tmp_path / "origin.git", tmp_path / "clone"
    git(tmp_path, "init", "-q", "--bare", "-b", "main", str(origin))
    git(tmp_path, "clone", "-q", str(origin), str(clone))
    git(clone, "config", "user.email", "t@t"); git(clone, "config", "user.name", "t")
    (clone / "tests.py").write_text("def test_a():\n    pass\n")
    (clone / "code.py").write_text("x = 1\n")
    git(clone, "add", "-A"); git(clone, "commit", "-qm", "base"); git(clone, "push", "-q", "origin", "main")
    return origin, clone


def _branch(clone, name, edits):
    git(clone, "checkout", "-q", "-b", name, "origin/main")
    for f, text in edits.items():
        (clone / f).write_text(text)
    git(clone, "add", "-A"); git(clone, "commit", "-qm", name); git(clone, "push", "-q", "origin", name)
    git(clone, "checkout", "-q", "--detach")


def _main_moves(clone, edits):
    git(clone, "checkout", "-q", "-B", "main", "origin/main")
    for f, text in edits.items():
        (clone / f).write_text(text)
    git(clone, "add", "-A"); git(clone, "commit", "-qm", "main moves"); git(clone, "push", "-q", "origin", "main")
    git(clone, "checkout", "-q", "--detach")


PASS = lambda repo, cwd, changed: (True, "")  # noqa: E731


def test_both_appending_tests_is_repaired_tested_and_pushed(origin_and_clone):
    origin, clone = origin_and_clone
    _branch(clone, "pr", {"tests.py": "def test_a():\n    pass\n\ndef test_pr():\n    pass\n"})
    _main_moves(clone, {"tests.py": "def test_a():\n    pass\n\ndef test_main():\n    pass\n"})
    assert cr.conflicted_files(str(clone), "main", "pr") == ["tests.py"]
    seen = []
    res = cr.repair("o/r", "pr", str(clone), "main", run_tests=lambda r, cwd, ch: (seen.append(ch) or True, ""))
    assert res["outcome"] == "repaired" and "tests.py" in res["detail"]
    git(clone, "fetch", "-q", "origin")
    text = git(clone, "show", "origin/pr:tests.py")
    assert "test_main" in text and "test_pr" in text and text.index("test_main") < text.index("test_pr")
    assert git(clone, "merge-base", "--is-ancestor", "origin/main", "origin/pr") == ""  # now on top of main
    assert seen and "tests.py" in seen[0]


def test_a_real_conflict_is_not_touched_and_names_the_file(origin_and_clone):
    origin, clone = origin_and_clone
    _branch(clone, "pr", {"code.py": "x = 2\n"})
    _main_moves(clone, {"code.py": "x = 3\n"})
    before = git(clone, "rev-parse", "origin/pr")
    res = cr.repair("o/r", "pr", str(clone), "main", run_tests=PASS)
    assert res["outcome"] == "rebuild" and res["files"] == ["code.py"]
    git(clone, "fetch", "-q", "origin")
    assert git(clone, "rev-parse", "origin/pr") == before


def test_failing_tests_after_resolving_push_nothing(origin_and_clone):
    origin, clone = origin_and_clone
    _branch(clone, "pr", {"tests.py": "def test_a():\n    pass\n\ndef test_pr():\n    pass\n"})
    _main_moves(clone, {"tests.py": "def test_a():\n    pass\n\ndef test_main():\n    pass\n"})
    before = git(clone, "rev-parse", "origin/pr")
    res = cr.repair("o/r", "pr", str(clone), "main", run_tests=lambda r, cwd, ch: (False, "FAILED test_pr"))
    assert res["outcome"] == "rebuild" and "tests fail" in res["reason"]
    git(clone, "fetch", "-q", "origin")
    assert git(clone, "rev-parse", "origin/pr") == before


def test_the_shared_checkout_is_never_used_or_left_dirty(origin_and_clone):
    origin, clone = origin_and_clone
    _branch(clone, "pr", {"tests.py": "def test_a():\n    pass\n\ndef test_pr():\n    pass\n"})
    _main_moves(clone, {"tests.py": "def test_a():\n    pass\n\ndef test_main():\n    pass\n"})
    head = git(clone, "rev-parse", "HEAD")
    cr.repair("o/r", "pr", str(clone), "main", run_tests=PASS)
    assert git(clone, "rev-parse", "HEAD") == head and git(clone, "status", "--porcelain") == ""
    assert len(git(clone, "worktree", "list").splitlines()) == 1


def test_budget_and_memory(tmp_path, monkeypatch):
    monkeypatch.setattr(cr, "where", lambda repo: ("/clone", "main"))
    calls = []
    def fake(repo, head, clone, base):
        calls.append(head)
        return {"outcome": "rebuild", "files": ["a.py"], "reason": "real"}
    state = tmp_path / "s.json"
    b = cr.Budget(1)
    pr = {"number": 5, "headRefName": "h", "headRefOid": "sha1"}
    assert cr.attempt("o/r", pr, b, state, fake)["outcome"] == "rebuild"
    assert cr.attempt("o/r", {**pr, "number": 6}, b, state, fake) == {"outcome": "later"}       # out of budget
    assert cr.attempt("o/r", pr, cr.Budget(5), state, fake)["files"] == ["a.py"]                # same commit: not retried
    assert calls == ["h"]
    cr.attempt("o/r", {**pr, "headRefOid": "sha2"}, cr.Budget(5), state, fake)                    # a new commit is tried
    assert calls == ["h", "h"]


def test_no_clone_here_means_no_repair(monkeypatch):
    monkeypatch.setattr(cr, "where", lambda repo: (None, "main"))
    assert cr.attempt("o/r", {"number": 1, "headRefName": "h"}, cr.Budget())["outcome"] == "rebuild"
