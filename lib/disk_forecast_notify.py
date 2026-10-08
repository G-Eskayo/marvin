#!/usr/bin/env python3
"""Red disk:headroom forecast notifications (ADR 0056).

When disk headroom falls below 7 days (red severity), notify once per device
per day via desktop, push, and dashboard channels (same pattern as
mr_notification.py). De-duped via ~/.claude/logs/disk-headroom-notified.json
so a persistent red state doesn't spam.

Called from health_checks._cli() after a fresh disk:headroom check.
"""
from __future__ import annotations

import json
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from notify import notify as _default_desktop_notify  # noqa: E402
import machine_profile  # noqa: E402

HOME = Path.home()
NOTIFICATION_STATE_PATH = HOME / ".claude" / "logs" / "disk-headroom-notified.json"
PUSH_TIMEOUT_S = 60
DASHBOARD_REFRESH_URL = "http://localhost:7878/mr-ready"
DASHBOARD_REFRESH_TIMEOUT_S = 3


def _default_push_notify(message: str) -> None:
    prompt = f"Call the PushNotification tool with the message '{message}' and status alert."
    subprocess.run(
        ["claude", "-p", prompt, "--model", "claude-haiku-4-5-20251001",
         "--allowedTools", "PushNotification"],
        capture_output=True, text=True, timeout=PUSH_TIMEOUT_S,
    )


def _default_dashboard_refresh_ping() -> None:
    urllib.request.urlopen(
        urllib.request.Request(DASHBOARD_REFRESH_URL, data=b"{}", method="POST"),
        timeout=DASHBOARD_REFRESH_TIMEOUT_S,
    )


desktop_notify = _default_desktop_notify
push_notify = _default_push_notify
dashboard_refresh_ping = _default_dashboard_refresh_ping


def _read_notification_state() -> dict:
    """Load the notification de-duplication state."""
    if NOTIFICATION_STATE_PATH.exists():
        try:
            return json.loads(NOTIFICATION_STATE_PATH.read_text())
        except Exception:
            pass
    return {}


def _write_notification_state(state: dict) -> None:
    """Save the notification state."""
    NOTIFICATION_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    NOTIFICATION_STATE_PATH.write_text(json.dumps(state, indent=2))


def should_notify(device: str) -> bool:
    """Check if we should send a new notification for this device today.

    Returns False if we already notified on this calendar day for this device.
    """
    state = _read_notification_state()
    today = datetime.now(timezone.utc).date().isoformat()

    device_state = state.get(device, {})
    last_notified = device_state.get("last_notified_date")

    return last_notified != today


def mark_notified(device: str) -> None:
    """Record that we notified for this device today."""
    state = _read_notification_state()
    today = datetime.now(timezone.utc).date().isoformat()

    if device not in state:
        state[device] = {}

    state[device]["last_notified_date"] = today
    state[device]["last_notified_at"] = datetime.now(timezone.utc).isoformat()

    _write_notification_state(state)


def notify_red_headroom(device: str, days_until_critical: float, detail: str) -> dict:
    """Fire notification on red disk:headroom forecast.

    Returns status dict with success/failure for each channel.
    """
    if not should_notify(device):
        return {"notified": False, "reason": "already notified today for this device"}

    message = f"MARVIN: disk space critical on {device} — {days_until_critical:.0f}d until out"

    desktop_sent = False
    try:
        desktop_notify("MARVIN: Disk space critical", message)
        desktop_sent = True
    except Exception:
        pass

    push_sent = False
    try:
        push_notify(message)
        push_sent = True
    except Exception:
        pass

    dashboard_pinged = False
    try:
        dashboard_refresh_ping()
        dashboard_pinged = True
    except Exception:
        pass

    mark_notified(device)

    return {
        "notified": True,
        "device": device,
        "days_until_critical": days_until_critical,
        "desktop_sent": desktop_sent,
        "push_sent": push_sent,
        "dashboard_pinged": dashboard_pinged,
    }
