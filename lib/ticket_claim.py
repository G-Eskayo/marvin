#!/usr/bin/env python3
"""Single-machine ticket claim for the MR pipeline (G-Eskayo/marvin#7).

Connects ticket_promotion's (#6) output to sandbox_orchestration's (#3)
input: on a cron trigger, claims the highest-priority unclaimed
`ready-for-agent` ticket -- if this machine is under its queue cap -- and
hands it off for execution.

Claim state lives entirely as a GitHub label (`claimed:<machine_id>`), not
a new local dispatch-state file -- GitHub's API is already the shared,
atomic source of truth both machines can see, unlike task_dispatch.py's
normal case where no such shared truth otherwise exists. Machine identity
reuses machine_profile.machine_label() rather than inventing a new
identifier.

"Priority" for claim ordering is, for now, oldest-issue-number-first --
disclosed simplification, since ticket_promotion.py doesn't yet attach any
explicit priority signal to the tickets it creates. A real priority label
would be a natural follow-on enhancement to #6, not something this module
invents on its own.

`release` is exposed as its own operation, not folded into claim_next_ticket
-- it's reused as-is by the two-machine tiebreak and cleanup sweep modules
(both still to come), so it needs to exist as a standalone primitive now
rather than being extracted later.
"""
from __future__ import annotations
import json
import subprocess
import sys
from pathlib import Path
from typing import Callable

sys.path.insert(0, str(Path(__file__).resolve().parent))
from machine_profile import machine_label  # noqa: E402
from sandbox_orchestration import execute_ticket as _default_execute  # noqa: E402

MAX_QUEUE = 3
REPO = "G-Eskayo/marvin"


def _claim_label(machine_id: str) -> str:
    return f"claimed:{machine_id}"


def _default_list_claimed(machine_id: str) -> list[dict]:
    result = subprocess.run(
        ["gh", "issue", "list", "--repo", REPO, "--state", "open",
         "--label", _claim_label(machine_id), "--json", "number,labels"],
        capture_output=True, text=True, check=True,
    )
    return json.loads(result.stdout)


def _default_list_unclaimed_ready() -> list[dict]:
    result = subprocess.run(
        ["gh", "issue", "list", "--repo", REPO, "--state", "open",
         "--label", "ready-for-agent", "--json", "number,labels,body"],
        capture_output=True, text=True, check=True,
    )
    issues = json.loads(result.stdout)
    return [
        issue for issue in issues
        if not any(label["name"].startswith("claimed:") for label in issue.get("labels", []))
        # to-issues' own template always includes "## Parent"; to-prd's PRD
        # template never does -- real, existing structural signal for "this
        # is an atomic, executable ticket" vs. "this is an overview PRD that
        # was already broken into child tickets and isn't itself AFK work."
        and "## Parent" in (issue.get("body") or "")
    ]


def _default_add_claim_label(issue_number: int, machine_id: str) -> None:
    label = _claim_label(machine_id)
    result = subprocess.run(
        ["gh", "issue", "edit", str(issue_number), "--repo", REPO, "--add-label", label],
        capture_output=True, text=True,
    )
    if result.returncode != 0 and "not found" in (result.stderr or "").lower():
        subprocess.run(["gh", "label", "create", label, "--repo", REPO], capture_output=True, check=True)
        subprocess.run(
            ["gh", "issue", "edit", str(issue_number), "--repo", REPO, "--add-label", label],
            capture_output=True, check=True,
        )
    elif result.returncode != 0:
        result.check_returncode()


def _default_remove_claim_label(issue_number: int, machine_id: str) -> None:
    subprocess.run(
        ["gh", "issue", "edit", str(issue_number), "--repo", REPO,
         "--remove-label", _claim_label(machine_id)],
        capture_output=True, check=True,
    )


def claim_next_ticket(
    machine_id: str,
    list_claimed: Callable[[str], list[dict]] | None = None,
    list_unclaimed_ready: Callable[[], list[dict]] | None = None,
    add_claim_label: Callable[[int, str], None] | None = None,
    max_queue: int = MAX_QUEUE,
) -> int | None:
    """Claim the highest-priority (lowest issue number) unclaimed
    ready-for-agent ticket, if this machine is under its queue cap.
    Returns the claimed issue number, or None if nothing was claimed."""
    list_claimed = list_claimed or _default_list_claimed
    list_unclaimed_ready = list_unclaimed_ready or _default_list_unclaimed_ready
    add_claim_label = add_claim_label or _default_add_claim_label

    if len(list_claimed(machine_id)) >= max_queue:
        return None

    candidates = list_unclaimed_ready()
    if not candidates:
        return None

    chosen = min(candidates, key=lambda issue: issue["number"])
    add_claim_label(chosen["number"], machine_id)
    return chosen["number"]


def release(
    issue_number: int,
    machine_id: str,
    remove_claim_label: Callable[[int, str], None] | None = None,
) -> None:
    """Release a claim this machine holds, so another machine (or a later
    cycle) can pick the ticket up. Reused as-is by the two-machine tiebreak
    and cleanup sweep modules."""
    remove_claim_label = remove_claim_label or _default_remove_claim_label
    remove_claim_label(issue_number, machine_id)


def run_claim_cycle(
    machine_id: str | None = None,
    claim: Callable[[str], int | None] | None = None,
    execute: Callable[[str], dict] | None = None,
) -> dict:
    """Cron entry point: claim a ticket if capacity allows, then hand it to
    sandbox orchestration automatically. Returns {"claimed", "execution_result"}."""
    machine_id = machine_id or machine_label()
    claim = claim or claim_next_ticket
    execute = execute or (lambda ticket_ref: _default_execute(ticket_ref, ticket_ref, measure=lambda wt: {}))

    issue_number = claim(machine_id)
    if issue_number is None:
        return {"claimed": None, "execution_result": None}

    ticket_ref = f"{REPO}#{issue_number}"
    execution_result = execute(ticket_ref)
    return {"claimed": ticket_ref, "execution_result": execution_result}
