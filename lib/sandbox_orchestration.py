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


# ADR 0030: headless `-p` calls have no TTY, so anything not pre-authorized
# hard-denies instead of prompting -- `dontAsk` + an explicit allowlist keeps
# each phase on a tight, auditable leash (not `bypassPermissions`, which
# would also drop protection for file/network access that has nothing to do
# with this repo and would never show up in the eventual PR diff for
# review). git commit/push/`gh pr create` are deliberately absent from
# either list -- those run as plain `subprocess.run()` calls from
# `mr_raiser.py`, not from inside a nested Claude session, so they were
# never subject to this wall to begin with.
_PLAN_ALLOWED_TOOLS = "Read,Grep,Glob,Bash(gh issue view*),Bash(gh issue list*)"
_EXEC_ALLOWED_TOOLS = (
    "Read,Edit,Write,"
    "Bash(git status*),"
    "Bash(~/.agents/venv/bin/python -m pytest*),"
    # A real live-fire dispatch (G-Eskayo/marvin#21) found the executor
    # naturally reaches for bare `pytest`/`python -m pytest` for its own
    # self-verification, not just the venv's fully-qualified form -- only
    # allowlisting one exact invocation left it stuck asking a question
    # nobody headless is present to answer.
    "Bash(pytest*),Bash(python -m pytest*),Bash(python3 -m pytest*),"
    "Bash(npm test*),Bash(npm install*),Bash(npx vitest run*)"
)


def _default_executor(worktree_path: Path, ticket_ref: str, feedback: dict | None) -> str:
    """Real default: a flagship-tier planning call, then a Haiku-tier
    execution call inside the worktree. Mocked in tests -- never invoked
    without an explicit live-fire decision, since it spends real API cost
    and autonomously edits files."""
    # A real live-fire dispatch (G-Eskayo/marvin#21) found this the hard
    # way, twice: (1) without an explicit "you're headless" statement,
    # the planning model reasonably-but-wrongly paused to ask for human
    # confirmation before declaring existing work sufficient -- nobody
    # headless was there to answer, and the "plan" that got passed to the
    # executor was just that unanswered question. (2) the executor got
    # stuck trying to commit/push/open a PR itself and asking for Bash
    # permission to do so, not knowing that's raise_mr's job, done
    # automatically after this function returns -- its own job stops at
    # implementing and locally verifying.
    autonomy_note = (
        "You are operating fully autonomously and headlessly -- there is no "
        "human present to answer questions, grant additional permissions, or "
        "confirm judgment calls. If existing code already satisfies this "
        "ticket, say so plainly in your plan and act on that rather than "
        "pausing to ask for confirmation; if something is genuinely "
        "ambiguous, make the most reasonable call yourself and note it."
    )
    plan_prompt = (
        f"{autonomy_note}\n\n"
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
         "--permission-mode", "dontAsk", "--allowedTools", _PLAN_ALLOWED_TOOLS],
        cwd=worktree_path, capture_output=True, text=True, timeout=PLAN_TIMEOUT_S,
    )
    plan = plan_result.stdout

    exec_prompt = (
        f"{autonomy_note} Your job here stops at implementing the plan and "
        f"verifying it locally (edit files, run the relevant tests) -- do NOT "
        f"commit, push, or open a pull request; a separate process handles "
        f"that automatically after you finish, and asking for permission to "
        f"do it yourself will just leave you stuck with no one to grant it.\n\n"
        f"Implement this plan in the current working tree:\n\n{plan}"
    )
    subprocess.run(
        ["claude", "-p", exec_prompt, "--model", HAIKU_MODEL,
         "--permission-mode", "dontAsk", "--allowedTools", _EXEC_ALLOWED_TOOLS],
        cwd=worktree_path, timeout=EXEC_TIMEOUT_S,
    )
    return plan


def _create_worktree(repo_path: Path, ticket_ref: str) -> Path:
    """Branches explicitly from `origin/main` (fetched fresh first), not
    repo_path's current HEAD -- repo_path is the same shared checkout an
    interactive session might be using at the same moment, possibly on a
    different branch mid-edit. Branching from whatever happens to be
    checked out there would silently start a ticket's work from the wrong
    base and reintroduce exactly the collision risk worktree isolation
    exists to remove (G-Eskayo/marvin#95).

    Force-removes any pre-existing worktree AND branch of the same name
    first. Two different stale states hit this live, both from separate
    real re-dispatches:
    - Ticket #21: `git worktree remove` (used to clean up a finished
      attempt) frees the directory but doesn't delete the branch, and
      `git worktree add -b` refuses to recreate a branch that already
      exists.
    - Ticket #20: the worktree itself was never removed at all -- `git
      branch -D` alone can't free it (git refuses to delete a branch
      checked out in an existing worktree), so `git worktree add -b`
      then fails on the still-existing branch too.
    Safe to discard either way: this branch/worktree is reused only
    across separate attempts at the exact same ticket, a re-dispatch only
    happens once the ticket is unclaimed again (its previous PR
    merged/closed, or it never got far enough to push anything), and
    neither is ever referenced by anything outside this module."""
    WORKTREES_ROOT.mkdir(parents=True, exist_ok=True)
    branch = f"pipeline/{ticket_ref.lower().replace(' ', '-')}"
    worktree_path = WORKTREES_ROOT / branch.replace("/", "-")
    subprocess.run(["git", "fetch", "origin", "main"], cwd=repo_path, check=True, capture_output=True)
    subprocess.run(["git", "worktree", "remove", "--force", str(worktree_path)], cwd=repo_path, capture_output=True)
    subprocess.run(["git", "branch", "-D", branch], cwd=repo_path, capture_output=True)
    subprocess.run(
        ["git", "worktree", "add", "-b", branch, str(worktree_path), "origin/main"],
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
