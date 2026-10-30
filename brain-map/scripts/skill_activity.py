#!/usr/bin/env python3
"""PostToolUse hook (no matcher — fires on every tool): appends one line per tool call
to ~/.agents/brain-map/activity.jsonl.

This is the live signal source for the map (template.html): the page reads each line, lights the node that did
the work, and lights a thread only from a causal pair (#843): a skill call, then a later event in the same session
within the window, on a node that skill has a thread to. So each line carries:

- ``skill``: the skill id for a Skill call, else ``"MARVIN"`` (the root), the generic "MARVIN did something" the
  map falls back to when nothing more specific matches. Kept for every older reader (DesktopLive, the Linux host).
- ``ts``: wall-clock seconds.
- ``tool``: the tool name (Skill, Bash, Edit, Read, Agent, ...).
- ``session``: Claude Code's session id, when the payload has one. Pairs are only ever made inside one session.
- ``agent``: the helper's agent id, when the call ran inside a helper (#854: the map's Work half lights that worker).
- ``file``: the file a Read/Edit/Write/NotebookEdit touched, relative to the agents folder, only when it is inside
  that folder. A path anywhere else (a project repo, a temp worktree) is left out, so it never reaches the map.

Never blocks or errors the originating tool call: any failure exits silently, matching the other PostToolUse hooks.
"""
import json
import os
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path.home() / ".agents" / "lib"))
from hook_errors import log_hook_error  # noqa: E402

ACTIVITY_PATH = Path.home() / ".agents" / "brain-map" / "activity.jsonl"
AGENTS_DIR = Path.home() / ".agents"
MAX_LINES = 500  # trim on write — this is a live-activity feed, not a log archive
FILE_KEYS = ("file_path", "notebook_path")
_AGENT_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")  # the same shape chat_helpers.py accepts


def _relative_file(tool_input: dict, agents_dir: Path):
    for key in FILE_KEYS:
        raw = tool_input.get(key)
        if not isinstance(raw, str) or not raw or not os.path.isabs(raw):
            continue
        try:
            rel = Path(os.path.normpath(raw)).relative_to(Path(os.path.normpath(str(agents_dir))))
        except ValueError:
            return None
        return rel.as_posix() if rel.parts and rel.parts[0] != ".." else None
    return None


def entry_for(payload: dict, agents_dir: Path, now: float):
    """The activity line for one hook payload, or None when there is nothing to record."""
    tool_name = payload.get("tool_name", "")
    if not isinstance(tool_name, str) or not tool_name:
        return None
    tool_input = payload.get("tool_input")
    tool_input = tool_input if isinstance(tool_input, dict) else {}
    if tool_name == "Skill":
        skill = tool_input.get("skill", "")
        if not isinstance(skill, str) or not skill:
            return None
    else:
        skill = "MARVIN"
    entry = {"skill": skill, "ts": now, "tool": tool_name}
    session = payload.get("session_id")
    if isinstance(session, str) and session:
        entry["session"] = session
    agent = payload.get("agent_id")
    if isinstance(agent, str):
        agent = agent[len("agent-"):] if agent.startswith("agent-") else agent
        if _AGENT_ID.match(agent):
            entry["agent"] = agent
    rel = _relative_file(tool_input, agents_dir)
    if rel:
        entry["file"] = rel
    return entry


def main() -> None:
    try:
        payload = json.load(sys.stdin)
    except Exception as e:
        log_hook_error("skill_activity", "parsing stdin payload", e)
        return
    if not isinstance(payload, dict):
        return
    entry = entry_for(payload, AGENTS_DIR, time.time())
    if entry is None:
        return

    try:
        ACTIVITY_PATH.parent.mkdir(parents=True, exist_ok=True)
        lines = []
        if ACTIVITY_PATH.exists():
            lines = ACTIVITY_PATH.read_text(encoding="utf-8").splitlines()
        lines.append(json.dumps(entry))
        lines = lines[-MAX_LINES:]
        ACTIVITY_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    except Exception as e:
        log_hook_error("skill_activity", f"writing activity log to {ACTIVITY_PATH}", e)
        return


if __name__ == "__main__":
    main()
