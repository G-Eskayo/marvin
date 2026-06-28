#!/usr/bin/env python3
"""PostToolUse hook: after Write/Edit, print a terse resume-prompt reminder.

Keeps the prompt cache warm by emitting a single line that tells a resuming
agent where to look for the handoff document. Does nothing if no recent
handoff exists (within 7 days).
"""
from __future__ import annotations
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

HANDOFFS_DIR = Path.home() / ".claude" / "handoffs"
MAX_AGE = timedelta(days=7)


def main() -> None:
    if not HANDOFFS_DIR.exists():
        return

    candidates = sorted(HANDOFFS_DIR.glob("handoff-*.md"), reverse=True)
    if not candidates:
        return

    latest = candidates[0]
    try:
        mtime = datetime.fromtimestamp(latest.stat().st_mtime, tz=timezone.utc)
    except OSError:
        return

    if datetime.now(timezone.utc) - mtime > MAX_AGE:
        return

    print(f"[handoff] Last saved: {latest.name} — paste resume prompt to restore context.", file=sys.stderr)


if __name__ == "__main__":
    main()
