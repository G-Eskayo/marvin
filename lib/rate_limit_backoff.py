#!/usr/bin/env python3
"""Detects Claude Code's own headless usage-limit message and persists a
shared backoff deadline so the ticket pipeline stops re-dispatching into
the same wall every ~30s.

Found live 2026-09-01: ticket #29's `claude -p` planner hit the account's
session limit, and its entire stdout was just the literal string
"You've hit your session limit - resets 4:50pm (America/Denver)".
Nothing distinguished that from a real plan, so it got threaded through
as fake plan/implementation content, the ticket finished its normal
non-passing path, released its claim, and immediately triggered a
redispatch -- which hit the identical limit again about 30 seconds
later, forever, until a human noticed.

The backoff is account-wide, not per-ticket or per-issue: the usage
limit is shared across every ticket a machine could dispatch, so once
one hits it, dispatching should pause entirely until the reset, not just
skip the one ticket that happened to trip it first.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

STATE_PATH = Path.home() / ".claude" / "rate-limit-backoff.json"

# A small buffer past the exact reset avoids racing the reset instant --
# dispatching in the same second the limit clears is as likely to lose
# that race as win it.
_RESET_BUFFER = timedelta(minutes=1)

_RESET_RE = re.compile(
    r"session limit.*?resets\s+(\d{1,2}):(\d{2})\s*([ap]m)\s*\(([^)]+)\)",
    re.IGNORECASE | re.DOTALL,
)


class RateLimited(Exception):
    """Raised by an executor when Claude Code's own headless output is a
    usage-limit message rather than real plan/implementation content."""

    def __init__(self, backoff_until: datetime, text: str):
        self.backoff_until = backoff_until
        super().__init__(f"rate-limited, backing off until {backoff_until.isoformat()}: {text.strip()[:200]}")


def parse_reset_time(text: str, *, now: datetime | None = None) -> datetime | None:
    """Extract an absolute UTC datetime from a message like "You've hit
    your session limit - resets 4:50pm (America/Denver)". Returns None
    for anything that doesn't match. The message carries no date, only a
    wall-clock time in a named zone, so this resolves to the next future
    occurrence of that time (today if still ahead of `now`, otherwise
    tomorrow) -- correct as long as the gap between detecting the
    message and consuming its deadline never spans a full day, which
    a retry loop firing every ~30s never will."""
    match = _RESET_RE.search(text)
    if match is None:
        return None
    hour_raw, minute_raw, meridiem, tz_name = match.groups()
    hour = int(hour_raw) % 12
    if meridiem.lower() == "pm":
        hour += 12
    minute = int(minute_raw)

    try:
        tz = ZoneInfo(tz_name.strip())
    except Exception:
        tz = timezone.utc

    now = now or datetime.now(timezone.utc)
    local_now = now.astimezone(tz)
    candidate = local_now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if candidate <= local_now:
        candidate += timedelta(days=1)
    return candidate.astimezone(timezone.utc)


def is_rate_limit_text(text: str) -> bool:
    return bool(re.search(r"session limit", text, re.IGNORECASE))


def record_backoff(text: str, *, now: datetime | None = None) -> datetime | None:
    """If `text` looks like a Claude Code usage-limit message, persist its
    reset time (plus a small buffer) as the shared backoff deadline and
    return it. No-op (returns None, writes nothing) for anything else."""
    reset_at = parse_reset_time(text, now=now)
    if reset_at is None:
        return None

    backoff_until = reset_at + _RESET_BUFFER
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps({
        "backoff_until": backoff_until.isoformat(),
        "detected_at": (now or datetime.now(timezone.utc)).isoformat(),
        "source_text": text.strip()[:200],
    }))
    return backoff_until


def active_backoff(*, now: datetime | None = None) -> datetime | None:
    """Returns the recorded backoff deadline if one exists and is still in
    the future, else None. Self-cleans an expired file so a stale
    deadline can never linger and get misread as still active later."""
    if not STATE_PATH.exists():
        return None
    try:
        data = json.loads(STATE_PATH.read_text())
        backoff_until = datetime.fromisoformat(data["backoff_until"])
    except Exception:
        return None

    now = now or datetime.now(timezone.utc)
    if backoff_until <= now:
        STATE_PATH.unlink(missing_ok=True)
        return None
    return backoff_until
