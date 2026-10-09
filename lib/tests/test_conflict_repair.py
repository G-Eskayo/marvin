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
    assert res["cost_usd"] == 0.0  # No model call needed for both-added conflict
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
    assert res["cost_usd"] == 0.0  # No model call when no resolver provided
    git(clone, "fetch", "-q", "origin")
    assert git(clone, "rev-parse", "origin/pr") == before


def test_failing_tests_after_resolving_push_nothing(origin_and_clone):
    origin, clone = origin_and_clone
    _branch(clone, "pr", {"tests.py": "def test_a():\n    pass\n\ndef test_pr():\n    pass\n"})
    _main_moves(clone, {"tests.py": "def test_a():\n    pass\n\ndef test_main():\n    pass\n"})
    before = git(clone, "rev-parse", "origin/pr")
    res = cr.repair("o/r", "pr", str(clone), "main", run_tests=lambda r, cwd, ch: (False, "FAILED test_pr"))
    assert res["outcome"] == "rebuild" and "tests fail" in res["reason"]
    assert res["cost_usd"] == 0.0
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
    def fake(repo, head, clone, base, pr=None):
        calls.append(head)
        return {"outcome": "rebuild", "files": ["a.py"], "reason": "real", "cost_usd": 0.0}
    state = tmp_path / "s.json"
    b = cr.Budget(1)
    pr = {"number": 5, "headRefName": "h", "headRefOid": "sha1"}
    result1 = cr.attempt("o/r", pr, b, state, fake)
    assert result1["outcome"] == "rebuild"
    assert "cost_usd" in result1
    result2 = cr.attempt("o/r", {**pr, "number": 6}, b, state, fake)
    assert result2["outcome"] == "later"       # out of budget
    assert "cost_usd" in result2
    result3 = cr.attempt("o/r", pr, cr.Budget(5), state, fake)
    assert result3["files"] == ["a.py"]                # same commit: not retried
    assert "cost_usd" in result3
    assert calls == ["h"]
    cr.attempt("o/r", {**pr, "headRefOid": "sha2"}, cr.Budget(5), state, fake)                    # a new commit is tried
    assert calls == ["h", "h"]


def test_no_clone_here_means_no_repair(monkeypatch):
    monkeypatch.setattr(cr, "where", lambda repo: (None, "main"))
    result = cr.attempt("o/r", {"number": 1, "headRefName": "h"}, cr.Budget())
    assert result["outcome"] == "rebuild"
    assert result["cost_usd"] == 0.0


def test_both_sides_add_to_list_with_model_assist(origin_and_clone):
    """Both sides change the same existing line to different values - a genuine conflict model resolves."""
    origin, clone = origin_and_clone
    base_file = "code.py"
    # Start with a config with a value
    (clone / base_file).write_text("config = {\n    'timeout': 30,\n}\n")
    git(clone, "add", "-A"); git(clone, "commit", "-qm", "base config"); git(clone, "push", "-q", "origin", "main")

    # PR changes timeout to 60
    _branch(clone, "pr", {base_file: "config = {\n    'timeout': 60,\n}\n"})

    # Main changes timeout to 90
    _main_moves(clone, {base_file: "config = {\n    'timeout': 90,\n}\n"})

    assert cr.conflicted_files(str(clone), "main", "pr") == [base_file]

    # Fake model resolver that picks a compromise value
    def fake_resolve_hunks(scratch_dir, prompt):
        resolved_file = Path(scratch_dir) / base_file
        resolved_file.write_text("config = {\n    'timeout': 75,\n}\n")
        return {"cost_usd": 0.01, "text": "resolved", "exit_code": 0}

    res = cr.repair("o/r", "pr", str(clone), "main", run_tests=PASS, resolve_hunks=fake_resolve_hunks)
    assert res["outcome"] == "repaired"
    assert "model-assisted" in res["detail"]
    assert res["cost_usd"] == 0.01

    git(clone, "fetch", "-q", "origin")
    text = git(clone, "show", "origin/pr:" + base_file)
    assert "75" in text
    assert git(clone, "merge-base", "--is-ancestor", "origin/main", "origin/pr") == ""


def test_model_resolution_fails_verification(origin_and_clone):
    """Model resolution that leaves conflict markers or changes lines outside the conflict."""
    origin, clone = origin_and_clone
    base_file = "code.py"
    (clone / base_file).write_text("x = 1\ny = 2\n")
    git(clone, "add", "-A"); git(clone, "commit", "-qm", "base"); git(clone, "push", "-q", "origin", "main")

    _branch(clone, "pr", {base_file: "x = 2\ny = 2\n"})
    _main_moves(clone, {base_file: "x = 1\ny = 3\n"})

    before = git(clone, "rev-parse", "origin/pr")

    # Fake resolver that leaves conflict markers (fails verification)
    def bad_resolve_hunks(scratch_dir, prompt):
        resolved_file = Path(scratch_dir) / base_file
        resolved_file.write_text("x = 2\n<<<<<<<\ny = 2\n=======\ny = 3\n>>>>>>>\n")
        return {"cost_usd": 0.01, "text": "nope", "exit_code": 0}

    res = cr.repair("o/r", "pr", str(clone), "main", run_tests=PASS, resolve_hunks=bad_resolve_hunks)
    assert res["outcome"] == "rebuild"
    assert "verification failed" in res["reason"]
    assert res["cost_usd"] == 0.01

    git(clone, "fetch", "-q", "origin")
    assert git(clone, "rev-parse", "origin/pr") == before


def test_model_resolution_fails_tests(origin_and_clone):
    """Model resolution succeeds verification but tests fail."""
    origin, clone = origin_and_clone
    base_file = "code.py"
    (clone / base_file).write_text("x = 1\ny = 0\n")
    git(clone, "add", "-A"); git(clone, "commit", "-qm", "base"); git(clone, "push", "-q", "origin", "main")

    _branch(clone, "pr", {base_file: "x = 2\ny = 0\n"})
    _main_moves(clone, {base_file: "x = 1\ny = 3\n"})

    before = git(clone, "rev-parse", "origin/pr")

    def fake_resolve_hunks(scratch_dir, prompt):
        resolved_file = Path(scratch_dir) / base_file
        resolved_file.write_text("x = 2\ny = 3\n")  # Valid merge
        return {"cost_usd": 0.01, "text": "ok", "exit_code": 0}

    def failing_tests(repo, cwd, changed):
        return False, "test_x failed"

    res = cr.repair("o/r", "pr", str(clone), "main", run_tests=failing_tests, resolve_hunks=fake_resolve_hunks)
    assert res["outcome"] == "rebuild"
    assert "tests fail" in res["reason"]
    assert res["cost_usd"] == 0.01

    git(clone, "fetch", "-q", "origin")
    assert git(clone, "rev-parse", "origin/pr") == before


def test_cost_in_all_repair_outcomes(origin_and_clone):
    """Every repair outcome includes cost_usd."""
    origin, clone = origin_and_clone
    _branch(clone, "pr", {"tests.py": "def test_a():\n    pass\n\ndef test_pr():\n    pass\n"})
    _main_moves(clone, {"tests.py": "def test_a():\n    pass\n\ndef test_main():\n    pass\n"})

    # Success case
    res = cr.repair("o/r", "pr", str(clone), "main", run_tests=PASS)
    assert "cost_usd" in res
    assert res["cost_usd"] == 0.0  # No model call in this case

    # Create another conflict
    _branch(clone, "pr2", {"code.py": "x = 2\n"})
    _main_moves(clone, {"code.py": "x = 3\n"})

    # Failure case
    res2 = cr.repair("o/r", "pr2", str(clone), "main", run_tests=PASS)
    assert "cost_usd" in res2
    assert res2["cost_usd"] == 0.0
