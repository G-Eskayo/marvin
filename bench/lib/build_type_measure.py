"""Measure baseline build characteristics (type checking, linting, tests) for a codebase.

Used to capture metrics before and after running a coding task to determine if the
solution is correct (same type signature, linting, test passes).
"""
from __future__ import annotations
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass
class BuildMeasure:
    """Result of a build/check run."""
    type_check_pass: bool
    type_check_errors: int
    lint_pass: bool
    lint_warnings: int
    tests_pass: bool
    tests_failed: int
    wall_s: float
    error_log: str = ""

    def to_dict(self) -> dict:
        return {
            "type_check_pass": self.type_check_pass,
            "type_check_errors": self.type_check_errors,
            "lint_pass": self.lint_pass,
            "lint_warnings": self.lint_warnings,
            "tests_pass": self.tests_pass,
            "tests_failed": self.tests_failed,
            "wall_s": self.wall_s,
            "error_log": self.error_log,
        }


def measure(workdir: Path, timeout: int = 120) -> BuildMeasure:
    """Run type checking, linting, and tests on a codebase.

    Returns a BuildMeasure with pass/fail status and error counts for each check.
    Errors are logged but don't raise exceptions — allows partial success reporting.
    """
    import time
    start = time.time()
    errors: list[str] = []

    # Type check (mypy)
    type_pass = False
    type_errors = 0
    try:
        result = subprocess.run(
            ["mypy", "."],
            cwd=workdir,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        type_pass = result.returncode == 0
        if not type_pass:
            type_errors = len([l for l in result.stdout.splitlines() if ": error:"])
            errors.append(f"mypy: {type_errors} errors")
    except subprocess.TimeoutExpired:
        errors.append("mypy: timeout")
    except Exception as e:
        errors.append(f"mypy: {e}")

    # Linting (pylint)
    lint_pass = False
    lint_warnings = 0
    try:
        result = subprocess.run(
            ["pylint", ".", "--exit-zero"],  # exit-zero to not fail on warnings
            cwd=workdir,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        lint_pass = result.returncode == 0
        if not lint_pass:
            # Parse pylint output for message count
            for line in result.stdout.splitlines():
                if "warning" in line.lower():
                    lint_warnings += 1
            errors.append(f"pylint: {lint_warnings} warnings")
    except subprocess.TimeoutExpired:
        errors.append("pylint: timeout")
    except Exception as e:
        errors.append(f"pylint: {e}")

    # Tests (pytest)
    tests_pass = False
    tests_failed = 0
    try:
        result = subprocess.run(
            ["pytest", "-q"],
            cwd=workdir,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        tests_pass = result.returncode == 0
        if not tests_pass:
            # Count failed test lines in output
            for line in result.stdout.splitlines():
                if "FAILED" in line:
                    tests_failed += 1
            errors.append(f"pytest: {tests_failed} failed")
    except subprocess.TimeoutExpired:
        errors.append("pytest: timeout")
    except Exception as e:
        errors.append(f"pytest: {e}")

    wall_s = time.time() - start

    return BuildMeasure(
        type_check_pass=type_pass,
        type_check_errors=type_errors,
        lint_pass=lint_pass,
        lint_warnings=lint_warnings,
        tests_pass=tests_pass,
        tests_failed=tests_failed,
        wall_s=wall_s,
        error_log="\n".join(errors),
    )
