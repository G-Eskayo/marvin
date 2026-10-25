#!/usr/bin/env python3
"""Job ownership helpers for Mini-primary fallback builds (ADR 0067).

The Mini is the primary machine for research-colony, daily-digest, and
morning-brief. The MacBook builds them only as a fallback, an hour after
the usual time, if the Mini hasn't done so already. This module provides
the checks needed by all three jobs:

- is_primary(): whether this machine should attempt the primary build
- past_deadline(usual_hour, usual_minute, now, tz): whether to skip (primary
  should be done by now)
- mini_output(remote_relpath) -> str | None: fetch the Mini's output over
  SSH and check whether it's real (non-empty, not a quarantine placeholder)
"""
from __future__ import annotations
from datetime import datetime, timedelta, timezone, tzinfo
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from machine_profile import is_stationary, ssh_cat, remote_macs  # noqa: E402


def is_primary() -> bool:
    """This machine is the primary builder iff it's stationary (Mac Mini).
    Reuses the same idiom as cross_machine_merge.py."""
    return is_stationary()


def past_deadline(usual_hour: int, usual_minute: int, now: datetime | None = None,
                  tz: tzinfo | None = None) -> bool:
    """Has the deadline for the primary machine passed?
    Deadline = usual_time + 1 hour. For the MacBook fallback, this tells
    whether to skip (the Mini should have been done by now).

    Args:
        usual_hour: hour (0-23) when the job normally runs
        usual_minute: minute (0-59) when the job normally runs
        now: datetime to check; defaults to current UTC time
        tz: timezone to evaluate the deadline in; defaults to local timezone

    Returns: True if we're past the deadline (after usual_time + 1h local)
    """
    now = now or datetime.now(timezone.utc)
    local_now = now.astimezone(tz)

    # Create datetime for usual time
    usual_dt = local_now.replace(hour=usual_hour, minute=usual_minute, second=0, microsecond=0)

    # If the usual time is in the future and we're in early morning after a late job,
    # the usual time must have been yesterday
    if usual_dt > local_now and usual_hour >= 22 and local_now.hour <= 6:
        usual_dt = usual_dt - timedelta(days=1)

    # Create deadline (1 hour after usual time)
    deadline_dt = usual_dt + timedelta(hours=1)

    # Check if deadline wraps past midnight
    if deadline_dt.day != usual_dt.day:
        # Wrap case: return True if we're past the usual time
        return local_now >= usual_dt
    else:
        # No wrap: return True if we're past the deadline
        return local_now >= deadline_dt


def mini_output(remote_relpath: str) -> str | None:
    """Fetch the Mini's output over SSH, return the content if real.

    Args:
        remote_relpath: relative path under ~/.claude, e.g. "daily-digest/2026-10-25.md"

    Returns:
        File contents if the Mini has real output, None if:
        - the Mini is unreachable or the file doesn't exist
        - the file is empty
    """
    for remote_id, info in remote_macs().items():
        # Only look for machines with kind == "desktop" (Mac Minis)
        if info.get("kind") != "desktop":
            continue
        host = info.get("tailscale_hostname")
        if not host:
            continue

        full_path = f"~/.claude/{remote_relpath}"
        content = ssh_cat(host, full_path, timeout=10)
        if content is None:
            return None

        # Check if it has real content (not empty)
        stripped = content.strip()
        if not stripped:
            return None

        return content

    return None
