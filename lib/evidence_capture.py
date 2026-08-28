#!/usr/bin/env python3
"""Evidence capture for the MR pipeline (G-Eskayo/marvin#72, ADR 0024).

Captures real test-suite results (`capture_test_results`, this ticket --
G-Eskayo/marvin#76). Dev-environment screenshot evidence for UI-touching
tickets (`capture_dev_evidence`) is G-Eskayo/marvin#77's addition to this
same module -- not built here.

Kept as its own module rather than folded into
`sandbox_orchestration.execute_ticket`, whose own tune-and-compare-loop
interface and tests stay untouched by this addition: `mr_raiser.raise_mr`
calls into this module directly with the worktree path `execute_ticket`
already returned, rather than `execute_ticket` absorbing capture logic it
has no reason to know about.

`parse_test_output` is split out from `capture_test_results` as pure
string-parsing, independently testable against fixture output without a
real subprocess run.
"""
from __future__ import annotations
import re
import subprocess
from pathlib import Path


def parse_test_output(suite: str, output: str) -> dict:
    """Extract pass/fail/total from a test runner's real stdout+stderr.
    Recognizes pytest's summary line ("11 passed in 2.72s",
    "3 failed, 8 passed in 2.72s") and vitest's ("Tests  33 passed (33)",
    "Tests  30 passed | 3 failed (33)"). Returns
    {"suite", "passed", "failed", "total"} with all three None if no
    recognized summary line is found."""
    # vitest's summary line is distinctively prefixed with "Tests" (as
    # opposed to the "Test Files" line above it, which has its own,
    # different pass/fail counts) -- match that whole line first so its
    # counts aren't shadowed by "Test Files"'s.
    vitest_line = re.search(
        r"^\s*Tests\s+(\d+)\s+passed(?:\s*\|\s*(\d+)\s+failed)?\s*\((\d+)\)", output, re.MULTILINE
    )
    if vitest_line:
        passed = int(vitest_line.group(1))
        failed = int(vitest_line.group(2) or 0)
        total = int(vitest_line.group(3))
        return {"suite": suite, "passed": passed, "failed": failed, "total": total}

    passed_match = re.search(r"(\d+)\s+passed", output)
    failed_match = re.search(r"(\d+)\s+failed", output)
    if not passed_match and not failed_match:
        return {"suite": suite, "passed": None, "failed": None, "total": None}

    passed = int(passed_match.group(1)) if passed_match else 0
    failed = int(failed_match.group(1)) if failed_match else 0
    return {"suite": suite, "passed": passed, "failed": failed, "total": passed + failed}


def capture_test_results(worktree_path: Path, test_command: list[str]) -> dict:
    """Run the ticket's real test command inside worktree_path and parse
    its output. `test_command` is caller-supplied (e.g.
    ["pytest", "-q"] or ["npx", "vitest", "run"]) since different
    subsystems use different runners -- this module has no way to know
    which one a given ticket needs."""
    result = subprocess.run(
        test_command, cwd=worktree_path, capture_output=True, text=True,
    )
    return parse_test_output(" ".join(test_command), result.stdout + result.stderr)
