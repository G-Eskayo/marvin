#!/usr/bin/env python3
"""PostToolUse hook (matcher: Skill): appends {skill, ts} to
~/.agents/brain-map/activity.jsonl whenever a skill actually fires.

This is the live signal source for DesktopLive's pulse/camera-nudge
animation — the graph reading activity.jsonl is what turns "a picture of
the structure" into "what's actually running right now". Never blocks or
errors the originating tool call: any failure exits silently, matching
the other three PostToolUse hooks in this system.
"""
import json
import sys
import time
from pathlib import Path

ACTIVITY_PATH = Path.home() / ".agents" / "brain-map" / "activity.jsonl"
MAX_LINES = 500  # trim on write — this is a live-activity feed, not a log archive


def main() -> None:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return

    if payload.get("tool_name", "") != "Skill":
        return
    skill = (payload.get("tool_input") or {}).get("skill", "")
    if not skill:
        return

    entry = json.dumps({"skill": skill, "ts": time.time()})

    try:
        ACTIVITY_PATH.parent.mkdir(parents=True, exist_ok=True)
        lines = []
        if ACTIVITY_PATH.exists():
            lines = ACTIVITY_PATH.read_text(encoding="utf-8").splitlines()
        lines.append(entry)
        lines = lines[-MAX_LINES:]
        ACTIVITY_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    except Exception:
        return


if __name__ == "__main__":
    main()
