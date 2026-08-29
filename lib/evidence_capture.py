#!/usr/bin/env python3
"""Evidence capture for the MR pipeline (G-Eskayo/marvin#72, ADR 0024).

Captures real test-suite results (`capture_test_results`,
G-Eskayo/marvin#76) and, for UI-touching tickets, dev-environment
screenshot evidence (`ticket_touches_ui`/`capture_dev_evidence`,
G-Eskayo/marvin#77).

Kept as its own module rather than folded into
`sandbox_orchestration.execute_ticket`, whose own tune-and-compare-loop
interface and tests stay untouched by this addition: `mr_raiser.raise_mr`
calls into this module directly with the worktree path `execute_ticket`
already returned, rather than `execute_ticket` absorbing capture logic it
has no reason to know about.

`parse_test_output` is split out from `capture_test_results`, and
`ticket_touches_ui` from `capture_dev_evidence`, as pure logic
independently testable without a real subprocess run.
"""
from __future__ import annotations
import re
import subprocess
from pathlib import Path
from typing import Callable


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


# UI-associated path prefixes for dev-evidence gating (ADR 0024). A direct
# check on the diff, not a general classifier -- the one narrow built-in
# exception to "every evidence section always required" in v1.
UI_PATH_PREFIXES = ("dashboard/src/", "dashboard/electron/")


def _is_ui_path(changed_file: str) -> bool:
    return any(changed_file.startswith(prefix) for prefix in UI_PATH_PREFIXES)


def ticket_touches_ui(worktree_path: Path, base_branch: str = "main") -> bool:
    """True if this ticket's diff (against base_branch) includes any file
    under a UI-associated path."""
    result = subprocess.run(
        ["git", "diff", "--name-only", f"{base_branch}...HEAD"],
        cwd=worktree_path, capture_output=True, text=True,
    )
    return any(_is_ui_path(f) for f in result.stdout.splitlines())


def _default_capture_screenshot(worktree_path: Path) -> str:
    """Real default: builds the dashboard and drives it headlessly via
    dashboard/scripts/capture_screenshot.mjs (playwright-core +
    Playwright's _electron launcher -- same pattern as the `run` skill's
    Electron driver examples), saving the screenshot into the worktree
    itself so it rides along in mr_raiser._commit_and_push's existing
    `git add -A` rather than needing a separate upload mechanism. Returns
    the screenshot's path relative to worktree_path, suitable for a
    PR-body markdown image reference."""
    dashboard_dir = worktree_path / "dashboard"
    relative_output = Path("docs") / "evidence" / f"{worktree_path.name}.png"
    output_path = worktree_path / relative_output

    subprocess.run(["npm", "install"], cwd=dashboard_dir, check=True, capture_output=True)
    subprocess.run(["npm", "run", "build"], cwd=dashboard_dir, check=True, capture_output=True)
    subprocess.run(
        ["node", "scripts/capture_screenshot.mjs", str(output_path)],
        cwd=dashboard_dir, check=True, capture_output=True,
    )
    return str(relative_output)


def capture_dev_evidence(
    worktree_path: Path,
    touches_ui: bool,
    capture_screenshot: Callable[[Path], str] | None = None,
) -> dict:
    """For a UI-touching ticket, drive the app headlessly and capture a
    screenshot; for a non-UI ticket, return the explicit N/A case rather
    than a fabricated or omitted one (ADR 0024). Always returns a dict --
    never None -- so mr_raiser's formatting has exactly one shape to
    handle, with `na` distinguishing "legitimately not applicable" from
    a populated result."""
    if not touches_ui:
        return {"na": True, "reason": "no UI"}

    capture_screenshot = capture_screenshot or _default_capture_screenshot
    screenshot_path = capture_screenshot(worktree_path)
    return {
        "na": False,
        "screenshot_path": screenshot_path,
        "description": "Live screenshot captured from the running app.",
    }
