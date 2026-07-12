#!/usr/bin/env python3
"""SessionStart hook: arrival-triggered, on-demand session continuity.

The core idea — flip departure-triggered handoff automation (guess when
Gil is "leaving" a machine) into arrival-triggered (react when he actually
shows up somewhere else). Nothing has to happen on the machine he's
leaving; walking away is enough. The moment a new session starts here, this
reaches back to every other known machine, asks "what were you just doing"
(find_freshest_session.py, a cheap `claude agents --json` + `find` check —
no tokens spent), and only escalates to the expensive part (a detached
claude -p call reconstructing a handoff from the live transcript, via
generate_handoff_from_transcript.py) if something's actually newer than
the last handoff this machine already pulled.

State (~/.claude/.session-continuity-state.json, machine-local, NOT
synced — this is about *this* machine's own view of what it's already
seen) tracks the transcript mtime last acted on, per remote device, so a
quiet remote doesn't get poked on every single session start.

Bounded synchronous wait (not fire-and-forget): the whole point is the
resume prompt being there when the session opens, not a notification that
might get missed. Only pays the ~30-90s cost on the actual "just switched
machines" moment — every other session start is the cheap check only.
"""
from __future__ import annotations
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path.home() / ".agents" / "lib"))
from machine_profile import remote_devices  # noqa: E402
from task_dispatch import dispatch  # noqa: E402

STATE_PATH = Path.home() / ".claude" / ".session-continuity-state.json"
CLAUDE_DIR_REL = ".claude"
VENV_PYTHON = "/Users/gileskayo/.agents/venv/bin/python"
GENERATE_SCRIPT = "/Users/gileskayo/.agents/skills/handoff/scripts/generate_handoff_from_transcript.py"
CODE_SYNC = "/Users/gileskayo/.agents/lib/code_sync.py"
SSH_OPTS = ["-o", "ConnectTimeout=5", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=accept-new"]


def _load_state() -> dict:
    try:
        return json.loads(STATE_PATH.read_text())
    except Exception:
        return {}


def _save_state(state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=2))


def _check_remote(device_id: str, host: str) -> dict | None:
    result = subprocess.run(
        ["ssh", *SSH_OPTS, host, f"{VENV_PYTHON} /Users/gileskayo/.agents/skills/handoff/scripts/find_freshest_session.py"],
        capture_output=True, text=True, timeout=15,
    )
    if result.returncode != 0 or not result.stdout.strip():
        return None
    try:
        info = json.loads(result.stdout)
    except Exception:
        return None
    if not info:
        return None
    info["device_id"] = device_id
    info["host"] = host
    return info


def _surface_resume_prompt(handoff_path: Path) -> None:
    try:
        text = handoff_path.read_text(errors="ignore")
    except Exception:
        return
    m = re.search(r"##\s*Resume prompt\s*\n(.*)$", text, re.DOTALL | re.IGNORECASE)
    body = (m.group(1) if m else "").strip().strip("-").strip()
    if not body:
        return
    bar = "=" * 64
    print(f"\n{bar}\n📋 Picked up from where you left off — resume prompt:\n{bar}")
    print(body)
    print(f"{bar}\n(source: {handoff_path})")


def main() -> None:
    remotes = remote_devices()
    if not remotes:
        return

    state = _load_state()
    candidates = []
    for device_id, info in remotes.items():
        host = info.get("tailscale_hostname")
        if not host:
            continue
        result = _check_remote(device_id, host)
        if result:
            candidates.append(result)

    if not candidates:
        return

    freshest = max(candidates, key=lambda c: c["mtime"])
    device_id = freshest["device_id"]
    last_seen = state.get(device_id, 0)
    if freshest["mtime"] <= last_seen:
        return  # nothing new since we last checked this machine

    generate_and_push = f"{VENV_PYTHON} {GENERATE_SCRIPT} {freshest['transcript_path']} && {VENV_PYTHON} {CODE_SYNC} push /Users/gileskayo/{CLAUDE_DIR_REL}"
    result = dispatch(generate_and_push, target=device_id, mode="sync", timeout=180, task_label="generate handoff from live session")
    if not result.ok:
        return  # fail quiet — same as any other SSH-unreachable case elsewhere in MARVIN

    # Pull to get the freshly-pushed handoff, then surface it.
    before = sorted((Path.home() / ".claude" / "handoffs").glob("*.md")) if (Path.home() / ".claude" / "handoffs").is_dir() else []
    subprocess.run([VENV_PYTHON, CODE_SYNC, "pull", str(Path.home() / ".claude")], capture_output=True)
    after_dir = Path.home() / ".claude" / "handoffs"
    after = sorted(after_dir.glob("*.md")) if after_dir.is_dir() else []
    new_files = [f for f in after if f not in before]
    if new_files:
        _surface_resume_prompt(max(new_files, key=lambda p: p.stat().st_mtime))

    state[device_id] = freshest["mtime"]
    _save_state(state)


if __name__ == "__main__":
    main()
