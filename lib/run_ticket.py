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
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import machine_profile  # noqa: E402
from build_type_measure import measure, test_command_for  # noqa: E402
from evidence_capture import capture_dev_evidence, capture_test_results, ticket_touches_ui  # noqa: E402
from mr_raiser import raise_mr  # noqa: E402
from sandbox_orchestration import execute_ticket  # noqa: E402
from ticket_pipeline import _label_for_device, _release  # noqa: E402
import ticket_stages as ts  # noqa: E402

REPO = "G-Eskayo/marvin"
FAILURE_MARKER = "Automated implementation did not pass verification"
MAX_CONSECUTIVE_FAILURES = 3


def _comment_failure(issue_number: int, reason: str) -> None:
    subprocess.run(
        ["gh", "issue", "comment", str(issue_number), "--repo", REPO, "--body",
         f"{FAILURE_MARKER}: {reason}"],
        check=False,
    )


def _consecutive_failure_streak(issue_number: int) -> int:
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
    loop across calls."""
    proc = subprocess.run(
        ["gh", "issue", "view", str(issue_number), "--repo", REPO,
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


def _park_stuck_ticket(issue_number: int, streak: int) -> None:
    label = _label_for_device(machine_profile.registry_id())
    subprocess.run(
        ["gh", "issue", "edit", str(issue_number), "--repo", REPO,
         "--remove-label", "ready-for-agent"],
        capture_output=True, text=True, timeout=15, check=False,
    )
    subprocess.run(
        ["gh", "issue", "comment", str(issue_number), "--repo", REPO, "--body",
         f"Parking this ticket after {streak} consecutive failed automated "
         f"attempts with no progress -- removing `ready-for-agent` so it "
         f"stops being re-dispatched. Still labeled `claimed:{label}`; "
         f"needs a human look (re-scope, do it by hand, or re-add "
         f"`ready-for-agent` once it's less ambiguous) before it's "
         f"eligible again."],
        capture_output=True, text=True, timeout=15, check=False,
    )


def _release_claim(issue_number: int) -> None:
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
    _release(issue_number, label)


def _trigger_redispatch() -> None:
    """This machine has been free since execute_ticket returned above --
    win or lose, rather than sit idle until the next hourly
    ticket_pipeline.py cron tick, check for more unclaimed work right
    now. Fire-and-forget: ticket_pipeline.py already no-ops safely if
    nothing's unclaimed or no machine is free, so nothing here needs to
    check first, and a failed scan shouldn't affect this ticket's own
    already-decided outcome."""
    script = Path(__file__).resolve().parent / "ticket_pipeline.py"
    subprocess.Popen(
        [sys.executable, str(script)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
        start_new_session=True,
    )


def run(issue_number: int) -> dict:
    ticket_ref = f"{REPO}#{issue_number}"
    subsystem = f"ticket-{issue_number}"

    try:
        result = execute_ticket(ticket_ref, subsystem, measure)

        test_results = None
        dev_evidence = None
        if result["passing"]:
            worktree_path = result["worktree_path"]
            command = test_command_for(worktree_path)
            test_results = capture_test_results(worktree_path, command)
            dev_evidence = capture_dev_evidence(worktree_path, ticket_touches_ui(worktree_path))

        outcome = raise_mr(ticket_ref, result, test_results=test_results, dev_evidence=dev_evidence)
    except Exception as exc:
        # A crash anywhere in execute_ticket/raise_mr (a planner timeout, a
        # worktree-creation failure, anything) must never skip the cleanup
        # below -- found live 2026-08-31: two tickets in a row hit the
        # planner's 300s subprocess timeout, an uncaught exception that
        # crashed the whole process before it ever reached
        # raise_mr/_comment_failure/_release_claim/_trigger_redispatch,
        # leaving both permanently claimed with no way to retry.
        outcome = {"raised": False, "pr_url": None, "reason": f"Unhandled exception: {exc}"}

    if not outcome["raised"]:
        prior_streak = _consecutive_failure_streak(issue_number)
        _comment_failure(issue_number, outcome["reason"])
        if prior_streak + 1 >= MAX_CONSECUTIVE_FAILURES:
            _park_stuck_ticket(issue_number, prior_streak + 1)
            ts.record_stage(issue_number, "done", "failed", f"parked after {prior_streak + 1} consecutive failures")
        else:
            _release_claim(issue_number)
            ts.record_stage(issue_number, "done", "failed", outcome["reason"][:300])
    else:
        ts.record_stage(issue_number, "done", "passed", f"PR raised: {outcome['pr_url']}")

    _trigger_redispatch()

    return outcome


def main() -> None:
    if len(sys.argv) != 2:
        print("usage: run_ticket.py <issue_number>", file=sys.stderr)
        sys.exit(1)
    outcome = run(int(sys.argv[1]))
    print(outcome)
    sys.exit(0 if outcome["raised"] else 1)


if __name__ == "__main__":
    main()
