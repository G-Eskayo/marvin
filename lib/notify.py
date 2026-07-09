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
"""
from __future__ import annotations
import subprocess


def _applescript_quote(s: str) -> str:
    """AppleScript double-quoted string escaping — Python's repr() uses
    Python syntax, not AppleScript syntax, and would mis-embed anything
    with a double quote or backslash in it."""
    return s.replace("\\", "\\\\").replace('"', '\\"')


def notify(title: str, message: str) -> None:
    try:
        script = f'display notification "{_applescript_quote(message)}" with title "{_applescript_quote(title)}"'
        subprocess.run(["osascript", "-e", script], capture_output=True, timeout=5)
    except Exception:
        pass  # notification failing should never break the calling loop
