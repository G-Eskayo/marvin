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
from build_type_measure import measure, test_command_for  # noqa: E402
from evidence_capture import capture_dev_evidence, capture_test_results, ticket_touches_ui  # noqa: E402
from mr_raiser import raise_mr  # noqa: E402
from sandbox_orchestration import execute_ticket  # noqa: E402

REPO = "G-Eskayo/marvin"


def _comment_failure(issue_number: int, reason: str) -> None:
    subprocess.run(
        ["gh", "issue", "comment", str(issue_number), "--repo", REPO, "--body",
         f"Automated implementation did not pass verification: {reason}"],
        check=False,
    )


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

    result = execute_ticket(ticket_ref, subsystem, measure)

    test_results = None
    dev_evidence = None
    if result["passing"]:
        worktree_path = result["worktree_path"]
        command = test_command_for(worktree_path)
        test_results = capture_test_results(worktree_path, command)
        dev_evidence = capture_dev_evidence(worktree_path, ticket_touches_ui(worktree_path))

    outcome = raise_mr(ticket_ref, result, test_results=test_results, dev_evidence=dev_evidence)

    if not outcome["raised"]:
        _comment_failure(issue_number, outcome["reason"])

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
