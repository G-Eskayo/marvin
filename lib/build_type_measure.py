#!/usr/bin/env python3
"""Build-type ticket measure() for sandbox_orchestration.execute_ticket
(G-Eskayo/marvin#90).

A build-type ticket (a new feature/tab/flag with no prior baseline to
tune -- see CONTEXT.md's "Build-type ticket" glossary entry) has no real
metric to improve, unlike a tunable-subsystem ticket. `measure()` here
feeds metrics_registry.compare()'s existing interface a mechanical
pass/fail-style signal instead: raw tests_passed/tests_failed counts, so
"improved" means "more tests pass and nothing newly fails" -- not a
fabricated tunable metric, and not a passing fraction either (a fraction
can't tell "added new passing tests to an already-100%-passing suite"
from "nothing changed," both read as 1.0 -> 1.0; a real dispatch,
G-Eskayo/marvin#21, hit exactly this).

Reuses evidence_capture.capture_test_results/parse_test_output (G-Eskayo/
marvin#76) for the actual subprocess-run-and-parse work rather than
re-deriving it -- this module only adds the test-command selection and
the metrics_registry shaping on top.
"""
from __future__ import annotations
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from evidence_capture import capture_test_results  # noqa: E402

VENV_PYTHON = str(Path.home() / ".agents" / "venv" / "bin" / "python")


def _touched_files(worktree_path: Path, base_branch: str = "main") -> list[str]:
    result = subprocess.run(
        ["git", "diff", "--name-only", f"{base_branch}...HEAD"],
        cwd=worktree_path, capture_output=True, text=True,
    )
    return result.stdout.splitlines()


def _touches_dashboard(touched: list[str]) -> bool:
    return any(f.startswith("dashboard/") for f in touched)


def _scope_root(touched_file: str) -> str:
    """One touched file -> the pytest path arg it implies. `skills/` gets
    two path components (skills/paper-dive, not all of skills/ -- that'd
    still pull in every other skill's tests) since it's a shared
    namespace for otherwise-unrelated areas; everything else gets one
    (lib, bench, brain-map, ...)."""
    parts = touched_file.split("/")
    if parts[0] == "skills" and len(parts) > 1:
        return "/".join(parts[:2])
    return parts[0]


def test_command_for(worktree_path: Path, base_branch: str = "main") -> list[str]:
    """Which test command matches what this ticket's diff actually
    touches, scoped rather than always running the entire repo's tests --
    a real live-fire dispatch (G-Eskayo/marvin#21) found this the hard
    way: an unrelated, pre-existing test-collection failure elsewhere in
    the repo made the whole-repo baseline read 0.0, and "fixing" that
    unrelated collection error registered as a false-positive
    "improvement" for a ticket that was never actually implemented.
    A single list (not a (command, cwd) pair) so this composes directly
    with capture_test_results's cwd=worktree_path-always signature --
    the dashboard case cd's internally via a wrapped shell command."""
    touched = _touched_files(worktree_path, base_branch)
    if _touches_dashboard(touched):
        return ["bash", "-c", "cd dashboard && npx vitest run"]

    roots = sorted({_scope_root(f) for f in touched if f})
    existing_roots = [r for r in roots if (worktree_path / r).is_dir()]
    if not existing_roots:
        # Nothing changed, or nothing maps to a real code directory (e.g.
        # docs/adr/*.md-only) -- no scoped target to run, fall back to
        # the whole suite rather than silently running nothing.
        return [VENV_PYTHON, "-m", "pytest", "-q"]
    return [VENV_PYTHON, "-m", "pytest", "-q", *existing_roots]


def measure(worktree_path: Path) -> dict:
    """metrics_registry.compare()-shaped measure() for build-type
    tickets. Returns two separate counts -- tests_passed (higher is
    better) and tests_failed (lower is better) -- rather than one
    passing fraction. A real live-fire dispatch (G-Eskayo/marvin#21)
    found the fraction was blind to a common, legitimate case: a ticket
    that adds new passing tests to an already-100%-passing suite (34/34
    -> 37/37) is still 1.0 -> 1.0, registering as "unchanged" even though
    real, correct work landed. Two counts let metrics_registry.compare()'s
    existing per-metric direction logic see the added passing tests as a
    real improvement, while still catching an actual regression (failed
    count going up) as not passing -- something one fraction can't do."""
    command = test_command_for(worktree_path)
    parsed = capture_test_results(worktree_path, command)
    passed = parsed.get("passed") or 0
    failed = parsed.get("failed") or 0
    return {
        "tests_passed": {"value": passed, "higher_is_better": True},
        "tests_failed": {"value": failed, "higher_is_better": False},
    }
