#!/usr/bin/env python3
"""Brief fallback logic: ensure brief tasks (morning-brief, daily-digest, research-colony)
run if not already done today by the primary machine.

This module implements a cross-machine fallback pattern where the Mini runs the brief as
primary (early morning), and the MacBook runs fallback copies later in the day in case the
Mini's version didn't finish. The same logic applies to daily-digest and research-colony.

Core functions:
- should_run(): main decision point — poll the primary over SSH, decide whether to proceed locally.
- produced(): check whether a brief/digest file was successfully written and is non-empty.
- past_deadline(): check whether the current time has passed a scheduled deadline.

Decision NamedTuple: the return value from should_run() and related functions, suitable for
gating job execution (e.g., in launchd scripts).
"""
from __future__ import annotations

import json
import shlex
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import NamedTuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
import machine_profile  # noqa: E402
import scanner_role  # noqa: E402
import task_dispatch  # noqa: E402


class Decision(NamedTuple):
    """Result of should_run() or related checks: (should_proceed, reason)."""
    should_proceed: bool
    reason: str


def _infer_remote_path(local_path: str | Path) -> tuple[str, bool]:
    """Given a local ~/.claude/... path, infer the equivalent $HOME/... path for SSH exec on another machine.

    Returns (path_string, under_home) where:
    - path_string: unquoted relative path (e.g., ".claude/briefs/2026-10-24.md" or "brief.md")
    - under_home: True if path is under $HOME, False otherwise (filename fallback)

    Caller handles quoting via shlex.quote() and $HOME expansion.
    """
    path = Path(local_path)

    # If path is absolute, try to make it relative to home
    home = Path.home()
    try:
        rel = path.relative_to(home)
        return (str(rel), True)
    except ValueError:
        pass

    # Fallback: just the filename, relative to cwd (used in tests)
    return (path.name, False)


def _is_valid_content(content: str | None) -> bool:
    """Check whether content is valid (not None, not empty, not just whitespace, not a failure placeholder).

    Returns False for:
    - None or empty string
    - Whitespace-only content
    - Content containing "(claude call failed:" (quarantine placeholder)

    Returns True otherwise.
    """
    if not content or not content.strip():
        return False
    if "(claude call failed:" in content:
        return False
    return True


def read_remote(device_id: str, local_path: str | Path) -> str | None:
    """Read a file from a remote machine over SSH.

    Returns file content on success, None on failure (machine unreachable, file missing, etc.).
    device_id: registry ID (e.g., "mac-mini-1"), resolved via machine_profile.remote_devices().
    local_path: local ~/.claude/... path; converted to $HOME/... for remote exec.
    """
    devices = machine_profile.remote_devices()
    if device_id not in devices:
        return None

    info = devices[device_id]
    host = info.get("tailscale_hostname")
    if not host:
        return None

    rel, under_home = _infer_remote_path(local_path)
    cmd_path = f'"$HOME"/{shlex.quote(rel)}' if under_home else shlex.quote(rel)
    try:
        proc = subprocess.run(
            ["ssh", *task_dispatch.SSH_OPTS, host, f"cat {cmd_path}"],
            capture_output=True, text=True, timeout=15,
        )
        if proc.returncode == 0:
            return proc.stdout
    except Exception:
        pass
    return None


def produced(local_path: str | Path) -> bool:
    """Check whether a brief/digest file exists and is valid (non-empty, not a failure placeholder).

    Returns True if the file exists and has valid content, False otherwise.
    Used to detect whether a scheduled brief actually ran (as opposed to being skipped
    due to the same-day idempotency check). Never raises.
    """
    try:
        path = Path(local_path)
        if not path.exists():
            return False
        content = path.read_text()
        return _is_valid_content(content)
    except Exception:
        return False


def past_deadline(hour: int, minute: int, now: datetime | None = None) -> bool:
    """Check whether current local time has passed a given hour:minute.

    hour, minute: integers (e.g., 10, 15 for 10:15 AM).
    now: datetime override (for testing); defaults to now in local time.

    Returns True if the current time is >= the deadline, False otherwise.
    """
    now = now or datetime.now()
    current_time = (now.hour, now.minute)
    deadline = (hour, minute)
    return current_time >= deadline


def should_run(
    local_path: str | Path,
    usual_hour: int = 9,
    usual_minute: int = 0,
    now: datetime | None = None,
) -> Decision:
    """Main decision point: should this machine run the brief/digest?

    Mirrors scanner_role.should_scan()'s shape: primary (Mini) always runs;
    standby (MacBook) runs only if the primary hasn't produced the file yet.

    local_path: path to the output file (e.g., ~/.claude/briefs/2026-10-24.md).
    usual_hour, usual_minute: expected time the primary (Mini) finishes (for fallback).
    now: datetime override (for testing).

    Returns Decision(should_proceed=True, reason=...) if this machine should run,
    or Decision(should_proceed=False, reason=...) if not.
    """
    now = now or datetime.now(timezone.utc)

    # Guard against registry_id() raising; treat unknown machine as standby
    try:
        me = machine_profile.registry_id()
    except Exception:
        me = None

    # Primary (Mini) always runs
    if scanner_role.is_primary(me):
        return Decision(True, "primary: always runs")

    # Standby (MacBook): check deadline first
    local_now = now.astimezone() if now else None
    if not past_deadline(usual_hour, usual_minute, local_now):
        deadline_str = f"{usual_hour:02d}:{usual_minute:02d}"
        return Decision(False, f"standby: waiting until {deadline_str} for primary")

    # Deadline has passed; now check if primary has produced the file
    primary_dev, primary_info = scanner_role._primary_device()
    if not primary_info:
        return Decision(True, "standby: no primary found, running")

    # Check if primary is reachable
    host = primary_info.get("tailscale_hostname")
    if not host:
        return Decision(True, "standby: primary has no host info, running")

    try:
        online = task_dispatch._tailscale_online_hosts()
        if host not in online:
            return Decision(True, "standby: primary is unreachable, running")
    except Exception:
        return Decision(True, "standby: could not check primary reachability, running")

    # Primary is reachable; check if it has produced valid content
    remote_content = read_remote(primary_dev, local_path)
    if _is_valid_content(remote_content):
        return Decision(False, f"standby: primary has produced {local_path}")

    # Primary hasn't produced it, so we run
    return Decision(True, f"standby: past {usual_hour:02d}:{usual_minute:02d}, primary did not produce")
