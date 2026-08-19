#!/usr/bin/env python3
"""Sandbox orchestration for the MR pipeline (G-Eskayo/marvin#3).

Given a ticket, enters an isolated git worktree and drives it through a
tune-and-compare loop against metrics_registry (G-Eskayo/marvin#2) until the
comparison is favorable or max_iterations is exhausted. Stops short of
raising an MR -- that's G-Eskayo/marvin#4's job, which is why this module
deliberately never removes the worktree itself on success: the MR raiser
needs the worktree's branch/commits to still be there.

Worktree management uses real `git worktree` subprocess calls rather than
Claude Code's own EnterWorktree/ExitWorktree tools -- those only exist
inside an interactive Claude Code session's own tool-use loop, but this
module is meant to run headlessly (cron-triggered, no live session), and
worktrees are created in a location outside both the repo tree and Claude
Code's own `.claude/worktrees/` convention so the two mechanisms never
collide or get cleaned up by each other.

`measure`, `executor`, and `state_setup` are all caller-supplied hooks --
this module has no way to know what a given ticket needs measured, how it
should get implemented, or what shared local state (if any) its checks
touch. The default executor shells out to headless `claude -p`: a flagship
model for planning, then Haiku for execution, matching route.py's own
model-tier launch commands and the NetworkChuck/Terry headless-claude
precedent already documented in marvin-roadmap.md.
"""
from __future__ import annotations
import subprocess
from pathlib import Path
from typing import Callable

import metrics_registry as mr

WORKTREES_ROOT = Path.home() / ".agents-pipeline-worktrees"

FLAGSHIP_MODEL = "claude-sonnet-5"
HAIKU_MODEL = "claude-haiku-4-5-20251001"
PLAN_TIMEOUT_S = 300
EXEC_TIMEOUT_S = 900


def _default_executor(worktree_path: Path, ticket_ref: str, feedback: dict | None) -> str:
    """Real default: a flagship-tier planning call, then a Haiku-tier
    execution call inside the worktree. Mocked in tests -- never invoked
    without an explicit live-fire decision, since it spends real API cost
    and autonomously edits files."""
    plan_prompt = (
        f"Read GitHub issue {ticket_ref} (gh issue view {ticket_ref}) and produce a "
        f"concise, concrete implementation plan covering its 'What to build' section "
        f"and every acceptance criterion. Plan only -- do not edit any files yet."
    )
    if feedback is not None:
        plan_prompt += (
            f" A previous attempt's metrics comparison came back as: {feedback}. "
            f"Adjust the plan to address this before trying again."
        )
    plan_result = subprocess.run(
        ["claude", "-p", plan_prompt, "--model", FLAGSHIP_MODEL,
         "--allowedTools", "Read,Grep,Glob,Bash(gh issue view*),Bash(gh issue list*)"],
        cwd=worktree_path, capture_output=True, text=True, timeout=PLAN_TIMEOUT_S,
    )
    plan = plan_result.stdout

    exec_prompt = f"Implement this plan in the current working tree:\n\n{plan}"
    subprocess.run(
        ["claude", "-p", exec_prompt, "--model", HAIKU_MODEL,
         "--permission-mode", "acceptEdits"],
        cwd=worktree_path, timeout=EXEC_TIMEOUT_S,
    )
    return plan


def _create_worktree(repo_path: Path, ticket_ref: str) -> Path:
    WORKTREES_ROOT.mkdir(parents=True, exist_ok=True)
    branch = f"pipeline/{ticket_ref.lower().replace(' ', '-')}"
    worktree_path = WORKTREES_ROOT / branch.replace("/", "-")
    subprocess.run(
        ["git", "worktree", "add", "-b", branch, str(worktree_path)],
        cwd=repo_path, check=True, capture_output=True,
    )
    return worktree_path


def execute_ticket(
    ticket_ref: str,
    subsystem: str,
    measure: Callable[[Path], dict],
    executor: Callable[[Path, str, dict | None], str] | None = None,
    state_setup: Callable[[Path], None] | None = None,
    repo_path: Path | None = None,
    max_iterations: int = 3,
) -> dict:
    """Drive `ticket_ref` through an isolated worktree and a tune-and-compare
    loop. Returns {"passing", "worktree_path", "iterations", "final_comparison",
    "explanation"}."""
    executor = executor or _default_executor
    repo_path = repo_path or (Path.home() / ".agents")

    worktree_path = _create_worktree(repo_path, ticket_ref)

    if state_setup is not None:
        state_setup(worktree_path)

    baseline = measure(worktree_path)
    mr.record(subsystem, baseline)

    feedback = None
    comparison = None
    for iteration in range(1, max_iterations + 1):
        executor(worktree_path, ticket_ref, feedback)
        current = measure(worktree_path)
        comparison = mr.compare(subsystem, baseline, current)

        if comparison["passing"]:
            return {
                "passing": True,
                "worktree_path": worktree_path,
                "iterations": iteration,
                "final_comparison": comparison,
                "explanation": None,
            }
        feedback = comparison

    return {
        "passing": False,
        "worktree_path": worktree_path,
        "iterations": max_iterations,
        "final_comparison": comparison,
        "explanation": (
            f"Did not reach a passing comparison after {max_iterations} iterations "
            f"(max_iterations). Final verdict: {comparison['verdict'] if comparison else 'none'}."
        ),
    }
