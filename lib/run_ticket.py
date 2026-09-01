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
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import machine_profile  # noqa: E402
from build_type_measure import measure, test_command_for  # noqa: E402
from evidence_capture import capture_dev_evidence, capture_test_results, ticket_touches_ui  # noqa: E402
from mr_raiser import raise_mr  # noqa: E402
from rate_limit_backoff import RateLimited  # noqa: E402
from sandbox_orchestration import execute_ticket  # noqa: E402
from ticket_pipeline import _label_for_device, _release  # noqa: E402

REPO = "G-Eskayo/marvin"


def _comment_failure(issue_number: int, reason: str) -> None:
    subprocess.run(
        ["gh", "issue", "comment", str(issue_number), "--repo", REPO, "--body",
         f"Automated implementation did not pass verification: {reason}"],
        check=False,
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
    except RateLimited as exc:
        # The account's session limit, not a real failure of this ticket --
        # found live 2026-09-01: without this, the limit message got
        # threaded through as fake plan/implementation content, and the
        # normal not-raised path below (comment + release + immediate
        # redispatch) turned into a redispatch cascade that re-hit the
        # identical limit every ~30s until a human noticed. The claim still
        # gets released (this ticket is retryable once the backoff clears),
        # but skips the misleading "did not pass verification" issue
        # comment -- ticket_pipeline.py's own backoff check (see
        # active_backoff()) is what actually stops the redispatch loop.
        _release_claim(issue_number)
        _trigger_redispatch()
        return {"raised": False, "pr_url": None,
                "reason": f"Rate-limited -- backing off until {exc.backoff_until.isoformat()}"}
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
        _comment_failure(issue_number, outcome["reason"])
        _release_claim(issue_number)

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
