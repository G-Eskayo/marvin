#!/usr/bin/env python3
"""Autonomous fallback scheduling for the morning brief, daily digest, and research digest.

Three primary jobs run on the mac-mini at 08:30 (daily-digest), 09:00 (research-colony),
and 09:45 (morning-brief). If a primary fails or hangs, its fallback runs on the MacBook
an hour later (09:30, 10:00, 10:45) to ensure the brief is built even if the primary
fails silently.

The fallback checks:
1. If running on the primary (mac-mini): always run (local write to ~/.claude).
2. If running on a standby (MacBook): deadline passed (plus grace window), then check if primary produced output.

This handles: primary hangs, primary fails silently, primary's SSH output is stale.
"""
from __future__ import annotations

import shlex
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone, tzinfo
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))


@dataclass
class Decision:
    should_run: bool
    reason: str
    role: str = "fallback"


def _home_relative_cat(path: str | Path) -> str:
    """Return a shell command to cat a file, using $HOME if path is under home, else fully quoted.

    E.g. "/Users/giles/.claude/briefs/2026-10-24.md" → "cat $HOME/.claude/briefs/2026-10-24.md"
         "/tmp/foo.txt" → "cat '/tmp/foo.txt'"
    """
    path_str = str(path)
    home_str = str(Path.home())
    if path_str.startswith(home_str + "/"):
        # Relative to home
        rel = path_str[len(home_str) + 1:]
        return f"cat $HOME/{shlex.quote(rel)}"
    else:
        # Outside home: fully quote the absolute path
        return f"cat {shlex.quote(path_str)}"


def read_remote(path: str | Path, host: str, run=subprocess.run) -> str | None:
    """Read a file from a remote machine over SSH. Returns contents, empty string if file doesn't exist, or None on error."""
    import task_dispatch
    try:
        cmd_str = _home_relative_cat(path)
        proc = run(["ssh", *task_dispatch.SSH_OPTS, host, cmd_str], capture_output=True, text=True, timeout=10)
        if proc.returncode == 0:
            return proc.stdout
        # Exit code 1 usually means file doesn't exist (or permission denied — treat the same)
        return ""
    except (subprocess.TimeoutExpired, subprocess.SubprocessError, OSError):
        return None


def produced(path: str | Path, host: str | None = None, run=subprocess.run) -> bool:
    """Check whether a brief file has been freshly produced locally or remotely.

    "Not produced" = file doesn't exist, is empty, is unreadable, SSH unreachable, or contains
    the literal substring "(claude call failed:".
    """
    if host:
        # Read the remote file to check if it exists and is non-empty
        contents = read_remote(path, host, run=run)
        if contents is None:
            # SSH timeout or error
            return False
        if not contents:
            # Remote file missing or empty
            return False
        if "(claude call failed:" in contents:
            # Remote file contains failure placeholder
            return False
        return True
    else:
        # Local check
        try:
            path = Path(path)
            if not path.exists():
                return False
            if not path.stat().st_size:
                return False
            contents = path.read_text()
            if "(claude call failed:" in contents:
                return False
            return True
        except (OSError, PermissionError):
            return False


def past_deadline(hour: int, minute: int, now: datetime | None = None, tz: tzinfo | None = None, grace_minutes: int = 0) -> bool:
    """True if the current local time is past the given hour:minute (local wall-clock) plus grace window.

    Args:
        hour: hour of the deadline (0-23)
        minute: minute of the deadline (0-59)
        now: current time (defaults to now)
        tz: timezone for wall-clock comparison (defaults to local)
        grace_minutes: minutes after the deadline before it's considered "passed" (defaults to 0)
    """
    from datetime import timedelta
    now = now or datetime.now(timezone.utc)
    local = now.astimezone(tz)
    deadline = local.replace(hour=hour, minute=minute, second=0, microsecond=0)
    deadline_with_grace = deadline + timedelta(minutes=grace_minutes)
    return local > deadline_with_grace


def should_run(
    local_path: str | Path,
    usual_hour: int,
    usual_minute: int,
    now: datetime | None = None,
    run=subprocess.run,
    grace_minutes: int = 60,
) -> Decision:
    """Decide whether the fallback job should run.

    Args:
        local_path: path to the brief file on the local machine (e.g., ~/.claude/briefs/2026-10-24.md)
        usual_hour: hour the primary job was scheduled (e.g., 9)
        usual_minute: minute the primary job was scheduled (e.g., 45)
        now: for testing; defaults to now
        run: subprocess.run-like callable for SSH; defaults to subprocess.run
        grace_minutes: grace window in minutes after the usual time before the fallback is allowed to run (defaults to 60)

    Returns:
        Decision: (should_run, reason, role).
        - If running on the primary (mac-mini), always True with role="primary".
        - Otherwise: True if deadline (plus grace window) has passed and primary did not produce output; False otherwise.
        - On any exception, fail open: True with role="fallback".
    """
    try:
        import machine_profile
        import scanner_role
        import task_dispatch

        now = now or datetime.now(timezone.utc)
        me = machine_profile.registry_id()

        # If running on the primary, always run (we are the writer)
        if scanner_role.is_primary(me):
            return Decision(True, "running on primary (mac-mini)", role="primary")

        # Check if deadline (plus grace window) has passed
        if not past_deadline(usual_hour, usual_minute, now, grace_minutes=grace_minutes):
            return Decision(False, f"primary deadline {usual_hour:02d}:{usual_minute:02d} plus {grace_minutes}min grace window has not yet passed")

        # Deadline has passed. Check if primary has produced the file
        local_ok = produced(local_path, run=run)
        if local_ok:
            return Decision(False, "primary produced output (local), skipping fallback")

        # Try to read the file from the primary (mac-mini) over SSH
        _dev, info = scanner_role._primary_device()
        if not info:
            # No primary device in registry; fail open (run fallback)
            return Decision(True, "primary device not in registry, running fallback")

        primary_host = info["tailscale_hostname"]
        online_hosts = task_dispatch._tailscale_online_hosts()
        if primary_host not in online_hosts:
            # Primary is offline; fail open (run fallback)
            return Decision(True, "primary device is offline, running fallback")

        # Try SSH read
        remote_ok = produced(local_path, host=primary_host, run=run)
        if remote_ok:
            return Decision(False, "primary produced output (remote), skipping fallback")

        # Primary did not produce output
        return Decision(True, "primary did not produce output, running fallback")
    except Exception as exc:
        return Decision(True, f"fail-open: {exc}", role="fallback")
