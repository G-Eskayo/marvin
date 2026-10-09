"""Tests for test_change_rule.py (ADR 0063 gate 2, #336): code that changed without a test changing doesn't pass.
Written to break it: renames, deleted code, comment-only edits, generated files, docs and config, untracked new
files, unrelated test changes, a project without its own paths, and a huge diff. Against real git where it matters.

    ~/.agents/venv/bin/python -m pytest lib/tests/test_test_change_rule.py -v
"""
from __future__ import annotations
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import test_change_rule as tcr  # noqa: E402

R = tcr.MARVIN_RULES


def ch(path, status="M", added=("x = 1",), removed=()):
    return {"path": path, "status": status, "added": list(added), "removed": list(removed)}


# ── classifying paths ───────────────────────────────────────────────────────

def test_paths_are_code_tests_or_other():
    assert tcr.kind("lib/project_tagger.py", R) == "code"
    assert tcr.kind("lib/tests/test_project_tagger.py", R) == "test"
    assert tcr.kind("dashboard/src/components/X.jsx", R) == "code"
    assert tcr.kind("dashboard/test/x.test.js", R) == "test"
    assert tcr.kind("skills/route/scripts/route.py", R) == "code"
    assert tcr.kind("docs/adr/0063-x.md", R) == "other"
    assert tcr.kind("config/ticket_agents.json", R) == "other"
    assert tcr.kind("graphify-out/graph.json", R) == "other"      # generated
    assert tcr.kind("bench/metrics/x.json", R) == "other"         # generated


# ── the rule ────────────────────────────────────────────────────────────────

def test_code_with_a_test_change_passes_code_without_fails_with_a_reason_for_the_agent():
    ok, why = tcr.check([ch("lib/a.py"), ch("lib/tests/test_a.py")], R)
    assert ok
    ok, why = tcr.check([ch("lib/a.py")], R)
    assert not ok and "How we'll try to break it" in why and "lib/a.py" in why


def test_docs_config_and_generated_only_changes_pass():
    assert tcr.check([ch("docs/x.md"), ch("config/y.json"), ch("graphify-out/g.json")], R)[0]


def test_nothing_changed_passes():
    assert tcr.check([], R)[0]


def test_a_pure_rename_is_not_a_code_change():
    assert tcr.check([ch("lib/new_name.py", status="R100", added=(), removed=())], R)[0]


def test_deleting_code_still_needs_a_test_change():
    assert not tcr.check([ch("lib/old.py", status="D", added=(), removed=("def f():", "    return 1"))], R)[0]


def test_comment_only_and_blank_line_edits_are_not_code_changes():
    assert tcr.check([ch("lib/a.py", added=("# better wording", ""), removed=("# old wording",))], R)[0]
    assert tcr.check([ch("dashboard/src/x.js", added=("// clearer", "  * docs"), removed=())], R)[0]
    assert not tcr.check([ch("lib/a.py", added=("x = 2  # changed",), removed=("x = 1",))], R)[0]


def test_a_test_change_in_another_language_area_still_counts():
    # we can't prove a test covers the change; any test change is required, review judges the rest
    assert tcr.check([ch("lib/a.py"), ch("dashboard/test/y.test.js")], R)[0]


def test_another_project_uses_its_profile_paths_or_sensible_defaults():
    prof_rules = tcr.rules_for_profile({"code_paths": ["App/**"], "test_paths": ["AppTests/**"]})
    assert tcr.kind("App/View.swift", prof_rules) == "code" and tcr.kind("AppTests/T.swift", prof_rules) == "test"
    d = tcr.rules_for_profile(None)
    assert tcr.kind("src/a.ts", d) == "code" and tcr.kind("src/a.test.ts", d) == "test"
    assert tcr.kind("Sources/X.swift", d) == "code" and tcr.kind("Tests/XTests/XTests.swift", d) == "test"
    assert tcr.kind("README.md", d) == "other"


def test_a_huge_diff_is_handled():
    big = [ch(f"lib/m{i}.py", added=tuple(f"x{j} = {j}" for j in range(200))) for i in range(300)]
    assert not tcr.check(big, R)[0]
    assert tcr.check(big + [ch("lib/tests/test_m.py")], R)[0]


# ── against a real worktree ─────────────────────────────────────────────────

def git(cwd, *a):
    return subprocess.run(["git", *a], cwd=cwd, check=True, capture_output=True, text=True).stdout


@pytest.fixture
def repo(tmp_path):
    origin, wt = tmp_path / "origin.git", tmp_path / "wt"
    git(tmp_path, "init", "-q", "--bare", "-b", "main", str(origin))
    git(tmp_path, "clone", "-q", str(origin), str(wt))
    git(wt, "config", "user.email", "t@t"); git(wt, "config", "user.name", "t")
    (wt / "lib").mkdir(); (wt / "lib" / "tests").mkdir()
    (wt / "lib" / "a.py").write_text("x = 1\n")
    (wt / "lib" / "tests" / "test_a.py").write_text("def test_a():\n    assert True\n")
    git(wt, "add", "-A"); git(wt, "commit", "-qm", "base"); git(wt, "push", "-q", "origin", "main")
    return wt


def test_reads_committed_uncommitted_and_untracked_changes_from_a_worktree(repo):
    (repo / "lib" / "a.py").write_text("x = 2\n")                  # uncommitted edit
    (repo / "lib" / "new_mod.py").write_text("y = 1\n")            # untracked new file
    changes = tcr.changes_in(repo, "main")
    assert {c["path"] for c in changes} == {"lib/a.py", "lib/new_mod.py"}
    assert not tcr.check(changes, R)[0]
    (repo / "lib" / "tests" / "test_new.py").write_text("def test_n():\n    assert True\n")
    git(repo, "add", "-A"); git(repo, "commit", "-qm", "work")     # now committed, with a test
    assert tcr.check(tcr.changes_in(repo, "main"), R)[0]


def test_a_real_rename_without_edits_passes(repo):
    git(repo, "mv", "lib/a.py", "lib/b.py")
    assert tcr.check(tcr.changes_in(repo, "main"), R)[0]


def test_an_unreadable_worktree_fails_closed(tmp_path):
    ok, why = tcr.check_worktree(tmp_path / "missing", "main", R)
    assert not ok and "could not read" in why


def test_a_deleted_file_with_no_lines_shown_is_still_a_code_change():
    assert not tcr.check([ch("lib/gone.py", status="D", added=(), removed=())], R)[0]


def test_generated_output_never_counts_as_code_even_with_a_code_extension():
    assert tcr.kind("graphify-out/cache.py", R) == "other"
    d = tcr.rules_for_profile(None)                       # another project: every file may be code
    assert tcr.kind("graphify-out/cache.py", d) == "other" and tcr.check([ch("graphify-out/cache.py")], d)[0]


def test_a_repo_without_an_origin_compares_against_the_local_base_branch(tmp_path):
    repo = tmp_path / "solo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main"); git(repo, "config", "user.email", "t@t"); git(repo, "config", "user.name", "t")
    (repo / "lib").mkdir(); (repo / "lib" / "a.py").write_text("x = 1\n")
    git(repo, "add", "-A"); git(repo, "commit", "-qm", "base")
    git(repo, "checkout", "-q", "-b", "work")
    (repo / "lib" / "a.py").write_text("x = 2\n")
    git(repo, "commit", "-qam", "committed work")
    assert {c["path"] for c in tcr.changes_in(repo, "main")} == {"lib/a.py"}
