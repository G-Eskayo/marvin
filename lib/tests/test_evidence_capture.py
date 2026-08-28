"""Tests for evidence_capture.py. Run via:
    ~/.agents/venv/bin/python -m pytest lib/tests/test_evidence_capture.py -v
"""
from __future__ import annotations
import sys
from pathlib import Path

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
