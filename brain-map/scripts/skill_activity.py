#!/usr/bin/env python3
"""PostToolUse hook (no matcher — fires on every tool): appends {skill, ts}
to ~/.agents/brain-map/activity.jsonl whenever any tool fires.

This is the live signal source for DesktopLive's pulse/camera-nudge
animation — the graph reading activity.jsonl is what turns "a picture of
the structure" into "what's actually running right now". A Skill call logs
the specific skill ID, pulsing that node in the tree. Any other tool
(Bash, Edit, Write, Read, Agent, ...) logs the "MARVIN" root node instead —
template.html's triggerActivity() looks up the id in the tree and no-ops on
a miss, so a tool name that isn't a real node would otherwise be silently
dropped. Widened 2026-07-17: scoped to matcher: Skill alone, real work in a
session that never invokes a named skill (the common case — most sessions
are Bash/Edit/Read) left the visualization looking frozen for days despite
constant activity, which is exactly the "is MARVIN alive" signal this file
exists to give. Never blocks or errors the originating tool call: any
failure exits silently, matching the other three PostToolUse hooks in this
system.
"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path.home() / ".agents" / "lib"))
from hook_errors import log_hook_error  # noqa: E402

ACTIVITY_PATH = Path.home() / ".agents" / "brain-map" / "activity.jsonl"
MAX_LINES = 500  # trim on write — this is a live-activity feed, not a log archive


def main() -> None:
    try:
        payload = json.load(sys.stdin)
    except Exception as e:
        log_hook_error("skill_activity", "parsing stdin payload", e)
        return

    tool_name = payload.get("tool_name", "")
    if not tool_name:
        return
    if tool_name == "Skill":
        skill = (payload.get("tool_input") or {}).get("skill", "")
        if not skill:
            return
    else:
        skill = "MARVIN"

    entry = json.dumps({"skill": skill, "ts": time.time()})

    try:
        ACTIVITY_PATH.parent.mkdir(parents=True, exist_ok=True)
        lines = []
        if ACTIVITY_PATH.exists():
            lines = ACTIVITY_PATH.read_text(encoding="utf-8").splitlines()
        lines.append(entry)
        lines = lines[-MAX_LINES:]
        ACTIVITY_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    except Exception as e:
        log_hook_error("skill_activity", f"writing activity log to {ACTIVITY_PATH}", e)
        return


if __name__ == "__main__":
    main()
