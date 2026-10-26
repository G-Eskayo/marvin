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


# ── the scan's own entry point, end to end (P6, 2026-10-21) ────────────────
# ticket_pipeline._try_conflict_repair handed attempt() a lambda that did not accept the `pr=` keyword attempt()
# passes, so every repair crashed (523 times from 10-10 to 10-21) and fell through to a rebuild. The tests above
# call repair() directly and never went through that wiring. These do, with real git.
# conftest replaces _try_conflict_repair for every test; this module was imported first, so this is the real one.
import ticket_pipeline as tp  # noqa: E402
REAL_TRY_CONFLICT_REPAIR = tp._try_conflict_repair


@pytest.fixture
def scan_repair(origin_and_clone, tmp_path, monkeypatch):
    """The scan's repair entry point pointed at a real temp origin/clone, with its state file and tests in temp."""
    origin, clone = origin_and_clone
    monkeypatch.setattr(cr, "where", lambda repo: (str(clone), "main"))
    monkeypatch.setattr(cr, "STATE_PATH", tmp_path / "state" / "conflict-repair.json")
    monkeypatch.setattr(tp, "_REPAIR_BUDGET", None)
    seen = []
    monkeypatch.setattr(cr, "default_tests", lambda repo, cwd, changed: (seen.append(changed) or True, ""))
    monkeypatch.setenv("GIT_COMMITTER_NAME", "t"); monkeypatch.setenv("GIT_COMMITTER_EMAIL", "t@t")
    return clone, seen


def test_the_scans_repair_entry_point_repairs_a_real_conflict_and_pushes(scan_repair, tmp_path):
    clone, seen = scan_repair
    _branch(clone, "pipeline/pr", {"tests.py": "def test_a():\n    pass\n\ndef test_pr():\n    pass\n"})
    _main_moves(clone, {"tests.py": "def test_a():\n    pass\n\ndef test_main():\n    pass\n"})
    pr = {"number": 7, "title": "t", "body": "Closes #9", "headRefName": "pipeline/pr", "headRefOid": git(clone, "rev-parse", "origin/pipeline/pr")}
    res = REAL_TRY_CONFLICT_REPAIR("o/r", pr)
    assert res["outcome"] == "repaired", res
    assert "repair crashed" not in res.get("reason", "")
    git(clone, "fetch", "-q", "origin")
    assert git(clone, "merge-base", "--is-ancestor", "origin/main", "origin/pipeline/pr") == ""
    assert seen, "the project's tests must run before the push"


def test_a_genuine_conflict_reaches_the_model_with_the_prs_own_context(scan_repair, monkeypatch):
    clone, _ = scan_repair
    (clone / "code.py").write_text("timeout = 30\n")
    git(clone, "add", "-A"); git(clone, "commit", "-qm", "base"); git(clone, "push", "-q", "origin", "main")
    _branch(clone, "pipeline/pr", {"code.py": "timeout = 60\n"})
    _main_moves(clone, {"code.py": "timeout = 90\n"})
    prompts = []

    def fake_model(scratch, prompt):
        prompts.append(prompt)
        (Path(scratch) / "code.py").write_text("timeout = 75\n")
        return {"cost_usd": 0.02, "text": "ok", "exit_code": 0}
    monkeypatch.setattr(tp, "_resolve_hunks_with_model", fake_model)
    pr = {"number": 7, "title": "Raise the timeout", "body": "Closes #9\n\n## Acceptance criteria\n- timeout is 60",
          "headRefName": "pipeline/pr", "headRefOid": git(clone, "rev-parse", "origin/pipeline/pr")}
    res = REAL_TRY_CONFLICT_REPAIR("o/r", pr)
    assert res["outcome"] == "repaired" and res["cost_usd"] == 0.02, res
    assert prompts and "Raise the timeout" in prompts[0] and "#9" in prompts[0]   # the real PR, not a placeholder


def test_a_failed_repair_is_remembered_in_the_temp_state_not_the_real_one(scan_repair, tmp_path, monkeypatch):
    clone, _ = scan_repair
    (clone / "code.py").write_text("timeout = 30\n")
    git(clone, "add", "-A"); git(clone, "commit", "-qm", "base"); git(clone, "push", "-q", "origin", "main")
    _branch(clone, "pipeline/pr", {"code.py": "timeout = 60\n"})
    _main_moves(clone, {"code.py": "timeout = 90\n"})
    monkeypatch.setattr(tp, "_resolve_hunks_with_model", lambda scratch, prompt: {"cost_usd": 0.0, "text": "", "exit_code": 1})
    pr = {"number": 7, "body": "Closes #9", "headRefName": "pipeline/pr", "headRefOid": git(clone, "rev-parse", "origin/pipeline/pr")}
    res = REAL_TRY_CONFLICT_REPAIR("o/r", pr)
    assert res["outcome"] == "rebuild" and res["files"] == ["code.py"] and "crashed" not in res["reason"]
    state = (tmp_path / "state" / "conflict-repair.json")
    assert state.exists() and "o/r#7" in state.read_text()
    # the same commit is not retried on the next scan
    monkeypatch.setattr(tp, "_REPAIR_BUDGET", None)
    again = REAL_TRY_CONFLICT_REPAIR("o/r", pr)
    assert again["outcome"] == "rebuild" and again["cost_usd"] == 0.0


def test_a_crash_inside_repair_still_falls_back_to_a_rebuild(monkeypatch, tmp_path):
    monkeypatch.setattr(cr, "where", lambda repo: ("/nonexistent-clone", "main"))
    monkeypatch.setattr(cr, "STATE_PATH", tmp_path / "s.json")
    monkeypatch.setattr(tp, "_REPAIR_BUDGET", None)
    def boom(*a, **k):
        raise ValueError("boom")
    monkeypatch.setattr(cr, "repair", boom)
    res = REAL_TRY_CONFLICT_REPAIR("o/r", {"number": 1, "headRefName": "h", "headRefOid": "s"})
    assert res["outcome"] == "rebuild" and "boom" in res["reason"]
