#!/usr/bin/env python3
"""Guard reading: uniform logging and state tracking for all system-state reads.

When MARVIN reads disk space, memory pressure, GitHub budget, Tailscale status, or
any other state that could be unreadable, it goes through guard_reading() to log
whether the read succeeded. This creates a persistent record of which guards are
unreliable, so health checks can alert when an episode of unreadable state is old enough
to matter. A guard that can't be read never blocks dispatch; guard_reading() just logs
the incident so Health can flag it.

Each guard has a fail-mode from the FAIL_MODE table: "closed" means refusals (like
disk space) go through the guard, "open" means unreadable state falls back to safe
defaults and dispatch carries on. The table drives:
- which guard name goes in the log
- what fail-mode it has
- what Health shows (streak age, consecutive failures)

    guard_reading(name, value, error=None) -> value | None
        Appends one line to ~/.claude/logs/guard-readings.jsonl and returns `value`
        unchanged on success (whether value is None, 0, False or a real value), or
        None on a read failure (error not None).

    guard_reading.py record --name <name> --ok <bool> [--error <msg>]
        Node.js and bash call this to log their reads too (async fire-and-forget).
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

HOME = Path.home()
LOG_PATH = HOME / ".claude" / "logs" / "guard-readings.jsonl"
STATE_PATH = HOME / ".claude" / "logs" / "guard-degraded-state.json"
LOG_MAX_BYTES = 5 * 2**20

FAIL_MODE = {
    "disk:local-pipeline": "closed",         # dispatch checks before work starts
    "disk:local-triggers": "open",           # preflight() never blocks when unreadable (as #690)
    "disk:remote-dispatch": "closed",        # remote machine's disk
    "disk:merge-gate": "closed",             # merge refuses when unreadable
    "memory:pressure": "open",               # memory guard never blocks when unreadable
    "dispatch:github-budget": "open",        # unreadable budget doesn't block (fallback)
    "dispatch:breaker": "open",              # unreadable breaker doesn't block
    "dispatch:missing-tools": "open",        # missing tools don't block when unreadable
    "dispatch:task-records": "open",         # task records fallback to empty when unreadable
    "dispatch:tailscale-hosts": "open",      # Tailscale fallback to safe defaults
    "dispatch:state-local": "open",          # unreadable dispatch state uses defaults
    "dispatch:state-remote": "open",         # remote dispatch state unreadable = safe default
    "pipeline:breaker-remote": "open",       # remote breaker unreadable doesn't block
}

ALERT_THRESHOLD_S = 2 * 3600  # a guard with 2+ consecutive unreadables or 30min old episode alerts
ALERT_THRESHOLD_MIN = 30


def guard_reading(name: str, value: Any, error: str | None = None) -> Any:
    """Log a system-state read (success or failure) and return the value.

    Args:
        name: guard name from FAIL_MODE table
        value: the read value (None, 0, False, or a real value all mean success here)
        error: if not None, the read failed with this reason

    Returns:
        `value` unchanged on success, None on failure (error not None).
        Guards that can't be read (error not None) never block dispatch; the
        return value helps the caller decide whether to use the value.
    """
    ok = error is None
    entry = {
        "at": datetime.now(timezone.utc).isoformat(),
        "guard": name,
        "ok": ok,
        "fail_mode": FAIL_MODE.get(name, "unknown"),
    }
    if error:
        entry["error"] = str(error)[:200]

    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        # Rotate log file when it exceeds max size, keeping the newest half.
        if LOG_PATH.exists() and LOG_PATH.stat().st_size > LOG_MAX_BYTES:
            lines = LOG_PATH.read_text(errors="replace").splitlines()
            LOG_PATH.write_text("\n".join(lines[len(lines) // 2:]) + "\n")
        with open(LOG_PATH, "a") as f:
            f.write(json.dumps(entry) + "\n")
    except OSError:
        pass  # a log that can't be written must not change what we return

    if ok:
        return value
    return None


def _read_guard_log() -> list[dict]:
    """All entries from the guard log, newest last. Returns [] if the log doesn't exist."""
    if not LOG_PATH.exists():
        return []
    lines = []
    try:
        for line in LOG_PATH.read_text(errors="replace").splitlines():
            try:
                lines.append(json.loads(line))
            except (ValueError, TypeError):
                pass
    except OSError:
        pass
    return lines


def guard_state(name: str) -> dict:
    """The current episode state for a guard: consecutive failures, age, is it old enough to alert.

    Returns:
        {"ok": bool, "consecutive_unreadable": int, "episode_age_min": float, "alert": bool}
    """
    lines = _read_guard_log()
    # Find the current episode: walk backwards from newest until we hit an "ok" entry.
    consecutive_unreadable = 0
    episode_start: datetime | None = None
    for entry in reversed(lines):
        if entry.get("guard") != name:
            continue
        if entry.get("ok"):
            break
        consecutive_unreadable += 1
        episode_start = datetime.fromisoformat(entry["at"])

    if consecutive_unreadable == 0:
        return {"ok": True, "consecutive_unreadable": 0, "episode_age_min": 0.0, "alert": False}

    now = datetime.now(timezone.utc)
    episode_age = (now - episode_start).total_seconds() / 60 if episode_start else 0.0
    alert = consecutive_unreadable >= 2 or episode_age >= ALERT_THRESHOLD_MIN
    return {
        "ok": False,
        "consecutive_unreadable": consecutive_unreadable,
        "episode_age_min": episode_age,
        "alert": alert,
    }


def _read_degraded_state() -> dict:
    """Current degraded-alert state file: {guard_name: "alerted_at" timestamp or None, ...}."""
    try:
        return json.loads(STATE_PATH.read_text())
    except (OSError, ValueError):
        return {}


def _write_degraded_state(state: dict) -> None:
    """Write degraded-alert state file atomically."""
    try:
        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        STATE_PATH.write_text(json.dumps(state) + "\n")
    except OSError:
        pass


def check_and_alert(notify_fn) -> list[str]:
    """Check all guards for 2+ unreadable or ≥30min episode age; alert once per episode.

    Args:
        notify_fn: a callable that takes (title, message) to send a notification

    Returns:
        list of guard names that were alerted (may be empty).

    This is called by health_checks.py to trigger alerts; it updates the state file
    so we don't alert twice for the same episode.
    """
    alerted = []
    state = _read_degraded_state()
    now = datetime.now(timezone.utc).isoformat()

    for guard_name in FAIL_MODE:
        s = guard_state(guard_name)
        if not s["alert"]:
            if guard_name in state:
                del state[guard_name]
            continue
        # This guard's episode is old enough to alert, and we haven't alerted yet (or did long ago).
        if guard_name in state:
            continue  # already alerted this episode, skip
        # New alert.
        try:
            notify_fn(
                f"Guard unreadable: {guard_name}",
                f"{guard_name} has been unreadable for {s['episode_age_min']:.0f} minutes "
                f"({s['consecutive_unreadable']} consecutive failures).",
            )
        except Exception:
            pass  # a failed notification must not break the check
        state[guard_name] = now
        alerted.append(guard_name)

    _write_degraded_state(state)
    return alerted


def _cli(argv: list[str]) -> int:
    """CLI: record --name <name> --ok <bool> [--error <msg>]"""
    parser = argparse.ArgumentParser(description="Log a guard reading")
    subparsers = parser.add_subparsers(dest="command")

    record_parser = subparsers.add_parser("record")
    record_parser.add_argument("--name", required=True, help="Guard name")
    record_parser.add_argument("--ok", required=True, choices=["true", "false"], help="Whether the read succeeded")
    record_parser.add_argument("--error", default=None, help="Error message if the read failed")

    args = parser.parse_args(argv)

    if args.command == "record":
        ok = args.ok == "true"
        error = None if ok else (args.error or "read failed")
        guard_reading(args.name, None, error=error)
        return 0

    parser.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(_cli(sys.argv[1:]))
