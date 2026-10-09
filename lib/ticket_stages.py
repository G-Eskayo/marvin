#!/usr/bin/env python3
"""Per-ticket pipeline stage events (G-Eskayo/marvin#113-117's Activity tab
scope, extended per Gil's 2026-10-01 ask: record *history*, not just live
status, so stage failures become queryable data for self-improvement
instead of something that has to be forensically re-traced by hand each
time -- exactly what finding PR #119's real failure point required before
this existed).

One JSON file per ticket: ~/.claude/logs/ticket-stages/<owner>__<repo>-<n>.json, an
append-only list of {stage, status, detail, timestamp, machine}. Shared
format with webhook-server/ticket_stages.js (Node) -- the merge gate's
rebase/test/merge stages happen in the Node process, planning/executing/
verifying happen here in Python, both write the same file so one timeline
covers a ticket's whole life, not two disconnected halves.

Stages, in pipeline order: claimed, planning, executing, verifying,
gate (rebase+retest, only if behind main), merging, rebuilding, done.
status is one of: started, passed, failed.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import machine_profile  # noqa: E402

STAGES_DIR = Path.home() / ".claude" / "logs" / "ticket-stages"

VALID_STAGES = {"claimed", "planning", "executing", "verifying", "gate", "mutation", "merging", "versioning", "rebuilding", "done"}
VALID_STATUSES = {"started", "passed", "failed"}


MARVIN_REPO = "G-Eskayo/marvin"
# Keys are lowercased, so the owner's real spelling is restored from here when a key is read back.
KNOWN_OWNERS = {"g-eskayo": "G-Eskayo"}


def stage_key(repo: str | None, ticket_number: int) -> str:
    """`<owner>__<repo>-<n>`, lowercased (#216): #7 in clarity-captions is not #7 in marvin, and `__` keeps the key
    readable back even though the owner itself contains a hyphen. repo None means marvin."""
    owner, name = (repo or MARVIN_REPO).lower().split("/")
    return f"{owner}__{name}-{ticket_number}"


def parse_stage_key(stem: str) -> tuple[str, int] | None:
    """The inverse of stage_key, plus marvin's old bare-number files. None for anything else."""
    if stem.isdigit():
        return MARVIN_REPO, int(stem)
    owner, sep, rest = stem.partition("__")
    name, dash, number = rest.rpartition("-")
    if not (sep and dash and number.isdigit()):
        return None
    repo = f"{KNOWN_OWNERS.get(owner, owner)}/{name}"
    return (MARVIN_REPO if repo.lower() == MARVIN_REPO.lower() else repo), int(number)


def _is_marvin(repo: str | None) -> bool:
    return repo is None or repo.lower() == MARVIN_REPO.lower()


def _stage_file(ticket_number: int, repo: str | None = None) -> Path:
    return STAGES_DIR / f"{stage_key(repo, ticket_number)}.json"


def _legacy_file(ticket_number: int, repo: str | None) -> Path | None:
    """marvin's tickets used to be saved by bare number; until migrate_ticket_stages.py has run, read those too."""
    return STAGES_DIR / f"{ticket_number}.json" if _is_marvin(repo) else None


def record_stage(
    ticket_number: int, stage: str, status: str, detail: str = "",
    machine: str | None = None, cost_usd: float | None = None, title: str | None = None,
    repo: str | None = None, run_id: str | None = None,
) -> dict:
    if stage not in VALID_STAGES:
        raise ValueError(f"unknown stage: {stage!r} (expected one of {sorted(VALID_STAGES)})")
    if status not in VALID_STATUSES:
        raise ValueError(f"unknown status: {status!r} (expected one of {sorted(VALID_STATUSES)})")

    event = {
        "stage": stage,
        "status": status,
        "detail": detail,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "machine": machine or machine_profile.registry_id(),
        # Per-call cost in USD, from claude -p's own reported
        # total_cost_usd (Gil's 2026-10-01 ask: usage visibility alongside
        # Health/Metrics, not a separate subsystem) -- None, not 0.0, for
        # stages that don't involve an LLM call at all (claimed, merging),
        # so a sum over a ticket's events doesn't quietly undercount by
        # treating "no call made" the same as "call cost nothing."
        "cost_usd": cost_usd,
        # Found live 2026-10-01: a bare ticket number is opaque in any UI
        # or conversation -- Gil lost track of which ticket "#97" even was
        # mid-handoff. Only ever needs to be set once (claimed, the first
        # event, is where ticket_pipeline.py already has the title from
        # GitHub) -- readers take it from whichever event in a ticket's
        # timeline has it, not every event.
        "title": title,
        # Run id for claim ownership -- allows stale runs to avoid releasing
        # another run's claim. Included even when None so it's consistently
        # present in the event dict, but only checked/compared when non-None.
        "run_id": run_id,
    }
    path = _stage_file(ticket_number, repo)
    path.parent.mkdir(parents=True, exist_ok=True)
    legacy = _legacy_file(ticket_number, repo)
    if legacy and legacy.exists() and not path.exists():
        legacy.rename(path)
    events = read_stages(ticket_number, repo)
    events.append(event)
    path.write_text(json.dumps(events, indent=2))
    return event


def read_stages(ticket_number: int, repo: str | None = None) -> list[dict]:
    path = _stage_file(ticket_number, repo)
    if not path.exists():
        path = _legacy_file(ticket_number, repo)
    if not path or not path.exists():
        return []
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return []


def list_tracked_tickets(repo: str | None = None) -> list[int]:
    if not STAGES_DIR.exists():
        return []
    want = MARVIN_REPO if _is_marvin(repo) else repo
    numbers = set()
    for p in STAGES_DIR.glob("*.json"):
        parsed = parse_stage_key(p.stem)
        if parsed and parsed[0].lower() == want.lower():
            numbers.add(parsed[1])
    return sorted(numbers)


def claim_owner(ticket_number: int, repo: str | None = None) -> str | None:
    """Returns the run_id of the most recent 'claimed' event for this ticket,
    or None if there is no claimed event (legacy data, unreadable file, etc).
    A None result means "no one owns this claim" -> permissive, allowing a
    release without checking. A non-None result means this run_id must match
    the releasing run's id to proceed."""
    stages = read_stages(ticket_number, repo)
    for event in reversed(stages):
        if event.get("stage") == "claimed":
            return event.get("run_id")
    return None
