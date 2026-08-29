"""Tests for build_type_measure.py. Run via:
    ~/.agents/venv/bin/python -m pytest lib/tests/test_build_type_measure.py -v
"""
from __future__ import annotations
import subprocess
import sys
from pathlib import Path

import pytest

LIB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LIB))

import build_type_measure as btm  # noqa: E402


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


# ── test_command_for (real git diff, no test runner invoked) ───────────────

def test_command_for_picks_vitest_for_a_dashboard_change(repo_with_worktree):
    _commit_change(repo_with_worktree, "dashboard/src/App.jsx", "// change\n")
    command = btm.test_command_for(repo_with_worktree)
    assert "vitest" in " ".join(command)


def test_command_for_picks_pytest_for_a_backend_change(repo_with_worktree):
    _commit_change(repo_with_worktree, "lib/some_module.py", "# change\n")
    command = btm.test_command_for(repo_with_worktree)
    assert command == [btm.VENV_PYTHON, "-m", "pytest", "-q"]


def test_command_for_picks_pytest_when_nothing_changed(repo_with_worktree):
    command = btm.test_command_for(repo_with_worktree)
    assert command == [btm.VENV_PYTHON, "-m", "pytest", "-q"]


def test_command_for_picks_vitest_when_both_dashboard_and_backend_changed(repo_with_worktree):
    _commit_change(repo_with_worktree, "lib/some_module.py", "# change\n")
    _commit_change(repo_with_worktree, "dashboard/src/App.jsx", "// change\n")
    command = btm.test_command_for(repo_with_worktree)
    assert "vitest" in " ".join(command)


# ── measure() (injected capture_test_results via monkeypatch) ──────────────

def test_measure_returns_full_value_when_all_tests_pass(monkeypatch, tmp_path):
    monkeypatch.setattr(btm, "capture_test_results", lambda wt, cmd: {
        "suite": "pytest", "passed": 11, "failed": 0, "total": 11,
    })
    result = btm.measure(tmp_path)
    assert result == {"tests_passing": {"value": 1.0, "higher_is_better": True}}


def test_measure_returns_partial_value_when_some_tests_fail(monkeypatch, tmp_path):
    monkeypatch.setattr(btm, "capture_test_results", lambda wt, cmd: {
        "suite": "pytest", "passed": 8, "failed": 3, "total": 11,
    })
    result = btm.measure(tmp_path)
    assert result["tests_passing"]["value"] == pytest.approx(8 / 11)


def test_measure_returns_zero_when_output_is_unparseable(monkeypatch, tmp_path):
    monkeypatch.setattr(btm, "capture_test_results", lambda wt, cmd: {
        "suite": "mystery", "passed": None, "failed": None, "total": None,
    })
    result = btm.measure(tmp_path)
    assert result == {"tests_passing": {"value": 0.0, "higher_is_better": True}}


def test_measure_a_baseline_and_a_current_run_produce_a_real_improvement(monkeypatch, tmp_path):
    # Exercises the actual acceptance criterion: baseline (failing/absent)
    # vs. current (passing) must differ, and metrics_registry.compare()
    # must call that "improved" using this module's shape unmodified.
    sys.path.insert(0, str(LIB))
    import metrics_registry as mr

    monkeypatch.setattr(btm, "capture_test_results", lambda wt, cmd: {
        "suite": "pytest", "passed": None, "failed": None, "total": None,
    })
    baseline = btm.measure(tmp_path)

    monkeypatch.setattr(btm, "capture_test_results", lambda wt, cmd: {
        "suite": "pytest", "passed": 5, "failed": 0, "total": 5,
    })
    current = btm.measure(tmp_path)

    comparison = mr.compare("test-subsystem", baseline, current)
    assert comparison["passing"] is True
    assert comparison["verdict"] == "improved"
