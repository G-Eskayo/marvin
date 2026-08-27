"""Tests for evidence_capture.py. Run via:
    ~/.agents/venv/bin/python -m pytest lib/tests/test_evidence_capture.py -v
"""
from __future__ import annotations
import subprocess
import sys
from pathlib import Path

import pytest

LIB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LIB))

import evidence_capture as ec  # noqa: E402


# ── parse_test_output (pure parsing, no subprocess) ─────────────────────────

def test_parses_pytest_all_passing():
    result = ec.parse_test_output("pytest", "...........                    [100%]\n11 passed in 2.72s\n")
    assert result == {"suite": "pytest", "passed": 11, "failed": 0, "total": 11}


def test_parses_pytest_with_failures():
    result = ec.parse_test_output("pytest", "FFF........             [100%]\n3 failed, 8 passed in 1.90s\n")
    assert result == {"suite": "pytest", "passed": 8, "failed": 3, "total": 11}


def test_parses_vitest_all_passing():
    output = " Test Files  3 passed (3)\n      Tests  33 passed (33)\n   Duration  354ms\n"
    result = ec.parse_test_output("vitest", output)
    assert result == {"suite": "vitest", "passed": 33, "failed": 0, "total": 33}


def test_parses_vitest_with_failures():
    output = " Test Files  1 failed (3)\n      Tests  30 passed | 3 failed (33)\n"
    result = ec.parse_test_output("vitest", output)
    assert result == {"suite": "vitest", "passed": 30, "failed": 3, "total": 33}


def test_returns_all_none_for_unrecognized_output():
    result = ec.parse_test_output("mystery-runner", "no idea what happened here\n")
    assert result == {"suite": "mystery-runner", "passed": None, "failed": None, "total": None}


def test_suite_label_is_whatever_the_caller_passed_in():
    result = ec.parse_test_output("npm test -- --coverage", "5 passed in 0.5s\n")
    assert result["suite"] == "npm test -- --coverage"


# ── capture_test_results (real subprocess, fake command) ───────────────────

def test_capture_test_results_runs_command_and_parses_stdout(tmp_path):
    result = ec.capture_test_results(tmp_path, ["python3", "-c", "print('7 passed in 0.10s')"])
    assert result == {"suite": "python3 -c print('7 passed in 0.10s')", "passed": 7, "failed": 0, "total": 7}


def test_capture_test_results_runs_inside_the_given_worktree(tmp_path):
    (tmp_path / "marker.txt").write_text("here\n")
    result = ec.capture_test_results(
        tmp_path, ["python3", "-c", "import os; print(len(os.listdir('.')), 'passed in 0.01s')"]
    )
    assert result["passed"] == 1  # only marker.txt is in the empty tmp_path worktree


def test_capture_test_results_handles_a_nonzero_exit_gracefully(tmp_path):
    # A crashing test command (e.g. a real regression) shouldn't raise --
    # it should come back as unparseable rather than blowing up MR raising.
    result = ec.capture_test_results(tmp_path, ["python3", "-c", "import sys; sys.exit(1)"])
    assert result["passed"] is None


# ── ticket_touches_ui (real git diff, no driving) ───────────────────────────

def _run(cmd, cwd):
    subprocess.run(cmd, cwd=cwd, check=True, capture_output=True)


@pytest.fixture
def repo_with_worktree(tmp_path):
    main_repo = tmp_path / "main-repo"
    main_repo.mkdir()
    _run(["git", "init", "-q"], cwd=main_repo)
    _run(["git", "config", "user.email", "test@test.com"], cwd=main_repo)
    _run(["git", "config", "user.name", "Test"], cwd=main_repo)
    (main_repo / "README.md").write_text("hello\n")
    _run(["git", "add", "."], cwd=main_repo)
    _run(["git", "commit", "-q", "-m", "init"], cwd=main_repo)
    _run(["git", "branch", "-M", "main"], cwd=main_repo)

    worktree = tmp_path / "worktree"
    _run(["git", "worktree", "add", "-b", "pipeline/ticket-1", str(worktree)], cwd=main_repo)
    return worktree


def _commit_change(worktree, relative_path, content):
    target = worktree / relative_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content)
    _run(["git", "add", "."], cwd=worktree)
    _run(["git", "commit", "-q", "-m", "change"], cwd=worktree)


def test_touches_ui_true_for_a_dashboard_src_change(repo_with_worktree):
    _commit_change(repo_with_worktree, "dashboard/src/App.jsx", "// change\n")
    assert ec.ticket_touches_ui(repo_with_worktree) is True


def test_touches_ui_true_for_a_dashboard_electron_change(repo_with_worktree):
    _commit_change(repo_with_worktree, "dashboard/electron/main/index.js", "// change\n")
    assert ec.ticket_touches_ui(repo_with_worktree) is True


def test_touches_ui_false_for_a_backend_only_change(repo_with_worktree):
    _commit_change(repo_with_worktree, "lib/some_module.py", "# change\n")
    assert ec.ticket_touches_ui(repo_with_worktree) is False


def test_touches_ui_false_when_nothing_changed(repo_with_worktree):
    assert ec.ticket_touches_ui(repo_with_worktree) is False


def test_touches_ui_true_when_ui_and_backend_both_changed(repo_with_worktree):
    _commit_change(repo_with_worktree, "lib/some_module.py", "# change\n")
    _commit_change(repo_with_worktree, "dashboard/src/App.jsx", "// change\n")
    assert ec.ticket_touches_ui(repo_with_worktree) is True


# ── capture_dev_evidence (injected capture_screenshot, no real driving) ────

def test_capture_dev_evidence_returns_explicit_na_for_a_non_ui_ticket(tmp_path):
    result = ec.capture_dev_evidence(tmp_path, touches_ui=False)
    assert result == {"na": True, "reason": "no UI"}


def test_capture_dev_evidence_does_not_call_capture_screenshot_for_a_non_ui_ticket(tmp_path):
    calls = []
    ec.capture_dev_evidence(
        tmp_path, touches_ui=False, capture_screenshot=lambda p: calls.append(p) or "x.png"
    )
    assert calls == []


def test_capture_dev_evidence_calls_capture_screenshot_for_a_ui_ticket(tmp_path):
    captured = {}

    def fake_capture(worktree_path):
        captured["worktree_path"] = worktree_path
        return "docs/evidence/fake.png"

    result = ec.capture_dev_evidence(tmp_path, touches_ui=True, capture_screenshot=fake_capture)
    assert captured["worktree_path"] == tmp_path
    assert result == {
        "na": False,
        "screenshot_path": "docs/evidence/fake.png",
        "description": "Live screenshot captured from the running app.",
    }
