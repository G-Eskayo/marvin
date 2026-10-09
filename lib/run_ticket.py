#!/usr/bin/env python3
"""Drives one ticket through execute_ticket -> raise_mr end to end
(G-Eskayo/marvin#95). This is the actual shell command ticket_pipeline.py
hands to task_dispatch -- split into its own script rather than inlined
into ticket_pipeline.py's dispatch command, since task_dispatch runs an
arbitrary shell command (potentially over SSH on a remote machine), not a
local Python function call.

Run standalone: ~/.agents/venv/bin/python run_ticket.py <issue_number>
"""
from __future__ import annotations
import json
import os
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import functools  # noqa: E402
import machine_profile  # noqa: E402
import project_profile as pp  # noqa: E402
from build_type_measure import measure, test_command_for  # noqa: E402
from evidence_capture import capture_dev_evidence, capture_test_results, ticket_touches_ui, TestTimedOut  # noqa: E402
from mr_raiser import raise_mr  # noqa: E402
from sandbox_orchestration import execute_ticket, _default_executor, TaskListTooVague  # noqa: E402
from cleanup_sweep import drop_build_output  # noqa: E402
from ticket_pipeline import _label_for_device, _release  # noqa: E402
import failure_breaker  # noqa: E402
import ticket_stages as ts  # noqa: E402
import redispatch_trigger  # noqa: E402

REPO = "G-Eskayo/marvin"
FAILURE_MARKER = "Automated implementation did not pass verification"
TIMEOUT_MARKER = "Automated verification timed out"
MAX_CONSECUTIVE_FAILURES = 3


def _comment_failure(issue_number: int, reason: str, repo: str = REPO) -> None:
    subprocess.run(
        ["gh", "issue", "comment", str(issue_number), "--repo", repo, "--body",
         f"{FAILURE_MARKER}: {reason}"],
        check=False,
    )


def _consecutive_failure_streak(issue_number: int, repo: str = REPO) -> int:
    """Count trailing automated-failure comments on this issue, most-recent
    first, stopping at the first non-matching comment (a human reply, a
    passing run, anything else). This is the cross-dispatch retry counter --
    deliberately not a local state file, so both machines agree on it for
    free via the shared issue thread, and a human commenting on the ticket
    (to redirect it, add context, anything) naturally resets the streak.

    Found live 2026-09-04..06: with no cap across separate run_ticket.py
    invocations, a release-claim-then-immediate-redispatch cycle on a
    genuinely-too-ambiguous ticket (#28) spun ~6,900 back-to-back headless
    sessions over 3 days with every attempt reaching an identical
    'unchanged' verdict -- max_iterations=3 only bounds iterations *inside*
    one execute_ticket call, nothing bounded the outer release/redispatch
    loop across calls. Timeouts do not count as failures; only FAILURE_MARKER."""
    proc = subprocess.run(
        ["gh", "issue", "view", str(issue_number), "--repo", repo,
         "--json", "comments"],
        capture_output=True, text=True, timeout=30, check=False,
    )
    if proc.returncode != 0:
        return 0
    try:
        comments = json.loads(proc.stdout)["comments"]
    except (json.JSONDecodeError, KeyError):
        return 0
    streak = 0
    for c in reversed(comments):
        if FAILURE_MARKER in c.get("body", ""):
            streak += 1
        else:
            break
    return streak


def _park_stuck_ticket(issue_number: int, streak: int, repo: str = REPO) -> None:
    label = _label_for_device(machine_profile.registry_id())
    subprocess.run(
        ["gh", "issue", "edit", str(issue_number), "--repo", repo,
         "--remove-label", "ready-for-agent",
         "--remove-label", f"claimed:{label}"],
        capture_output=True, text=True, timeout=15, check=False,
    )
    # The claim is dropped too, not only ready-for-agent: ticket_pipeline only
    # dispatches ready-for-agent tickets with no claimed:* label, so a parked
    # ticket that kept its claim could never be revived by re-adding the label.
    subprocess.run(
        ["gh", "issue", "comment", str(issue_number), "--repo", repo, "--body",
         f"Parking this ticket after {streak} consecutive failed automated "
         f"attempts with no progress -- removed `ready-for-agent` and the "
         f"claim so it stops being re-dispatched. Needs a human look "
         f"(re-scope, do it by hand, or re-add `ready-for-agent` once it's "
         f"less ambiguous) before it's eligible again."],
        capture_output=True, text=True, timeout=15, check=False,
    )


def _release_claim(issue_number: int, repo: str = REPO, run_id: str | None = None) -> None:
    """A ticket that didn't raise a PR -- rate-limited, a worktree-creation
    failure, or genuinely never reached a passing comparison -- leaves this
    machine free again, but ticket_pipeline.py's claim happens before
    dispatch, with no way to know in advance whether the dispatch will
    actually produce anything. Without this, the claimed:<machine> label
    sticks around forever and the ticket is silently starved from ever
    being retried. Found live 2026-08-29: a redispatch cascade during a
    Claude usage-limit window left 28 tickets claimed with zero real work
    done, none of them ever eligible for retry again."""
    label = _label_for_device(machine_profile.registry_id())
    _release(issue_number, label, run_id=run_id) if repo == REPO else _release(issue_number, label, repo, run_id=run_id)


def _trigger_redispatch() -> None:
    """This machine has been free since execute_ticket returned above --
    win or lose, rather than sit idle until the next hourly
    ticket_pipeline.py cron tick, check for more unclaimed work right
    now. Uses redispatch_trigger's debounce so N simultaneous exits
    don't spawn N separate full scans, just one after a short delay.
    Fire-and-forget: ticket_pipeline.py already no-ops safely if
    nothing's unclaimed or no machine is free."""
    redispatch_trigger.request_scan()


def _load_catalog() -> dict:
    try:
        import project_catalog
        return project_catalog.read_catalog(project_catalog.catalog_path()) or {"projects": []}
    except Exception:  # noqa: BLE001 -- the profile's clone_hints still work without a catalog
        return {"projects": []}


def parse_ticket_arg(arg: str) -> tuple[str, int]:
    """'123' (marvin's, as before) or 'owner/repo#123'."""
    m = re.fullmatch(r"([\w.-]+/[\w.-]+)#(\d+)", arg.strip())
    if m:
        return m.group(1), int(m.group(2))
    if arg.strip().isdigit():
        return REPO, int(arg)
    raise ValueError(f"expected a ticket number or owner/repo#number, got {arg!r}")


# marvin has no profile (project_profile.py), so its regenerable build output is listed here; another
# project lists its own under "build_output" in config/projects/<name>.json.
MARVIN_BUILD_OUTPUT = ["dashboard/node_modules"]


def _drop_build_output(worktree_path, profile: dict | None) -> None:
    """A finished run's worktree stays until its PR merges (cleanup_sweep), so drop the build output now:
    found 2026-10-06, 2.1 GiB of SwiftPM .build per clarity worktree. Best effort: never fails the run."""
    if worktree_path is None:
        return
    try:
        drop_build_output(Path(worktree_path), profile.get("build_output", []) if profile else MARVIN_BUILD_OUTPUT)
    except Exception as exc:
        print(f"[run_ticket] could not drop build output in {worktree_path}: {exc}", file=sys.stderr)


def run(issue_number: int, repo: str = REPO) -> dict:
    ticket_ref = f"{repo}#{issue_number}"
    other = repo != REPO
    # marvin's path is called exactly as it always was; another project's calls carry its repo so its
    # stage records, claim label, comments and breaker entries stay its own.
    kw = {"repo": repo} if other else {}
    run_id = os.environ.get("MARVIN_RUN_ID")
    profile = pp.load_profile(repo) if other else None
    subsystem = f"ticket-{issue_number}" if not other else f"{repo.split('/')[-1].lower()}-ticket-{issue_number}"
    measurer = None
    worktree_path = None

    try:
        if other and profile is None:
            outcome = {"raised": False, "pr_url": None, "reason": f"{repo} has no execution profile (config/projects/), so the pipeline cannot run its tickets"}
        else:
            if profile is None:
                result = execute_ticket(ticket_ref, subsystem, measure)
            else:
                clone = pp.resolve_clone(profile, _load_catalog(), ensure=True)
                if clone is None:
                    raise RuntimeError(f"no local clone of {repo} found on this machine (catalog and clone_hints)")
                measurer = pp.Measurer(profile)
                result = execute_ticket(
                    ticket_ref, subsystem, measurer,
                    executor=functools.partial(_default_executor, profile=profile, clone=clone, env=measurer.env),
                    repo_path=clone, base_branch=profile["base_branch"],
                )

            worktree_path = result.get("worktree_path")
            test_results = None
            dev_evidence = None
            if result["passing"]:
                if measurer is None:
                    command = test_command_for(worktree_path)
                    test_results = capture_test_results(worktree_path, command)
                    dev_evidence = capture_dev_evidence(worktree_path, ticket_touches_ui(worktree_path))
                else:
                    test_results, dev_evidence = measurer.evidence(worktree_path)
                    if test_results is not None:
                        test_results["notes"] = measurer.pr_note()

            outcome = raise_mr(ticket_ref, result, test_results=test_results, dev_evidence=dev_evidence)
    except pp.EnvMissing as exc:
        # This machine lacks a tool the project's required check needs. That is about the machine, not the
        # ticket: no comment, no strike, no breaker entry; the claim goes back so a capable machine can take it.
        outcome = {"raised": False, "pr_url": None, "reason": str(exc), "env_missing": True}
    except TestTimedOut as exc:
        # A test or setup step exceeded its timeout: the BUILD MACHINE ran out of time, not the PR's code.
        # Like env_missing, this is not a ticket failure: release the claim, post a timeout comment (for
        # visibility), and redispatch so another machine can try.
        reason = str(exc)
        outcome = {"raised": False, "pr_url": None, "reason": reason, "timed_out": True}
    except TaskListTooVague as exc:
        # The planning call produced a design doc but could not derive a concrete task list. This is a
        # ticket issue (too vague/ambiguous), not a machine or environment issue. Post an explanatory comment
        # and deliberately do NOT release the claim -- it stays claimed so the ticket isn't re-dispatched to
        # spin endlessly. The ticket needs human de-vague-ing before it's eligible again.
        reason = str(exc)
        outcome = {"raised": False, "pr_url": None, "reason": reason, "too_vague": True}
    except Exception as exc:
        # A crash anywhere in execute_ticket/raise_mr (a planner timeout, a
        # worktree-creation failure, anything) must never skip the cleanup
        # below -- found live 2026-08-31: two tickets in a row hit the
        # planner's 300s subprocess timeout, an uncaught exception that
        # crashed the whole process before it ever reached
        # raise_mr/_comment_failure/_release_claim/_trigger_redispatch,
        # leaving both permanently claimed with no way to retry.
        outcome = {"raised": False, "pr_url": None, "reason": f"Unhandled exception: {exc}"}

    _drop_build_output(worktree_path, profile)

    if not outcome["raised"]:
        if outcome.get("env_missing"):
            _release_claim(issue_number, **kw, run_id=run_id)
            ts.record_stage(issue_number, "done", "failed", outcome["reason"][:300], **kw)
            _trigger_redispatch()
            return outcome
        if outcome.get("timed_out"):
            _release_claim(issue_number, **kw, run_id=run_id)
            subprocess.run(
                ["gh", "issue", "comment", str(issue_number), "--repo", repo, "--body",
                 f"{TIMEOUT_MARKER}: {outcome['reason']}"],
                check=False,
            )
            ts.record_stage(issue_number, "verifying", "failed", outcome["reason"][:300], **kw)
            ts.record_stage(issue_number, "done", "failed", outcome["reason"][:300], **kw)
            _trigger_redispatch()
            return outcome
        if outcome.get("too_vague"):
            # Ticket is too vague to plan -- post an explanatory comment, leave the claim in place
            # (do NOT call _release_claim), and trigger a redispatch so other tickets can run.
            subprocess.run(
                ["gh", "issue", "comment", str(issue_number), "--repo", repo, "--body",
                 f"Automated planning could not derive a concrete task list: {outcome['reason']}. "
                 f"This ticket needs human clarification or re-scoping before automated implementation can proceed."],
                check=False,
            )
            ts.record_stage(issue_number, "done", "failed", outcome["reason"][:300], **kw)
            _trigger_redispatch()
            return outcome
        prior_streak = _consecutive_failure_streak(issue_number, **kw)
        _comment_failure(issue_number, outcome["reason"], **kw)
        # Feed the cross-ticket breaker (failure_breaker.py): the SAME failure across
        # different tickets means the system is broken, not the tickets.
        failure_breaker.record_failure(issue_number, outcome["reason"], **({"project": repo} if other else {}))
        if prior_streak + 1 >= MAX_CONSECUTIVE_FAILURES:
            _park_stuck_ticket(issue_number, prior_streak + 1, **kw)
            ts.record_stage(issue_number, "done", "failed", f"parked after {prior_streak + 1} consecutive failures", **kw)
        else:
            _release_claim(issue_number, **kw, run_id=run_id)
            ts.record_stage(issue_number, "done", "failed", outcome["reason"][:300], **kw)
    else:
        ts.record_stage(issue_number, "done", "passed", f"PR raised: {outcome['pr_url']}", **kw)
        failure_breaker.record_success(issue_number, **({"project": repo} if other else {}))  # proves this project's environment works

    _trigger_redispatch()

    return outcome


def main() -> None:
    if len(sys.argv) != 2:
        print("usage: run_ticket.py <issue_number | owner/repo#issue_number>", file=sys.stderr)
        sys.exit(1)
    try:
        repo, number = parse_ticket_arg(sys.argv[1])
    except ValueError as e:
        print(e, file=sys.stderr)
        sys.exit(1)
    outcome = run(number, repo) if repo != REPO else run(number)
    print(outcome)
    sys.exit(0 if outcome["raised"] else 1)


if __name__ == "__main__":
    main()
