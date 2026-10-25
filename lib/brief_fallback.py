#!/usr/bin/env python3
"""Fallback builder logic for morning-brief, daily-digest, and research-colony (marvin#X).

When the primary builder (on the mini) doesn't produce output by a deadline+grace window,
the fallback builder (on the laptop) takes over. This module provides:
- deadline checking (usual_hour:usual_minute + grace_minutes)
- detection of successful output (brief.md / .produced sidecar)
- should_run() matching scanner_role.decide()'s shape: tuple[bool, str]
- remote path reading for health checks and diagnostics
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

__all__ = ["produced", "past_deadline", "should_run"]


def produced(path: Path) -> bool:
    """Has the file been produced (exists, has a .produced sidecar, or was quarantined)?

    Returns True if the file exists with content OR has a .produced sidecar (indicating prior success).
    Also returns True if the file contains quarantine markers (indicating the output was
    already flagged by safety-monitor), since that means a builder did produce something.

    Returns False if the file is empty/whitespace-only (no real output), contains a failure
    placeholder (indicating the builder tried and failed), or doesn't exist.
    """
    if path.exists():
        content = path.read_text(errors="ignore").strip()
        if not content:
            return False
        if "(claude call failed:" in content:
            return False
        if "_Quarantined by safety-monitor" in content:
            return True
        return True

    sidecar = path.parent / f"{path.name}.produced"
    if sidecar.exists():
        return True

    return False


def past_deadline(now: datetime, usual_hour: int, usual_minute: int, grace_minutes: int = 0) -> bool:
    """Is now past the scheduled time + grace window? Checks local time."""
    local_now = now.astimezone()
    deadline = local_now.replace(hour=usual_hour, minute=usual_minute, second=0, microsecond=0)
    if local_now.date() != deadline.date():
        deadline = deadline.replace(day=local_now.day, month=local_now.month, year=local_now.year)
    deadline_with_grace = deadline + timedelta(minutes=grace_minutes)
    return local_now > deadline_with_grace


def should_run(local_path: Path, usual_hour: int, usual_minute: int,
               grace_minutes: int = 60, now: datetime | None = None) -> tuple[bool, str]:
    """(should_run, reason) matching scanner_role.decide()'s shape.

    Returns (True, reason) if past deadline+grace and output not produced.
    Returns (False, reason) if output was already produced or deadline not yet reached.
    """
    now = now or datetime.now(timezone.utc)

    if produced(local_path):
        return False, f"output already produced ({local_path.name})"

    if not past_deadline(now, usual_hour, usual_minute, grace_minutes):
        return False, f"deadline not yet reached ({usual_hour}:{usual_minute:02d} + {grace_minutes}min)"

    return True, f"fallback: primary deadline passed ({usual_hour}:{usual_minute:02d} + {grace_minutes}min)"


