#!/usr/bin/env python3
"""Two-machine coordination for the MR pipeline (G-Eskayo/marvin#8).

Extends ticket_claim.py (#7) without modifying it -- its claim_next_ticket
and queue-depth-cap behavior are unchanged. The real race this module
defends against: ticket_claim's add_claim_label is a GitHub label ADD, not
a compare-and-swap. If both machines' claim cycles run close enough
together, both `list_unclaimed_ready()` calls can see a ticket as
unclaimed before either has written its label, and *both* add_claim_label
calls can succeed -- leaving the issue with two different claimed:*
labels and both machines believing they own it. That's the collision to
detect and resolve, not a rejected write.

**Primary defense (deployment-level, not testable in isolation here)**:
the two machines' claim cron jobs should run on a fixed, non-overlapping
time offset -- not random jitter -- so the common case never collides in
the first place. MACHINE_CRON_OFFSETS below is the reference config a
future launchd install step reads; this module can't prove real-world
cron timing from a unit test, only the tiebreak logic for when the
offset isn't enough.

**Residual defense**: after a successful claim, check whether more than
one claimed:* label now exists on the ticket. If so, a deterministic
tiebreak (alphabetically-earlier hostname wins) picks one winner; the
loser calls ticket_claim.release() -- the existing primitive, not new
release machinery, per the ticket's own explicit instruction.

"Best task for this machine" stays priority-order-plus-queue-depth (#7's
existing behavior, untouched) -- the two known machines aren't capability-
differentiated for this kind of work. task_dispatch's explicit-target-
override remains the escape hatch if a genuinely different-capability
machine joins later; not built here.
"""
from __future__ import annotations
import json
import subprocess
import sys
from pathlib import Path
from typing import Callable

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ticket_claim  # noqa: E402

REPO = ticket_claim.REPO

# Reference config for a future launchd install step -- not enforced by this
# module, since real cron scheduling can't be proven from a unit test.
MACHINE_CRON_OFFSETS = {
    "mac-mini": 0,
    "macbook-pro": 120,
}


def _default_list_claim_labels(issue_number: int) -> list[str]:
    result = subprocess.run(
        ["gh", "issue", "view", str(issue_number), "--repo", REPO, "--json", "labels"],
        capture_output=True, text=True, check=True,
    )
    labels = json.loads(result.stdout)["labels"]
    return [label["name"] for label in labels if label["name"].startswith("claimed:")]


def resolve_collision(
    issue_number: int,
    this_machine_id: str,
    list_claim_labels: Callable[[int], list[str]] | None = None,
    release: Callable[[int, str], None] | None = None,
) -> dict:
    """Check `issue_number` for a same-instant collision (more than one
    claimed:* label) and resolve it deterministically. Returns
    {"collision", "winner", "released"}."""
    list_claim_labels = list_claim_labels or _default_list_claim_labels
    release = release or ticket_claim.release

    claimants = sorted(label.removeprefix("claimed:") for label in list_claim_labels(issue_number))

    if len(claimants) <= 1:
        return {"collision": False, "winner": claimants[0] if claimants else None, "released": False}

    winner = claimants[0]  # alphabetically-earlier hostname wins
    if this_machine_id != winner:
        release(issue_number, this_machine_id)
        return {"collision": True, "winner": winner, "released": True}
    return {"collision": True, "winner": winner, "released": False}


def claim_with_coordination(
    machine_id: str,
    claim: Callable[[str], int | None] | None = None,
    resolve: Callable[[int, str], dict] | None = None,
) -> int | None:
    """Claim via ticket_claim.claim_next_ticket (unchanged), then resolve any
    collision. Returns the issue number this machine actually ends up
    holding after coordination, or None."""
    claim = claim or ticket_claim.claim_next_ticket
    resolve = resolve or resolve_collision

    issue_number = claim(machine_id)
    if issue_number is None:
        return None

    result = resolve(issue_number, machine_id)
    return None if result["released"] else issue_number
