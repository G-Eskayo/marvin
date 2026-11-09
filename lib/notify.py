#!/usr/bin/env python3
"""Shared notification helper. Since #1123 (ADR 0083) `notify()` goes through the one alert path,
`mr_notification._fire`, and `desktop()` is that path's desktop channel. History of the desktop channel follows.

Shared macOS notification helper — resolves the long-open "Digest
delivery mechanism" roadmap decision (~/.claude/marvin-roadmap.md §I).

Chose option (b), a real macOS notification, over passive session-start-only
printing: the actual problem this closes is content silently piling up with
no proactive signal, which passive printing can't fix by definition (found
2026-07-09 investigating why quarantine.md had 6 unreviewed items and 0
checked boxes — nothing ever told Gil to go look).

PushNotification (reaches desktop + phone via Remote Control) would be
better, but it's a tool called from within an active Claude Code session —
these loops run as bare launchd-invoked scripts with no session or tool
access. Untested whether a headless `claude -p` call could invoke it; not
assumed here. This is the reliable fallback that definitely works standalone.

Click-to-open (added 2026-08-19): plain `osascript -e 'display notification'`
has no click-action mechanism at all in current macOS, and Notification
Center attributes the banner to "Script Editor" (osascript's own host app),
so clicking it just refocuses an empty Script Editor instead of the document
the message referenced (Gil hit this — every "check sync-log.md"/"check
quarantine.md" notification was a dead end). terminal-notifier supports a
real `-open <url>` click action, so it's used when installed
(`brew install terminal-notifier`); without it, this falls back to the
original no-click-action behavior rather than failing.
"""
from __future__ import annotations
import os
import shutil
import subprocess
import sys
from pathlib import Path


def _applescript_quote(s: str) -> str:
    """AppleScript double-quoted string escaping — Python's repr() uses
    Python syntax, not AppleScript syntax, and would mis-embed anything
    with a double quote or backslash in it."""
    return s.replace("\\", "\\\\").replace('"', '\\"')


def _to_open_url(target: str) -> str:
    """terminal-notifier's -open wants a URL; accept a local path too."""
    if target.startswith(("http://", "https://", "file://")):
        return target
    return Path(target).expanduser().resolve().as_uri()


NOTIFIER_PLACES = ("/opt/homebrew/bin/terminal-notifier", "/usr/local/bin/terminal-notifier")


def _notifier() -> str | None:
    """terminal-notifier on PATH, else where Homebrew puts it. launchd's default PATH has no /opt/homebrew/bin, so a
    job without it on PATH used to fall back to osascript's click-less banner without saying so (#1123)."""
    found = shutil.which("terminal-notifier")
    if found:
        return found
    return next((p for p in NOTIFIER_PLACES if Path(p).is_file() and os.access(p, os.X_OK)), None)


def desktop(title: str, message: str, open_target: str | None = None) -> str:
    """This Mac's banner, and the real result: "sent" only when the notifier exited 0. Raises on failure, so the
    alert path (mr_notification._fire) records what actually happened."""
    notifier = _notifier()
    if notifier:
        cmd = [notifier, "-title", title, "-message", message]
        if open_target:
            cmd += ["-open", _to_open_url(open_target)]
    else:
        script = f'display notification "{_applescript_quote(message)}" with title "{_applescript_quote(title)}"'
        cmd = ["osascript", "-e", script]
    out = subprocess.run(cmd, capture_output=True, timeout=5)
    if getattr(out, "returncode", 0) != 0:
        err = (getattr(out, "stderr", b"") or b"").decode(errors="replace").strip().splitlines()
        raise RuntimeError(f"{Path(cmd[0]).name} exited {out.returncode}" + (f": {err[-1][:120]}" if err else ""))
    return "sent" if notifier else "sent (no click action: terminal-notifier not found)"


def notify(title: str, message: str, open_target: str | None = None) -> dict:
    """Tell the owner, through the one alert path (mr_notification._fire: desktop, dashboard, and the phone once
    MARVIN Mobile's push lands, #958). Returns each channel's real result. Never raises: telling must never break the
    calling loop."""
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import mr_notification
        return mr_notification._fire(title, message, open_target)
    except Exception as exc:  # noqa: BLE001
        return {"channels": {}, "delivered": [], "error": f"{type(exc).__name__}: {exc}"[:200]}
