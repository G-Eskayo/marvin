#!/usr/bin/env python3
"""Fallback brief builder — standby machine covers when primary is down.

The morning brief, daily digest, and research digest are built by specific
launchd jobs on the primary machine. If the primary is down or late, the
standby machine checks whether today's output exists, and if not, builds it.

This module provides the logic: identifying machine roles, checking deadlines,
and deciding whether the fallback should run.
"""
from __future__ import annotations

import shlex
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import machine_profile  # noqa: E402
import scanner_role  # noqa: E402
from task_dispatch import SSH_OPTS  # noqa: E402


def _infer_remote_path(local_path: Path | str) -> tuple[str, str]:
    """Split a local path into its $HOME prefix and the remainder.
    Returns (home_prefix, remainder) where home_prefix is $HOME and remainder
    is the path relative to it.

    Example:
        /Users/giles/.claude/briefs/2026-10-25.md
        -> ($HOME, ".claude/briefs/2026-10-25.md")

    The caller constructs: cat "$HOME"/<remainder> to read it remotely.
    Fails closed (raises ValueError) for paths outside $HOME.
    """
    local_path = Path(local_path)
    home = Path.home()
    try:
        rel = local_path.relative_to(home)
    except ValueError:
        raise ValueError(f"{local_path} is not under {home}")
    return "$HOME", str(rel)


def read_remote(local_path: Path | str, host: str, run=subprocess.run) -> str | None:
    """Read a file from a remote machine via SSH.

    Args:
        local_path: The path on the local machine (which would be at the same
                    path on the remote machine). Must be under $HOME.
        host: SSH host (e.g. "gils-mac-mini").
        run: subprocess.run or a mock for testing.

    Returns:
        The file contents if successful, or None if:
        - Path is outside $HOME
        - SSH/timeout error
        - File doesn't exist or can't be read
        - Registry lookup fails
    """
    try:
        home_prefix, remainder = _infer_remote_path(local_path)
    except ValueError:
        return None  # path outside home

    cmd = ["ssh", *SSH_OPTS, host, f"cat {home_prefix}/{shlex.quote(remainder)}"]
    try:
        result = run(cmd, capture_output=True, text=True, timeout=10)
        return result.stdout if result.returncode == 0 else None
    except (subprocess.TimeoutExpired, OSError):
        return None


def produced(path: Path | str) -> bool:
    """Check whether a file actually contains produced output.

    Returns False if:
    - The file doesn't exist
    - The file is empty
    - The file contains only whitespace
    - The file contains a claude call failure marker "(claude call failed:"

    Returns True otherwise.
    """
    path = Path(path)
    if not path.exists():
        return False
    try:
        content = path.read_text()
    except OSError:
        return False
    if not content.strip():
        return False
    if "(claude call failed:" in content:
        return False
    return True


def past_deadline(now: datetime, usual_hour: int, usual_minute: int,
                  grace_minutes: int = 60) -> bool:
    """Check whether we're past the usual time plus grace period.

    Args:
        now: Current time (assumed local wall-clock time, matching StartCalendarInterval).
        usual_hour: Usual run hour (0-23, local time).
        usual_minute: Usual run minute (0-59, local time).
        grace_minutes: Minutes of grace after the usual time.

    Returns:
        True if now is past usual_time + grace_minutes in local time.
    """
    now = now.astimezone()
    deadline = now.replace(hour=usual_hour, minute=usual_minute,
                           second=0, microsecond=0)
    grace_deadline = deadline + timedelta(minutes=grace_minutes)
    return now >= grace_deadline


def should_run(local_path: Path | str, usual_hour: int, usual_minute: int,
               now: datetime | None = None, run=subprocess.run) \
        -> tuple[bool, str]:
    """Decide whether to build the brief on this machine.

    The primary (mac-mini) always runs. The standby (MacBook) runs only if:
    - The deadline has passed (usual_time + 60min grace)
    - AND the brief hasn't been produced locally
    - AND the primary hasn't produced it (checked over SSH)

    Args:
        local_path: Path to check (e.g., ~/.claude/briefs/2026-10-25.md).
        usual_hour: When the primary usually builds (UTC hour, 0-23).
        usual_minute: When the primary usually builds (UTC minute, 0-59).
        now: Current time (defaults to now; normally passed for testing).
        run: subprocess.run or mock for testing.

    Returns:
        (bool, str): (should_run, reason)
    """
    now = now or datetime.now(timezone.utc)
    my_id = machine_profile.registry_id()

    if scanner_role.is_primary(my_id):
        return (True, "")

    # I'm standby. Check deadline first.
    if not past_deadline(now, usual_hour, usual_minute):
        return (False, f"standby: primary hasn't reached deadline yet ({usual_hour:02d}:{usual_minute:02d} + 60min grace)")

    # Past deadline. Check local state.
    if produced(local_path):
        return (False, "already produced locally")

    # Local is missing/empty. Check if primary built it.
    primary_id = None
    for device_id in machine_profile.remote_macs().keys():
        if scanner_role.is_primary(device_id):
            primary_id = device_id
            break

    if primary_id:
        primary_info = machine_profile.remote_macs().get(primary_id, {})
        primary_host = primary_info.get("tailscale_hostname")
        if primary_host:
            content = read_remote(local_path, primary_host, run=run)
            if content:
                return (False, "fallback: primary already built it")

    return (True, "fallback: covering for the primary")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--path", required=True, help="Path to check")
    parser.add_argument("--hour", type=int, required=True, help="Usual run hour (UTC)")
    parser.add_argument("--minute", type=int, required=True, help="Usual run minute (UTC)")
    args = parser.parse_args()

    should, reason = should_run(args.path, args.hour, args.minute)
    print(f"should_run={should} reason={reason}")
    sys.exit(0 if should else 1)
