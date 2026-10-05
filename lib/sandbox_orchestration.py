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
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import metrics_registry as mr
import ticket_stages as ts

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
# Worktrees live in ~/.agents-pipeline-worktrees, a sibling of ~/.agents (not
# under it), so denying ~/.agents/** blocks writes to the real checkout without
# touching the executor's own worktree. Edit/Write were previously allowlisted
# with no path scope and a live probe showed an absolute-path write succeed
# (#41's executor copied lib/s2_client.py into the real checkout).
WORKTREES_DIR_NAME = ".agents-pipeline-worktrees"
_EXEC_DISALLOWED_TOOLS = "Write(~/.agents/**),Edit(~/.agents/**)"
_EXEC_ALLOWED_TOOLS = (
    "Read,Edit,Write,"
    "Bash(git status*),"
    "Bash(~/.agents/venv/bin/python -m pytest*),"
    # A real live-fire dispatch (G-Eskayo/marvin#21) found the executor
    # naturally reaches for bare `pytest`/`python -m pytest` for its own
    # self-verification, not only the venv's fully-qualified form -- only
    # allowlisting one exact invocation left it stuck asking a question
    # nobody headless is present to answer.
    "Bash(pytest*),Bash(python -m pytest*),Bash(python3 -m pytest*),"
    "Bash(npm test*),Bash(npm install*),Bash(npx vitest run*)"
)


def _run_claude(cmd: list[str], **kwargs) -> tuple[str, float]:
    """Runs a `claude -p ... --output-format json` call and returns
    (result_text, cost_usd). Centralized here (2026-10-01, per Gil's ask
    for usage visibility alongside Health/Metrics) so every claude -p call
    this module makes reports its real cost, not just its text output --
    feeds ticket_stages.py's per-stage cost field, which in turn feeds the
    same metrics_registry anomaly layer the Health tab already uses."""
    proc = subprocess.run(cmd + ["--output-format", "json"], capture_output=True, text=True, **kwargs)
    try:
        parsed = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return proc.stdout, 0.0
    return parsed.get("result", proc.stdout), parsed.get("total_cost_usd", 0.0) or 0.0


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
    # executor was that unanswered question. (2) the executor got
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
        f"and every acceptance criterion. Also read its comments (gh issue view {ticket_ref} --comments): "
        f"any denial feedback or earlier failure notes there are requirements for this attempt. "
        f"Plan only -- do not edit any files yet."
    )
    if feedback is not None:
        plan_prompt += (
            f" A previous attempt's metrics comparison came back as: {feedback}. "
            f"Adjust the plan to address this before trying again."
        )
    ticket_number = _parse_ticket_number(ticket_ref)
    plan, plan_cost = _run_claude(
        ["claude", "-p", plan_prompt, "--model", FLAGSHIP_MODEL,
         "--permission-mode", "dontAsk", "--allowedTools", _PLAN_ALLOWED_TOOLS],
        cwd=worktree_path, timeout=PLAN_TIMEOUT_S,
    )
    if ticket_number is not None:
        ts.record_stage(ticket_number, "executing", "started", "planning call", cost_usd=plan_cost)

    exec_prompt = (
        f"{autonomy_note} Your job here stops at implementing the plan and "
        f"verifying it locally (edit files, run the relevant tests) -- do NOT "
        f"commit, push, or open a pull request; a separate process handles "
        f"that automatically after you finish, and asking for permission to "
        f"do it yourself will just leave you stuck with no one to grant it. "
        f"Write files only inside your current working directory, never to an "
        f"absolute path elsewhere. If a new module must import a sibling lib "
        f"module, resolve it relative to __file__ (e.g. Path(__file__).resolve()"
        f".parents[N] / \"lib\"), never via Path.home() / \".agents\" -- that "
        f"points at the real checkout, which does not contain your changes.\n\n"
        f"Implement this plan in the current working tree:\n\n{plan}"
    )
    _, exec_cost = _run_claude(
        ["claude", "-p", exec_prompt, "--model", HAIKU_MODEL,
         "--permission-mode", "dontAsk", "--allowedTools", _EXEC_ALLOWED_TOOLS,
         "--disallowedTools", _EXEC_DISALLOWED_TOOLS],
        cwd=worktree_path, timeout=EXEC_TIMEOUT_S,
    )
    if ticket_number is not None:
        ts.record_stage(ticket_number, "executing", "passed", "execution call", cost_usd=exec_cost)
    return plan


def _preserve_prior_attempt(repo_path: Path, worktree_path: "Path | list[Path]", branch: str) -> str | None:
    """Before a re-dispatch discards a ticket's old worktree and branch, keep
    anything unique they hold: commit uncommitted changes onto the branch, then,
    if the branch has commits beyond origin/main, pin them under
    refs/rescue/<branch>/<utc-timestamp> (local ref, best-effort push to origin
    so it also survives the machine). Returns the rescue ref, or None when there
    was nothing worth keeping -- an untouched worktree leaves no noise."""
    def git(*args, cwd=repo_path):
        return subprocess.run(
            ["git", "-c", "user.name=marvin-pipeline", "-c", "user.email=pipeline@marvin.local", *args],
            cwd=cwd, capture_output=True, text=True,
        )

    paths = worktree_path if isinstance(worktree_path, (list, tuple)) else [worktree_path]
    for path in paths:
        if path.exists() and git("status", "--porcelain", cwd=path).stdout.strip():
            git("add", "-A", cwd=path)
            git("commit", "-qm", "WIP preserved before redispatch", cwd=path)

    ahead = git("rev-list", "--count", f"origin/main..{branch}")
    if ahead.returncode != 0 or not ahead.stdout.strip().isdigit() or int(ahead.stdout.strip()) == 0:
        return None  # no such branch, or nothing beyond origin/main
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    ref = f"refs/rescue/{branch}/{stamp}"
    git("update-ref", ref, branch)
    git("push", "origin", f"{ref}:{ref}")  # best-effort: the local ref is the guarantee
    print(f"[sandbox] preserved prior attempt of {branch} as {ref}", file=sys.stderr)
    return ref


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
    NOT safe to discard blindly, despite what this docstring used to claim
    ("a re-dispatch only happens once it never got far enough to push
    anything"): a failed attempt routinely leaves real work behind --
    uncommitted files, committed-but-unpushed commits. Found 2026-10-01 with
    five worktrees across both machines holding unmerged work (a whole new
    skill directory, a partial Files tab, committed bench tests), and #41's own
    first attempt was lost this way. So anything unique the prior attempt
    produced is first preserved under refs/rescue/<branch>/<timestamp> (kept
    locally and pushed to origin), and only then is the old state discarded."""
    WORKTREES_ROOT.mkdir(parents=True, exist_ok=True)
    branch = f"pipeline/{ticket_ref.lower().replace(' ', '-')}"
    # No '#' in the DIRECTORY name (the branch keeps it, cleanup_sweep reads the
    # branch): vite/vitest read '#' in a path as a URL fragment and crash, which
    # silently zeroed every pipeline ticket's vitest count. Worktrees created
    # before the rename sit at the old '#' path, so that one is cleaned up too.
    worktree_path = WORKTREES_ROOT / branch.replace("/", "-").replace("#", "-")
    legacy_path = WORKTREES_ROOT / branch.replace("/", "-")
    subprocess.run(["git", "fetch", "origin", "main"], cwd=repo_path, check=True, capture_output=True)
    _preserve_prior_attempt(repo_path, [worktree_path, legacy_path], branch)
    for stale in (worktree_path, legacy_path):
        subprocess.run(["git", "worktree", "remove", "--force", str(stale)], cwd=repo_path, capture_output=True)
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
    ticket_number = _parse_ticket_number(ticket_ref)

    worktree_path = _create_worktree(repo_path, ticket_ref)

    if state_setup is not None:
        state_setup(worktree_path)

    baseline = measure(worktree_path)
    mr.record(subsystem, baseline)

    feedback = None
    comparison = None
    for iteration in range(1, max_iterations + 1):
        # One event per phase, not per iteration sub-step -- `executor()`
        # covers plan+exec as a single opaque call (see _default_executor's
        # own two nested claude -p calls), so "executing" is the finest
        # grain available without changing that call shape too. Iteration
        # number lives in `detail` so a 3-retry ticket's timeline is still
        # legible, not three indistinguishable "executing" rows.
        if ticket_number is not None:
            ts.record_stage(ticket_number, "executing", "started", f"iteration {iteration}/{max_iterations}")
        try:
            executor(worktree_path, ticket_ref, feedback)
        except Exception as exc:
            if ticket_number is not None:
                ts.record_stage(ticket_number, "executing", "failed", str(exc)[:300])
            raise
        if ticket_number is not None:
            ts.record_stage(ticket_number, "executing", "passed", f"iteration {iteration}/{max_iterations}")
            ts.record_stage(ticket_number, "verifying", "started", f"iteration {iteration}/{max_iterations}")

        current = measure(worktree_path)
        comparison = mr.compare(subsystem, baseline, current)

        if comparison["passing"]:
            if ticket_number is not None:
                ts.record_stage(ticket_number, "verifying", "passed", comparison.get("verdict", ""))
            return {
                "passing": True,
                "worktree_path": worktree_path,
                "iterations": iteration,
                "final_comparison": comparison,
                "explanation": None,
            }
        if ticket_number is not None:
            ts.record_stage(ticket_number, "verifying", "failed", comparison.get("verdict", "unchanged"))
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


def _parse_ticket_number(ticket_ref: str) -> int | None:
    match = re.search(r"#(\d+)$", ticket_ref)
    return int(match.group(1)) if match else None
