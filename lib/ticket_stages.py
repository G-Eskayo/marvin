#!/usr/bin/env python3
"""Per-ticket pipeline stage events (G-Eskayo/marvin#113-117's Activity tab
scope, extended per Gil's 2026-10-01 ask: record *history*, not just live
status, so stage failures become queryable data for self-improvement
instead of something that has to be forensically re-traced by hand each
time -- exactly what finding PR #119's real failure point required before
this existed).

One JSON file per ticket: ~/.claude/logs/ticket-stages/<n>.json, an
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

VALID_STAGES = {"claimed", "planning", "executing", "verifying", "gate", "merging", "rebuilding", "done"}
VALID_STATUSES = {"started", "passed", "failed"}


def _stage_file(ticket_number: int) -> Path:
    return STAGES_DIR / f"{ticket_number}.json"


def record_stage(
    ticket_number: int, stage: str, status: str, detail: str = "",
    machine: str | None = None, cost_usd: float | None = None,
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
    }
    path = _stage_file(ticket_number)
    path.parent.mkdir(parents=True, exist_ok=True)
    events = read_stages(ticket_number)
    events.append(event)
    path.write_text(json.dumps(events, indent=2))
    return event


def read_stages(ticket_number: int) -> list[dict]:
    path = _stage_file(ticket_number)
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return []


def list_tracked_tickets() -> list[int]:
    if not STAGES_DIR.exists():
        return []
    numbers = []
    for p in STAGES_DIR.glob("*.json"):
        try:
            numbers.append(int(p.stem))
        except ValueError:
            continue
    return sorted(numbers)
