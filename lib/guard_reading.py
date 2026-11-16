#!/usr/bin/env python3
"""Centralized guard state management: record which guards are readable/unreadable, with episode logic,
yellow thresholds, and 2-hour escalation alerts. Closes #889 (tailscale outages discovered too late) and
#891-shape issues (malformed state files vanish silently).

Every guard call site wraps its reader with guard_reading() for centralized counting/logging; on success
the value is recorded and returned, on any Exception a None is returned. Call-site contract unchanged.

Closed guards (disk, memory) change real behavior: unreadable is treated as "refuse that work", fail-closed.
Open guards keep returning None to their caller; guard_reading only adds counting on top.

State: ~/.claude/logs/guard-unreadable.json, keyed by "name@device" (local if no device).
Per key: consecutive_unreadable, first_unreadable_at, consecutive_readable, alerted_at, last_error.
Yellow threshold: consecutive_unreadable > 2 OR now - first_unreadable_at >= 30min.
Episode closes after consecutive_readable >= 2 (debounce flapping).
Alert once per episode when now - first_unreadable_at >= 2h.
"""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable


FAIL_MODE: dict[str, str] = {
    "disk": "closed",
    "memory": "closed",
    "github_budget": "open",
    "credit": "open",
    "breaker": "open",
    "missing_tools": "open",
    "task_records": "open",
    "tailscale": "open",
    "dispatch_state": "open",
    "failure_log": "open",
}

STATE_PATH = Path.home() / ".claude" / "logs" / "guard-unreadable.json"
YELLOW_THRESHOLD_UNREADABLE = 2  # consecutive_unreadable > this
YELLOW_THRESHOLD_DURATION = timedelta(minutes=30)  # now - first_unreadable_at >=
EPISODE_CLOSE_THRESHOLD = 2  # consecutive_readable >= this
ALERT_DURATION = timedelta(hours=2)  # now - first_unreadable_at >=
STALE_THRESHOLD = timedelta(hours=1)  # readings older than this are considered stale and not flagged


def _validate_fail_mode() -> None:
    for guard, mode in FAIL_MODE.items():
        if mode not in ("open", "closed"):
            raise ValueError(f"FAIL_MODE[{guard!r}] = {mode!r}, must be 'open' or 'closed'")


_validate_fail_mode()


def _read_state() -> dict[str, dict]:
    """Guard state from the file, or {} if unreadable."""
    try:
        return json.loads(STATE_PATH.read_text())
    except (OSError, ValueError):
        return {}


def _write_state(state: dict) -> None:
    """Atomically write guard state, fail silently if not possible (the state file must never break a guard)."""
    try:
        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=STATE_PATH.parent, suffix=".tmp")
        with os.fdopen(fd, "w") as f:
            json.dump(state, f, indent=2)
            f.write("\n")
        os.replace(tmp, STATE_PATH)
    except OSError:
        pass


def guard_reading(
    name: str,
    reader: Callable,
    *args,
    device: str | None = None,
    **kwargs,
) -> Any:
    """Call reader(*args, **kwargs); on success record readable and return the value; on any Exception
    or None result record unreadable and return None. Call-site contract unchanged: always returns value or None."""
    if not isinstance(name, str) or not name:
        raise ValueError(f"guard_reading name must be a non-empty str, got {name!r}")
    if not callable(reader):
        raise TypeError(f"reader must be callable, got {type(reader).__name__}")
    if name not in FAIL_MODE:
        raise ValueError(f"guard {name!r} not in FAIL_MODE; add it to lib/guard_reading.py")

    key = f"{name}@{device or 'local'}"
    state = _read_state()
    now = datetime.now(timezone.utc)

    result = None
    exc = None
    try:
        result = reader(*args, **kwargs)
    except Exception as e:  # noqa: BLE001
        exc = e

    # Treat None result as unreadable (most wrapped readers return None on failure).
    is_readable = result is not None and exc is None

    try:
        if is_readable:
            # Success: record readable and return.
            if key not in state:
                state[key] = {
                    "consecutive_unreadable": 0,
                    "first_unreadable_at": None,
                    "consecutive_readable": 1,
                    "alerted_at": None,
                    "last_error": None,
                    "last_read_at": now.isoformat(),
                }
            else:
                entry = state[key]
                entry["consecutive_readable"] = entry.get("consecutive_readable", 0) + 1
                entry["last_read_at"] = now.isoformat()
                # Episode closes when consecutive_readable >= EPISODE_CLOSE_THRESHOLD; reset the unreadable counters.
                if entry["consecutive_readable"] >= EPISODE_CLOSE_THRESHOLD:
                    entry["consecutive_unreadable"] = 0
                    entry["first_unreadable_at"] = None
                    entry["alerted_at"] = None
        else:
            # Failure: record unreadable and return None.
            error_str = f"{type(exc).__name__}: {str(exc)[:120]}" if exc else "returned None"
            if key not in state:
                state[key] = {
                    "consecutive_unreadable": 1,
                    "first_unreadable_at": now.isoformat(),
                    "consecutive_readable": 0,
                    "alerted_at": None,
                    "last_error": error_str,
                    "last_read_at": now.isoformat(),
                }
            else:
                entry = state[key]
                entry["consecutive_unreadable"] = entry.get("consecutive_unreadable", 0) + 1
                entry["consecutive_readable"] = 0
                entry["last_error"] = error_str
                entry["last_read_at"] = now.isoformat()
                if entry["first_unreadable_at"] is None:
                    entry["first_unreadable_at"] = now.isoformat()

            # Log once per read to error_log (via hook_errors), only if there was an exception.
            if exc:
                try:
                    import sys

                    sys.path.insert(0, str(Path(__file__).resolve().parent))
                    import hook_errors

                    hook_errors.log_hook_error(
                        "guard_reading",
                        f"guard {key}",
                        exc,
                    )
                except Exception:  # noqa: BLE001
                    pass

            # Check if 2h alert should fire.
            entry = state[key]
            if entry.get("first_unreadable_at") and entry.get("alerted_at") is None:
                try:
                    first_time = datetime.fromisoformat(entry["first_unreadable_at"])
                    if now - first_time >= ALERT_DURATION:
                        entry["alerted_at"] = now.isoformat()
                        try:
                            import notify

                            notify.notify(
                                "MARVIN: guard unreadable",
                                f"{key} has been unreadable for 2 hours: {entry.get('last_error', '?')}",
                            )
                        except Exception:  # noqa: BLE001
                            pass
                except (ValueError, TypeError):
                    # Malformed ISO string in state; skip alert logic but keep the record.
                    pass

        _write_state(state)
    except Exception:  # noqa: BLE001
        # State bookkeeping error: fail silently but preserve the read result.
        pass

    return result if is_readable else None


def flagged_guards(now: datetime | None = None) -> list[dict]:
    """Guards currently at or above the yellow threshold: list of
    {"name": "name@device", "first_unreadable_at": iso, "last_error": "..."}."""
    now = now or datetime.now(timezone.utc)
    state = _read_state()
    flagged = []
    for key, entry in state.items():
        # Skip malformed entries (not a dict).
        if not isinstance(entry, dict):
            continue
        try:
            # Skip if stale (not probed recently). A guard that hasn't been read in over 1 hour doesn't count as flagged.
            last_read_str = entry.get("last_read_at")
            if last_read_str:
                last_read = datetime.fromisoformat(last_read_str)
                if now - last_read >= STALE_THRESHOLD:
                    continue  # Stale: don't flag even if first_unreadable_at is set.

            # Flag if consecutive_unreadable > threshold.
            if entry.get("consecutive_unreadable", 0) > YELLOW_THRESHOLD_UNREADABLE:
                flagged.append(
                    {
                        "name": key,
                        "first_unreadable_at": entry.get("first_unreadable_at"),
                        "last_error": entry.get("last_error"),
                    }
                )
                continue

            # Flag if first_unreadable_at exists and is old enough (>= 30min).
            first_unreadable_str = entry.get("first_unreadable_at")
            if first_unreadable_str:
                first_time = datetime.fromisoformat(first_unreadable_str)
                if now - first_time >= YELLOW_THRESHOLD_DURATION:
                    flagged.append(
                        {
                            "name": key,
                            "first_unreadable_at": entry.get("first_unreadable_at"),
                            "last_error": entry.get("last_error"),
                        }
                    )
        except (ValueError, TypeError, AttributeError):
            # Malformed entry (bad ISO string, missing keys, etc.); skip it.
            continue
    return flagged
