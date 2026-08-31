#!/usr/bin/env python3
"""MR-ready notification for the MR pipeline (G-Eskayo/marvin#5).

mr_raiser.py is bare Python with no Claude session of its own, so it can't
call the PushNotification tool directly -- that tool only exists inside a
live or headless `claude -p` session's own tool-use loop. Two channels,
not one:

- **desktop_notify** (default: notify.py's proven osascript mechanism) --
  guaranteed to work standalone, already relied on by other cron jobs.
- **push_notify** (default: a headless `claude -p` call whose only job is
  to invoke PushNotification) -- reaches the phone via Remote Control, but
  depends on a real Claude session spinning up just for this, and
  PushNotification has its own built-in duplicate-suppression logic (skips
  if it detects an active session already reaching the user) that a live
  smoke test can't fully validate from inside another active session.
- **dashboard_refresh_ping** (default: a POST to the dashboard webhook-
  server's own `/mr-ready` endpoint) -- a best-effort local nudge so an
  already-open dashboard on THIS machine updates immediately instead of
  waiting on its own fallback poll (Gil's request, 2026-08-31). The
  webhook-server always runs here via launchd regardless of whether the
  Electron app itself is open; it forwards the ping on to the app's own
  tiny local refresh server if one is listening
  (dashboard/webhook-server/refresh_relay.js). If dispatch happened on
  the *other* machine, this ping hits nothing here, which is correct --
  that machine's own dispatch would have pinged its own webhook-server.

Per notify.py's own established principle, a notification failing should
never break the calling pipeline -- push_notify and dashboard_refresh_ping
are both wrapped so a failure in either never prevents the desktop
notification or raises up to the caller.
"""
from __future__ import annotations
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from notify import notify as _default_desktop_notify  # noqa: E402

PUSH_TIMEOUT_S = 60
DASHBOARD_REFRESH_URL = "http://localhost:7878/mr-ready"
DASHBOARD_REFRESH_TIMEOUT_S = 3


def _default_push_notify(message: str) -> None:
    prompt = f"Call the PushNotification tool with the message '{message}' and status proactive."
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


def notify_mr_ready(ticket_ref: str, pr_url: str) -> dict:
    """Fire all three notification channels for a newly-raised MR. Never
    raises -- a failure in any channel is captured in the returned status
    dict."""
    message = f"MR ready for review: {ticket_ref} -> {pr_url}"

    desktop_sent = False
    try:
        desktop_notify("MARVIN: MR ready for review", message, open_target=pr_url)
        desktop_sent = True
    except Exception:
        pass

    push_succeeded = False
    try:
        push_notify(message)
        push_succeeded = True
    except Exception:
        pass

    dashboard_ping_succeeded = False
    try:
        dashboard_refresh_ping()
        dashboard_ping_succeeded = True
    except Exception:
        pass

    return {
        "desktop_sent": desktop_sent,
        "push_attempted": True,
        "push_succeeded": push_succeeded,
        "dashboard_ping_attempted": True,
        "dashboard_ping_succeeded": dashboard_ping_succeeded,
    }
