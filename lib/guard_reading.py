#!/usr/bin/env python3
"""Guard readable sensors for core dependencies (memory, disk, GitHub quota, Tailscale, pipeline health).

Each guard has a name and a fail mode: "closed" (refuse work if unreadable, treat as failure) or "open" (allow
work, alert loudly). A reading is recorded as one JSON line; episodes are folds of 2–N readings that show the
onset (2 consecutive unreadable, or 1 unreadable + 30 min), recovery (2 consecutive good), and age thresholds
that trigger yellow (30 min) and alert (2 h). Used by health_checks to report guard status and trigger alerts.

Health sweeps episode() every 15 minutes to detect failures that would otherwise go unnoticed for days (#889).
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

LOG_PATH = Path.home() / ".claude" / "logs" / "guard-readings.jsonl"
LOG_MAX_BYTES = 2**20
YELLOW_AFTER_MINUTES = 30
ALERT_AFTER_HOURS = 2

GUARD_TABLE = {
    "disk_local": "closed",
    "disk_remote": "closed",
    "memory": "closed",
    "task_records": "open",
    "peer_state_local": "open",
    "peer_state_remote": "open",
    "tailscale": "open",
    "github_budget": "open",
    "breaker": "open",
    "tools": "open",
}


def guard_reading(name: str, value_or_error: Any) -> Any:
    """Log a reading and return it unchanged, or return None if unreadable. Raises if the guard name doesn't exist."""
    if name not in GUARD_TABLE:
        raise ValueError(f"unknown guard: {name}")

    # Determine if the reading is readable: None or an Exception means unreadable, anything else is readable.
    is_exception = isinstance(value_or_error, BaseException)
    is_unreadable = value_or_error is None or is_exception

    # Log the reading.
    record(name, unreadable=is_unreadable)

    # Return the value (or None if unreadable).
    if is_unreadable:
        return None
    return value_or_error


def record(name: str, unreadable: bool) -> None:
    """One JSON line per reading. Never raises: a log that can't be written must not stop the guard."""
    entry = {"ts": datetime.now(timezone.utc).isoformat(), "guard": name, "ok": not unreadable}
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        if LOG_PATH.exists() and LOG_PATH.stat().st_size > LOG_MAX_BYTES:
            # Keep the newest half, bounded forever (mirrors memory_guard.record).
            lines = LOG_PATH.read_text(errors="replace").splitlines()
            LOG_PATH.write_text("\n".join(lines[len(lines) // 2:]) + "\n")
        with open(LOG_PATH, "a") as f:
            f.write(json.dumps(entry) + "\n")
    except OSError:
        pass


def episodes(now: datetime | None = None) -> dict[str, dict]:
    """Folds the log into episodes: active periods where a guard is unreadable.

    Onset (episode starts): 2 consecutive unreadable readings, OR 1 unreadable reading + 30 min with no recovery.
    Recovery (episode ends): 2 consecutive good readings.
    Returns {guard_name: {"episode_start": datetime, "age_minutes": int, "fail_mode": "open"|"closed"}}.
    Only active (ongoing or alert-worthy) episodes are returned; cleared episodes drop out.
    """
    now = now or datetime.now(timezone.utc)

    try:
        lines = LOG_PATH.read_text(errors="replace").splitlines()
    except OSError:
        lines = []

    # Parse readings in chronological order, skip malformed lines.
    readings: list[tuple[str, str, datetime]] = []  # (guard_name, "ok"|"bad", ts)
    for line in lines:
        try:
            e = json.loads(line)
            ts = datetime.fromisoformat(e["ts"])
            # Clamp future timestamps (clock skew) to now.
            if ts > now:
                ts = now
            readings.append((e["guard"], "ok" if e.get("ok") else "bad", ts))
        except (ValueError, KeyError, TypeError):
            continue

    # Group readings by guard name and fold into episodes.
    guards = {}
    for name in GUARD_TABLE:
        guards[name] = []

    for guard_name, ok_str, ts in readings:
        if guard_name in guards:
            guards[guard_name].append((ok_str, ts))

    result = {}
    for guard_name, readings_for_guard in guards.items():
        if not readings_for_guard:
            continue

        episode = _fold_episodes(readings_for_guard, now)
        if episode:
            episode["fail_mode"] = GUARD_TABLE[guard_name]
            result[guard_name] = episode

    return result


def _fold_episodes(readings: list[tuple[str, datetime]], now: datetime) -> dict | None:
    """Fold a list of (ok/bad, ts) readings into an active episode, or None.

    Onset: 2 consecutive "bad" readings, OR (1 "bad" reading + no recovery within 30 min).
    Recovery: 2 consecutive "ok" readings.
    """
    if not readings:
        return None

    # Find the most recent recovery point (2 consecutive "ok" readings).
    latest_recovery = None
    for i in range(len(readings) - 1):
        if readings[i][0] == "ok" and readings[i + 1][0] == "ok":
            latest_recovery = readings[i + 1][1]

    # If we have a recovery, only consider readings after it.
    if latest_recovery:
        readings = [r for r in readings if r[1] > latest_recovery]

    if not readings:
        return None

    # Check onset: 2 consecutive "bad" readings, OR (1 "bad" + 30 min elapsed with no recovery).
    has_two_bad = any(readings[i][0] == "bad" and i + 1 < len(readings) and readings[i + 1][0] == "bad"
                      for i in range(len(readings)))
    if has_two_bad:
        # Find the first "bad" reading in this episode.
        episode_start = next(r[1] for r in readings if r[0] == "bad")
    else:
        # Check if there's 1 "bad" reading + 30 min has passed since it.
        bad_readings = [r for r in readings if r[0] == "bad"]
        if bad_readings:
            first_bad = bad_readings[0]
            if (now - first_bad[1]).total_seconds() >= YELLOW_AFTER_MINUTES * 60:
                episode_start = first_bad[1]
            else:
                return None
        else:
            return None

    age_minutes = int((now - episode_start).total_seconds() // 60)
    return {"episode_start": episode_start.isoformat(), "age_minutes": age_minutes}
