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

Bounded (ticket 478): a remote transcript older than MAX_AGE_S is never rebuilt (a fresh state file used to let a
months-old one through), a failed generation backs off FAIL_BACKOFF_S before it's tried again, and one hung remote
only skips itself. The surfaced handoff is chosen by its content date and its claims are checked first
(lib/resume_check.py, marvin#1221), so a rebuilt handoff can't relay a solved problem as current.
"""
from __future__ import annotations
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path.home() / ".agents" / "lib"))
from machine_profile import remote_devices  # noqa: E402
from task_dispatch import dispatch  # noqa: E402
import machine_profile  # noqa: E402
import resume_check  # noqa: E402

STATE_PATH = Path.home() / ".claude" / ".session-continuity-state.json"
CLAUDE_DIR_REL = ".claude"
# $HOME, not a literal path: these strings run in a shell on whichever machine is checked, and the home
# directory differs between machines (ADR 0069).
VENV_PYTHON = "$HOME/.agents/venv/bin/python"
GENERATE_SCRIPT = "$HOME/.agents/skills/handoff/scripts/generate_handoff_from_transcript.py"
CODE_SYNC = "$HOME/.agents/lib/code_sync.py"
MAX_AGE_S = 24 * 3600        # "just switched machines" is hours, not weeks (ticket 478)
FAIL_BACKOFF_S = 3600        # a failed generation isn't re-paid on every session start
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
    try:
        result = subprocess.run(
            ["ssh", *SSH_OPTS, host, f"{VENV_PYTHON} $HOME/.agents/skills/handoff/scripts/find_freshest_session.py"],
            capture_output=True, text=True, timeout=15,
        )
    except (subprocess.TimeoutExpired, OSError):
        return None  # one hung remote only skips itself (ticket 478)
    if result is None or result.returncode != 0 or not result.stdout.strip():
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
    body = resume_check.resume_prompt(text)
    if not body:
        return
    now = datetime.now(timezone.utc)
    when = resume_check.handoff_time(handoff_path, now)
    try:
        report = resume_check.check(text, when, now=now)
    except Exception as exc:  # noqa: BLE001  (labelled, never silent)
        report = resume_check.Report("unverified", when, reason=f"the check failed ({exc.__class__.__name__})")
    resume_check.log_run(report, handoff=handoff_path, where="remote-resume", machine=machine_profile.machine_label())
    bar = "=" * 64
    print(f"\n{bar}\n📋 Picked up from where you left off — resume prompt:\n{resume_check.heading_line(report)}\n{bar}")
    print(resume_check.strike_urgent(body, report))
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
    now = time.time()
    if now - freshest["mtime"] > MAX_AGE_S:
        return  # an old remote session isn't "just switched machines"
    if now - state.get(f"{device_id}:failed_at", 0) < FAIL_BACKOFF_S:
        return  # it failed recently; don't re-pay up to 180 s on every session start

    generate_and_push = f"{VENV_PYTHON} {GENERATE_SCRIPT} {freshest['transcript_path']} && {VENV_PYTHON} {CODE_SYNC} push $HOME/{CLAUDE_DIR_REL}"
    result = dispatch(generate_and_push, target=device_id, mode="sync", timeout=180, task_label="generate handoff from live session")
    if not result.ok:
        state[f"{device_id}:failed_at"] = now
        _save_state(state)
        return  # fail quiet, but remembered: the back-off above stops the retry storm
    state.pop(f"{device_id}:failed_at", None)

    # Pull to get the freshly-pushed handoff, then surface it. Deliberately
    # not a before/after filename diff — generate_handoff_from_transcript.py
    # names files with only minute granularity, so two escalations inside
    # the same UTC minute overwrite the same filename; a "which names are
    # new" comparison misses that as a real update. Since we're already past
    # the freshness gate above, we know a generation happened — take
    # whichever handoff is newest right now, by its content date (as_of) first, mtime breaking ties.
    # Local, no shell: real paths, not the $HOME strings above (those crashed this step, 2026-10-25).
    agents = Path.home() / ".agents"
    try:
        subprocess.run([str(agents / "venv" / "bin" / "python"), str(agents / "lib" / "code_sync.py"), "pull",
                        str(Path.home() / CLAUDE_DIR_REL)], capture_output=True)
    except OSError:
        pass  # fail quiet: surface whatever handoff is already here
    ranked = resume_check.ranked_handoffs(Path.home() / ".claude" / "handoffs")
    for handoff_path, _ in ranked:
        try:
            text = handoff_path.read_text(errors="ignore")
        except OSError:
            continue
        if resume_check.resume_prompt(text):
            _surface_resume_prompt(handoff_path)
            break
    else:
        print(f"rebuilt a handoff on {device_id} but found no resume prompt in handoffs/")

    state[device_id] = freshest["mtime"]
    _save_state(state)


if __name__ == "__main__":
    main()
