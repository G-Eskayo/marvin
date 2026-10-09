"""Tests for commit_check.py (ADR 0063 gate 4, #337): a direct commit that changes code without a test needs a
stated reason. Real repos, the real hook, real `git commit`. Written to break it: empty / filler reasons, the reason
outside a trailer, auto-sync, merges, rebases, cherry-picks, docs-only, a non-ASCII message, an unwritable log, and an
existing commit-msg hook we must not clobber.

    ~/.agents/venv/bin/python -m pytest lib/tests/test_commit_check.py -v
"""
from __future__ import annotations
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import commit_check as cc  # noqa: E402


def git(cwd, *a, env=None, check=True):
    return subprocess.run(["git", *a], cwd=cwd, capture_output=True, text=True, check=check,
                          env={**os.environ, **(env or {})})


@pytest.fixture
def repo(tmp_path, monkeypatch):
    log = tmp_path / "skips.jsonl"
    monkeypatch.setenv("MARVIN_TEST_SKIP_LOG", str(log))
    r = tmp_path / "repo"
    r.mkdir()
    git(r, "init", "-q", "-b", "main"); git(r, "config", "user.email", "t@t"); git(r, "config", "user.name", "t")
    (r / "lib").mkdir(); (r / "lib" / "tests").mkdir(); (r / "docs").mkdir()
    (r / "lib" / "a.py").write_text("x = 1\n")
    git(r, "add", "-A"); git(r, "commit", "-qm", "base")
    assert cc.install_hook(r) == "installed"
    return r, log


def commit(r, msg, env=None):
    return git(r, "commit", "-q", "-am", msg, env=env, check=False)


def test_code_without_tests_is_refused_and_says_how_to_proceed(repo):
    r, log = repo
    (r / "lib" / "a.py").write_text("x = 2\n")
    p = commit(r, "change x")
    assert p.returncode != 0 and "No-test-reason:" in p.stderr and "lib/a.py" in p.stderr


def test_code_with_a_test_commits(repo):
    r, log = repo
    (r / "lib" / "a.py").write_text("x = 2\n")
    (r / "lib" / "tests" / "test_a.py").write_text("def test_a():\n    assert True\n")
    git(r, "add", "-A")
    assert commit(r, "change x with a test").returncode == 0


def test_a_stated_reason_lets_it_through_and_is_logged(repo):
    r, log = repo
    (r / "lib" / "a.py").write_text("x = 2\n")
    assert commit(r, "tune x\n\nNo-test-reason: constant tuned from live data, behaviour unchanged").returncode == 0
    row = json.loads(log.read_text().splitlines()[-1])
    assert row["kind"] == "reason" and "constant tuned" in row["reason"] and "lib/a.py" in row["files"]


def test_empty_or_filler_reasons_do_not_count(repo):
    r, log = repo
    (r / "lib" / "a.py").write_text("x = 2\n")
    for bad in ("No-test-reason:", "No-test-reason: ", "No-test-reason: tbd", "No-test-reason: n/a", "No-test-reason: -"):
        assert commit(r, f"change\n\n{bad}").returncode != 0, bad


def test_the_reason_must_be_its_own_line_not_buried_in_a_sentence(repo):
    r, log = repo
    (r / "lib" / "a.py").write_text("x = 2\n")
    assert commit(r, "change x (No-test-reason: sneaky)").returncode != 0


def test_docs_and_config_only_commit_freely(repo):
    r, log = repo
    (r / "docs" / "x.md").write_text("# x\n")
    git(r, "add", "-A")
    assert commit(r, "docs").returncode == 0


def test_auto_sync_is_never_blocked_but_is_logged(repo):
    r, log = repo
    (r / "lib" / "a.py").write_text("x = 3\n")
    assert commit(r, "auto-sync (mac): 1 file(s) changed", env={"MARVIN_COMMIT_KIND": "auto-sync"}).returncode == 0
    row = json.loads(log.read_text().splitlines()[-1])
    assert row["kind"] == "auto-sync" and "lib/a.py" in row["files"]


def test_merge_and_cherry_pick_commits_are_not_rechecked(repo):
    r, log = repo
    git(r, "checkout", "-q", "-b", "side")
    (r / "lib" / "a.py").write_text("x = 5\n")
    assert commit(r, "side\n\nNo-test-reason: fixture").returncode == 0
    git(r, "checkout", "-q", "main")
    (r / "docs" / "y.md").write_text("y\n"); git(r, "add", "-A"); commit(r, "main docs")
    assert git(r, "merge", "-q", "--no-ff", "side", "-m", "merge side", check=False).returncode == 0
    git(r, "checkout", "-q", "-b", "other", "HEAD~1")
    assert git(r, "cherry-pick", "side", check=False).returncode == 0


def test_a_non_ascii_message_works(repo):
    r, log = repo
    (r / "lib" / "a.py").write_text("x = 2\n")
    assert commit(r, "änderung ✓\n\nNo-test-reason: Kosmetik, Verhalten gleich").returncode == 0


def test_an_unwritable_log_never_blocks_a_commit_that_has_a_reason(repo, monkeypatch, tmp_path):
    r, _ = repo
    monkeypatch.setenv("MARVIN_TEST_SKIP_LOG", str(tmp_path / "no" / "such" / "dir" / "x.jsonl"))
    (tmp_path / "no").write_text("a file where a folder should be")
    (r / "lib" / "a.py").write_text("x = 2\n")
    assert commit(r, "x\n\nNo-test-reason: logged elsewhere").returncode == 0


def test_an_existing_foreign_commit_msg_hook_is_not_clobbered(tmp_path):
    r = tmp_path / "r"
    r.mkdir()
    git(r, "init", "-q")
    hook = r / ".git" / "hooks" / "commit-msg"
    hook.write_text("#!/bin/sh\necho theirs\n")
    assert cc.install_hook(r) == "skipped: a different commit-msg hook is already installed"
    assert hook.read_text() == "#!/bin/sh\necho theirs\n"
    assert cc.install_hook(r, force=False) .startswith("skipped")


def test_installing_twice_is_harmless(repo):
    r, _ = repo
    assert cc.install_hook(r) == "already installed"
