#!/usr/bin/env python3
"""Shared macOS notification helper — resolves the long-open "Digest
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
import shutil
import subprocess
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


def notify(title: str, message: str, open_target: str | None = None) -> None:
    """Fire a macOS notification. If open_target (a URL or local file path)
    is given and terminal-notifier is installed, clicking the notification
    opens it directly. Without terminal-notifier, falls back to a plain
    AppleScript notification with no click action."""
    try:
        notifier = shutil.which("terminal-notifier")
        if notifier:
            cmd = [notifier, "-title", title, "-message", message]
            if open_target:
                cmd += ["-open", _to_open_url(open_target)]
            subprocess.run(cmd, capture_output=True, timeout=5)
        else:
            script = f'display notification "{_applescript_quote(message)}" with title "{_applescript_quote(title)}"'
            subprocess.run(["osascript", "-e", script], capture_output=True, timeout=5)
    except Exception:
        pass  # notification failing should never break the calling loop
