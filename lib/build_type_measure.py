#!/usr/bin/env python3
"""Build-type ticket measure() for sandbox_orchestration.execute_ticket
(G-Eskayo/marvin#90).

A build-type ticket (a new feature/tab/flag with no prior baseline to
tune -- see CONTEXT.md's "Build-type ticket" glossary entry) has no real
metric to improve, unlike a tunable-subsystem ticket. `measure()` here
feeds metrics_registry.compare()'s existing interface a mechanical
pass/fail-style signal instead: the fraction of the relevant test suite
that passes, so "improved" means "more tests pass than before" (0 ->
partial -> 1.0), not a fabricated tunable metric.

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


def _touches_dashboard(worktree_path: Path, base_branch: str = "main") -> bool:
    result = subprocess.run(
        ["git", "diff", "--name-only", f"{base_branch}...HEAD"],
        cwd=worktree_path, capture_output=True, text=True,
    )
    return any(f.startswith("dashboard/") for f in result.stdout.splitlines())


def test_command_for(worktree_path: Path, base_branch: str = "main") -> list[str]:
    """Which test command matches what this ticket's diff actually
    touches, scoped rather than always running the entire repo's tests.
    A single list (not a (command, cwd) pair) so this composes directly
    with capture_test_results's cwd=worktree_path-always signature --
    the dashboard case cd's internally via a wrapped shell command."""
    if _touches_dashboard(worktree_path, base_branch):
        return ["bash", "-c", "cd dashboard && npx vitest run"]
    return [VENV_PYTHON, "-m", "pytest", "-q"]


def measure(worktree_path: Path) -> dict:
    """metrics_registry.compare()-shaped measure() for build-type
    tickets. Returns {"tests_passing": {"value", "higher_is_better"}} --
    value is the passing fraction (0.0 when nothing recognizable ran),
    so a comparison from failing/absent to passing shows as "improved"
    through metrics_registry's existing, unmodified compare() logic."""
    command = test_command_for(worktree_path)
    parsed = capture_test_results(worktree_path, command)
    total = parsed.get("total")
    value = (parsed["passed"] / total) if total else 0.0
    return {"tests_passing": {"value": value, "higher_is_better": True}}
