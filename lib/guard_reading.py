#!/usr/bin/env python3
"""Visibility into intermittent read failures via hysteresis (marvin#889, marvin#891).

A reading can be "ok" (a successful read) or an error. The module tracks episodes: a name that reads
bad at least twice within a 30-minute window opens an episode, stays open until an ok reading, and
alerts once per day while open. First alert is "new", a close is "cleared", and open but already
alerted is "reminder". Failures that can't be read are tracked too — no unreadable guard ever blocks,
but it must be visible.

    guard_reading.py reading NAME --ok [--detail TEXT]        # record ok
    guard_reading.py reading NAME --error TEXT [--detail TEXT] # record error
    mr_notification's dashboard shows one yellow row per open episode, severity yellow per FAIL_MODE.
    health_checks checks for them daily and alerts accordingly (ADR 0083).
"""
from __future__ import annotations

import argparse
import fcntl
import json
import os
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

HERE = Path(__file__).resolve()
MARVIN_ROOT = HERE.parent.parent
STATE_PATH = Path.home() / ".claude" / "logs" / "guard-state.json"

FAIL_MODE = {
    "memory:pressure": "memory pressure",
    "disk:preflight": "disk space below floor",
    "disk:dispatch_local": "local disk read failed",
    "disk:dispatch_remote": "remote disk read failed",
    "disk:merge_gate": "merge gate disk check failed",
    "dispatch:disk_free_gb": "disk free GB check failed",
    "dispatch:github_budget_pct": "GitHub budget percentage check failed",
    "dispatch:breaker_tripped": "circuit breaker tripped check failed",
    "dispatch:missing_tools": "missing tools check failed",
    "dispatch:task_records": "failed to read task records",
    "dispatch:credit_remote": "remote credit check failed",
    "breaker:record_failure": "circuit breaker recording failed",
    "task_dispatch:tailscale": "Tailscale online hosts check failed",
    "task_dispatch:local_state": "local dispatch state read failed",
    "task_dispatch:remote_state": "remote dispatch state read failed",
}


def reading(name: str, value_or_error: object, *, now: datetime | None = None,
            detail: str | None = None) -> dict:
    """Record one reading: ok (string/success) or error (Exception/failure). Never raises.
    Returns {"episode": episode_opened_at or None, "alert": "new"|"reminder"|"cleared"|None}."""
    now = now or datetime.now(timezone.utc)
    today = now.date().isoformat()

    is_ok = not isinstance(value_or_error, Exception)
    error_msg = str(value_or_error) if isinstance(value_or_error, Exception) else None
    detail_text = str(detail or "")[:256] if detail else None

    state = _read_state()
    entry = state.get(name, {})

    result = {"episode": None, "alert": None}

    if is_ok:
        if "episode_opened_at" in entry:
            result["alert"] = "cleared"
        state.pop(name, None)
    else:
        last_error_at_str = entry.get("last_error_at")
        last_error_at = None
        if last_error_at_str:
            try:
                last_error_at = datetime.fromisoformat(last_error_at_str)
            except (ValueError, TypeError):
                pass

        within_window = (
            last_error_at is not None and
            (now - last_error_at) <= timedelta(minutes=30)
        )

        if "episode_opened_at" in entry:
            result["episode"] = entry["episode_opened_at"]
            last_alert_date = entry.get("last_alert_date")
            if last_alert_date != today:
                result["alert"] = "reminder"
                entry["last_alert_date"] = today
        elif within_window:
            entry["episode_opened_at"] = now.isoformat()
            entry["last_alert_date"] = today
            result["episode"] = entry["episode_opened_at"]
            result["alert"] = "new"

        entry["last_error"] = error_msg
        entry["last_error_at"] = now.isoformat()
        if detail_text:
            entry["detail"] = detail_text
        entry["last_reading_at"] = now.isoformat()
        state[name] = entry

    _write_state(state)
    return result


def _read_state() -> dict:
    """Read and parse state file; return {} on missing or corrupt."""
    try:
        if not STATE_PATH.exists():
            return {}
        text = STATE_PATH.read_text()
        d = json.loads(text)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_state(state: dict) -> None:
    """Write state atomically, fcntl-locked. Never raises. Skip write if state is empty."""
    if not state:
        try:
            STATE_PATH.unlink(missing_ok=True)
        except OSError:
            pass
        return
    try:
        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(STATE_PATH, "a") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            try:
                f.seek(0)
                f.truncate()
                f.write(json.dumps(state) + "\n")
            finally:
                fcntl.flock(f, fcntl.LOCK_UN)
    except OSError:
        pass


def alert_degraded(state: dict | None = None, path: Path | None = None, fire: Callable | None = None,
                   today: str | None = None) -> None:
    """Alert on open episodes via mr_notification.alert_on_change. Never raises."""
    path = path or STATE_PATH
    today_str = today or date.today().isoformat()

    try:
        import mr_notification
    except ImportError:
        return

    state = state or _read_state()

    items = []
    for name, entry in state.items():
        if isinstance(entry, dict) and "episode_opened_at" in entry:
            items.append({
                "key": name,
                "state": "degraded",
                "title": f"Guard reading: {name}",
                "message": FAIL_MODE.get(name, name),
            })

    def message_fn(item: dict) -> tuple[str, str]:
        name = item.get("key", "?")
        msg = item.get("message", "")
        return f"MARVIN: {name}", msg

    if fire is None:
        fire = lambda t, m: mr_notification._fire(t, m)

    mr_notification.alert_on_change(
        items,
        path,
        bad=("degraded",),
        message=message_fn,
        fire=fire,
        today=date.fromisoformat(today_str) if today_str else date.today(),
    )


def main(argv: list[str]) -> int:
    """CLI: guard_reading.py reading NAME (--ok|--error TEXT) [--detail TEXT]."""
    parser = argparse.ArgumentParser(prog="guard_reading.py")
    subparsers = parser.add_subparsers(dest="cmd")

    reading_parser = subparsers.add_parser("reading")
    reading_parser.add_argument("name")
    reading_parser.add_argument("--ok", action="store_true")
    reading_parser.add_argument("--error", type=str)
    reading_parser.add_argument("--detail", type=str)

    args = parser.parse_args(argv)

    if args.cmd == "reading":
        if args.ok and args.error:
            print("error: cannot use both --ok and --error")
            return 1
        if not args.ok and not args.error:
            print("error: must use --ok or --error")
            return 1

        if args.ok:
            value_or_error = "ok"
        else:
            value_or_error = RuntimeError(args.error)

        result = reading(args.name, value_or_error, detail=args.detail)
        print(json.dumps(result))
        return 0

    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
