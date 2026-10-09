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
import time
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import marvin_launcher
import metrics_registry as mr
import test_change_rule  # noqa: E402
import code_review_gate  # noqa: E402
import project_profile as pp
import ticket_stages as ts

WORKTREES_ROOT = Path.home() / ".agents-pipeline-worktrees"

FLAGSHIP_MODEL = "claude-sonnet-5"
HAIKU_MODEL = "claude-haiku-4-5-20251001"
# Measured 2026-10-05 over 41 real planning calls: finished ones took 85-298s, many at 255-298s, and 8 hit the
# old 300s wall (about 1 in 5 died for being slow, not wrong). Time costs nothing here; tokens do, so be generous.
PLAN_TIMEOUT_S = 900
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
_PLAN_ALLOWED_TOOLS = ",".join(["Read", "Grep", "Glob", *pp.READ_ONLY_INSPECTION_TOOLS])
# Worktrees live in ~/.agents-pipeline-worktrees, a sibling of ~/.agents (not
# under it), so denying ~/.agents/** blocks writes to the real checkout without
# touching the executor's own worktree. Edit/Write were previously allowlisted
# with no path scope and a live probe showed an absolute-path write succeed
# (#41's executor copied lib/s2_client.py into the real checkout).
WORKTREES_DIR_NAME = ".agents-pipeline-worktrees"
_EXEC_DISALLOWED_TOOLS = "Write(~/.agents/**),Edit(~/.agents/**)"
_EXEC_ALLOWED_TOOLS = (
    "Read,Edit,Write,"
    + ",".join(pp.READ_ONLY_INSPECTION_TOOLS) + ","
    "Bash(~/.agents/venv/bin/python -m pytest*),"
    # A real live-fire dispatch (G-Eskayo/marvin#21) found the executor
    # naturally reaches for bare `pytest`/`python -m pytest` for its own
    # self-verification, not only the venv's fully-qualified form -- only
    # allowlisting one exact invocation left it stuck asking a question
    # nobody headless is present to answer.
    "Bash(pytest*),Bash(python -m pytest*),Bash(python3 -m pytest*),"
    "Bash(npm test*),Bash(npm install*),Bash(npx vitest run*)"
)


def _launch(kind: str, prompt: str, *, ticket_ref: str, **kwargs) -> tuple[str, float]:
    """Every model run this module makes goes through the MARVIN launcher (ADR 0059, marvin#302), which
    adds the kind's layers of MARVIN context, resolves the claude binary, and records the run with its
    real cost and tokens. Returns (result_text, cost_usd) for ticket_stages' per-stage cost field."""
    result = marvin_launcher.launch(kind, prompt, ticket=ticket_ref, **kwargs)
    return result.text, result.cost_usd


def _default_executor(worktree_path: Path, ticket_ref: str, feedback: dict | None, profile: dict | None = None,
                      clone: Path | None = None, env: dict | None = None) -> str:
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
    _preflight_worktree(worktree_path, ticket_ref)
    autonomy_note = (
        f"Your shell starts in {worktree_path}, this ticket's own git worktree (checked before you were launched). "
        "You are operating fully autonomously and headlessly -- there is no "
        "human present to answer questions, grant additional permissions, or "
        "confirm judgment calls. If existing code already satisfies this "
        "ticket, say so plainly in your plan and act on that rather than "
        "pausing to ask for confirmation; if something is genuinely "
        "ambiguous, make the most reasonable call yourself and note it. "
        # #277: refused shell habits were 25% of all headless refusals.
        "Since you are already there, never prefix commands with `cd <dir> &&` "
        "(it makes allowed commands get refused). Use the Read, Glob and Grep tools to look at files "
        "and folders, not ls/find/cat/grep in Bash; Glob lists a directory, Read can't open one. "
        "Read-only `graphify query`, `gh` (view/list/diff) and `git` (log/diff/show/blame) are allowed."
    )
    # A project profile (project_profile.py) replaces marvin's assumptions: its own notes, its own leash.
    project_notes = ""
    if profile is not None:
        import project_profile as pp
        notes = pp.executor_notes(profile)
        project_notes = f"\n\nProject notes:\n{notes}" if notes else ""
    # `gh issue view owner/repo#17` is rejected by gh; the working form names the repo with --repo.
    m = re.fullmatch(r"([\w.-]+/[\w.-]+)#(\d+)", ticket_ref)
    view = f"gh issue view {m.group(2)} --repo {m.group(1)}" if m else f"gh issue view {ticket_ref}"
    plan_prompt = (
        f"{autonomy_note}{project_notes}\n\n"
        f"Read GitHub issue {ticket_ref} ({view}) and produce a "
        f"concise, concrete implementation plan covering its 'What to build' section "
        f"and every acceptance criterion. Also read its comments ({view} --comments): "
        f"any denial feedback or earlier failure notes there are requirements for this attempt. "
        f"Plan only -- do not edit any files yet. "
        f"Before writing the design doc, read the current contents of every file your 'What to build' section and acceptance criteria say you will touch. "
        # marvin#276: the executor sees the north stars only through this section of the plan.
        f"Open the plan with a short '## North-star fit' section, against the north stars above: what it reuses "
        f"before adding anything, why it is the simplest sufficient approach, where it saves or spends tokens, and "
        f"whether it leaves the user more capable. If the ticket states a fit, check it against the code and correct it."
        # ADR 0063: tests try to break it, and come first.
        f" Then list the tests you will write FIRST: one for each case in the ticket's 'How we'll try to break it' "
        f"section (and its Attacks list, if any), plus any misuse the section missed (bad, empty, huge or malformed "
        f"input; each dependency failing; repeats and concurrency; wrong permissions; stale state; a person's "
        f"mistakes). Test against the real collaborator wherever a mock could hide its rules. Verify fails when code "
        f"changes without a test changing."
        # Owner rule 2026-10-09: choices for the owner are never asked in prose (docs/agents/decisions-format.md).
        f" If anything needs the owner to choose (a design option, an open question), do not guess silently and do "
        f"not ask in prose: list it in the plan as a Decisions section in the format of docs/agents/decisions-format.md "
        f"(\"<!-- marvin:decisions -->\", \"### id: question\", \"- [ ]\" options), so the PR can carry it and he answers "
        f"with buttons; a PR that asks in prose can't be approved."
    )

    # Check if a prior design doc exists (true only on iteration ≥2 within one execute_ticket call)
    design_doc_path = _design_doc_path(worktree_path, ticket_ref)
    prior_doc = None
    if design_doc_path.exists():
        prior_doc = design_doc_path.read_text()

    if feedback is not None:
        plan_prompt += (
            f" A previous attempt's metrics comparison came back as: {feedback}. "
            f"Adjust the plan to address this before trying again."
        )
        if isinstance(feedback, dict) and feedback.get("fix_these"):
            plan_prompt += (
                " Code review found these must-fix defects in the previous attempt; fix every one and add a test "
                "that would have caught it:\n" + "\n".join(f"- {f}" for f in feedback["fix_these"])
            )
        if prior_doc is not None:
            plan_prompt += (
                f"\n\nHere is the prior attempt's design doc:\n\n{prior_doc}\n\n"
                f"Write a genuinely revised design doc addressing the failure above — do not repeat the same plan unchanged."
            )
    ticket_number = _parse_ticket_number(ticket_ref)
    plan, plan_cost = _launch(
        "ticket-planner", plan_prompt, ticket_ref=ticket_ref, model=FLAGSHIP_MODEL,
        allowed_tools=_PLAN_ALLOWED_TOOLS, cwd=worktree_path, timeout=PLAN_TIMEOUT_S, env=env,
    )
    _stage(ticket_ref, "executing", "started", "planning call", cost_usd=plan_cost)

    # Write design doc to disk for persistence across iterations and inclusion in PR diff
    design_doc_path.parent.mkdir(parents=True, exist_ok=True)
    design_doc_path.write_text(plan)

    if profile is None:
        import_advice = (
            f"If a new module must import a sibling lib "
            f"module, resolve it relative to __file__ (e.g. Path(__file__).resolve()"
            f".parents[N] / \"lib\"), never via Path.home() / \".agents\" -- that "
            f"points at the real checkout, which does not contain your changes."
        )
        allowed_tools, disallowed_tools = _EXEC_ALLOWED_TOOLS, _EXEC_DISALLOWED_TOOLS
    else:
        import_advice = "Keep every change inside this working tree; the project's real checkout must not be touched."
        allowed_tools, disallowed_tools = pp.executor_tools(profile, clone)
    exec_prompt = (
        f"{autonomy_note}{project_notes} Your job here stops at implementing the plan and "
        f"verifying it locally (edit files, run the relevant tests) -- do NOT "
        f"commit, push, or open a pull request; a separate process handles "
        f"that automatically after you finish, and asking for permission to "
        f"do it yourself will just leave you stuck with no one to grant it. "
        f"Write files only inside your current working directory, never to an "
        f"absolute path elsewhere. {import_advice}\n\n"
        f"Implement this plan in the current working tree:\n\n{plan}"
    )
    _, exec_cost = _launch(
        "ticket-executor", exec_prompt, ticket_ref=ticket_ref, model=HAIKU_MODEL, allowed_tools=allowed_tools,
        disallowed_tools=disallowed_tools or None, cwd=worktree_path, timeout=EXEC_TIMEOUT_S, env=env,
    )
    _stage(ticket_ref, "executing", "passed", "execution call", cost_usd=exec_cost)
    return plan


def _preserve_prior_attempt(repo_path: Path, worktree_path: "Path | list[Path]", branch: str, base_branch: str = "main") -> str | None:
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

    ahead = git("rev-list", "--count", f"origin/{base_branch}..{branch}")
    if ahead.returncode != 0 or not ahead.stdout.strip().isdigit() or int(ahead.stdout.strip()) == 0:
        return None  # no such branch, or nothing beyond origin/main
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    ref = f"refs/rescue/{branch}/{stamp}"
    git("update-ref", ref, branch)
    git("push", "origin", f"{ref}:{ref}")  # best-effort: the local ref is the guarantee
    print(f"[sandbox] preserved prior attempt of {branch} as {ref}", file=sys.stderr)
    return ref


def _branch_for(ticket_ref: str) -> str:
    return f"pipeline/{ticket_ref.lower().replace(' ', '-')}"


def _doc_slug(ticket_ref: str) -> str:
    """Generate a filesystem-safe slug for the design doc, reusing _branch_for's sanitization."""
    return _branch_for(ticket_ref).replace("/", "-").replace("#", "-")


def _design_doc_path(worktree_path: Path, ticket_ref: str) -> Path:
    """Return the path to the design doc for this ticket in the worktree."""
    slug = _doc_slug(ticket_ref)
    return worktree_path / "docs" / "design" / f"{slug}.md"


def _preflight_worktree(worktree_path: Path, ticket_ref: str) -> None:
    """Prove, without any model, that the agent is about to start in this ticket's own worktree. The prompt
    tells the agent where its shell is (Gil, 2026-10-08: "does that mean that they are?"), so the claim must
    be checked, not assumed. Raises before any tokens are spent; the reason travels with the failure."""
    path = Path(worktree_path)
    root = WORKTREES_ROOT.resolve()
    if not path.is_dir():
        raise RuntimeError(f"preflight: {path} does not exist, refusing to launch the agent")
    resolved = path.resolve()
    if root not in resolved.parents:
        raise RuntimeError(f"preflight: {resolved} is outside {root}, refusing to launch the agent in a real clone")
    top = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=path, capture_output=True, text=True)
    if top.returncode != 0 or Path(top.stdout.strip()).resolve() != resolved:
        raise RuntimeError(f"preflight: {resolved} is not a git worktree root ({(top.stderr or top.stdout).strip()[:200]})")
    head = subprocess.run(["git", "symbolic-ref", "--short", "HEAD"], cwd=path, capture_output=True, text=True)
    want = _branch_for(ticket_ref)
    if head.stdout.strip() != want:
        raise RuntimeError(f"preflight: {resolved} is on branch {head.stdout.strip() or '(detached)'}, expected {want}")


def _create_worktree(repo_path: Path, ticket_ref: str, base_branch: str = "main") -> Path:
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
    branch = _branch_for(ticket_ref)
    # No '#' in the DIRECTORY name (the branch keeps it, cleanup_sweep reads the
    # branch): vite/vitest read '#' in a path as a URL fragment and crash, which
    # silently zeroed every pipeline ticket's vitest count. Worktrees created
    # before the rename sit at the old '#' path, so that one is cleaned up too.
    worktree_path = WORKTREES_ROOT / branch.replace("/", "-").replace("#", "-")
    legacy_path = WORKTREES_ROOT / branch.replace("/", "-")
    _fetch_base(repo_path, base_branch)
    _preserve_prior_attempt(repo_path, [worktree_path, legacy_path], branch, base_branch)
    for stale in (worktree_path, legacy_path):
        subprocess.run(["git", "worktree", "remove", "--force", str(stale)], cwd=repo_path, capture_output=True)
    subprocess.run(["git", "branch", "-D", branch], cwd=repo_path, capture_output=True)
    proc = subprocess.run(
        ["git", "worktree", "add", "-b", branch, str(worktree_path), f"origin/{base_branch}"],
        cwd=repo_path, capture_output=True, text=True,
    )
    if proc.returncode != 0:
        # check=True used to hide git's own message behind "exit status 128" (a ticket on the macbook failed that way and
        # nothing said why); the reason has to travel with the failure.
        raise RuntimeError(f"git worktree add failed in {repo_path} (exit {proc.returncode}): {(proc.stderr or '').strip()[-400:]}")
    return worktree_path


def _fetch_base(repo_path: Path, base_branch: str, attempts: int = 2) -> None:
    """Fetch the base branch, retrying once: a transient failure (a lock held by another git process, a
    network blip) used to kill a whole run with no explanation, because check=True hid git's own message."""
    for n in range(1, attempts + 1):
        proc = subprocess.run(["git", "fetch", "origin", base_branch], cwd=repo_path, capture_output=True, text=True)
        if proc.returncode == 0:
            return
        if n < attempts:
            time.sleep(3)
    raise RuntimeError(f"git fetch origin {base_branch} failed after {attempts} tries (exit {proc.returncode}): {(proc.stderr or '').strip()[-300:]}")


def execute_ticket(
    ticket_ref: str,
    subsystem: str,
    measure: Callable[[Path], dict],
    executor: Callable[[Path, str, dict | None], str] | None = None,
    state_setup: Callable[[Path], None] | None = None,
    repo_path: Path | None = None,
    max_iterations: int = 3,
    base_branch: str = "main",
    reviewer: Callable[[Path, str], dict] | None = None,
) -> dict:
    """Drive `ticket_ref` through an isolated worktree and a tune-and-compare
    loop. Returns {"passing", "worktree_path", "iterations", "final_comparison",
    "explanation"}."""
    executor = executor or _default_executor
    repo_path = repo_path or (Path.home() / ".agents")
    ticket_number = _parse_ticket_number(ticket_ref)

    worktree_path = _create_worktree(repo_path, ticket_ref, base_branch)

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
        _stage(ticket_ref, "executing", "started", f"iteration {iteration}/{max_iterations}")
        try:
            executor(worktree_path, ticket_ref, feedback)
        except Exception as exc:
            _stage(ticket_ref, "executing", "failed", str(exc)[:300])
            raise
        _stage(ticket_ref, "executing", "passed", f"iteration {iteration}/{max_iterations}")
        _stage(ticket_ref, "verifying", "started", f"iteration {iteration}/{max_iterations}")

        current = measure(worktree_path)
        comparison = mr.compare(subsystem, baseline, current)

        if comparison["passing"]:
            # ADR 0063 gate 2 (#336): code that changed without a test changing doesn't pass, whatever the metrics say
            tests_ok, why = test_change_rule.check_worktree(worktree_path, base_branch, _test_rules(ticket_ref))
            if not tests_ok:
                comparison = {**comparison, "passing": False, "verdict": "no tests changed", "tests": why}
        if comparison["passing"]:
            # Code review happens here, before a PR exists, so must-fix findings go back to the builder in this
            # run; Approve only checks the PR merges cleanly. A review that can't run doesn't block the build:
            # the PR says it wasn't reviewed.
            review = _review(reviewer or _default_reviewer, worktree_path, base_branch)
            comparison = {**comparison, "code_review": review}
            if review.get("clean") is False:
                comparison = {**comparison, "passing": False, "verdict": "code review found must-fix issues",
                              "fix_these": review.get("findings", [])}
        if comparison["passing"]:
            _stage(ticket_ref, "verifying", "passed", comparison.get("verdict", ""))
            return {
                "passing": True,
                "worktree_path": worktree_path,
                "iterations": iteration,
                "final_comparison": comparison,
                "explanation": None,
            }
        _stage(ticket_ref, "verifying", "failed", comparison.get("verdict", "unchanged"))
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


def _default_reviewer(worktree: Path, base: str) -> dict:
    return code_review_gate.review_worktree(worktree, base)


def _review(reviewer, worktree: Path, base: str) -> dict:
    try:
        review = reviewer(worktree, base)
    except Exception as exc:
        return {"clean": None, "error": f"code review failed to run: {str(exc)[:200]}"}
    if not isinstance(review, dict):
        return {"clean": None, "error": f"code review returned no result ({type(review).__name__})"}
    return review


def _test_rules(ticket_ref: str) -> dict:
    """What counts as code and as tests for this ticket's project (test_change_rule.py)."""
    repo = _ticket_repo(ticket_ref)
    if repo is None:
        return test_change_rule.MARVIN_RULES
    try:
        import project_profile as pp
        return test_change_rule.rules_for_profile(pp.load_profile(repo))
    except Exception:  # noqa: BLE001 -- unreadable profile: the generic rules still apply
        return test_change_rule.rules_for_profile(None)


def _ticket_repo(ticket_ref: str) -> str | None:
    """'G-Eskayo/clarity-captions#7' -> the repo, but None for marvin's (their records keep the plain number)."""
    repo = ticket_ref.rsplit("#", 1)[0] if "/" in ticket_ref and "#" in ticket_ref else None
    return None if repo in (None, "G-Eskayo/marvin") else repo


def _stage(ticket_ref: str, stage: str, status: str, detail: str = "", **kw) -> None:
    number = _parse_ticket_number(ticket_ref)
    if number is None:
        return
    repo = _ticket_repo(ticket_ref)
    ts.record_stage(number, stage, status, detail, **kw, **({"repo": repo} if repo else {}))


def _parse_ticket_number(ticket_ref: str) -> int | None:
    match = re.search(r"#(\d+)$", ticket_ref)
    return int(match.group(1)) if match else None
