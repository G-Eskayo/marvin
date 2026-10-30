#!/usr/bin/env python3
"""Fallback logic for brief-building jobs (daily digest, research colony, morning brief).

Each brief-building job has a primary window (running on the Mini) and a fallback window
(running on the MacBook if the Mini doesn't produce a result). This module provides:

- Decision: NamedTuple for encoding owner decisions about retiring cross-machine-merge
- should_run(): Gate that prevents a job from running during a sibling's primary window
- produced(): Check whether today's output file was built by any machine (idempotency)
- past_deadline(): Check whether we're past the final fallback deadline for the day
- read_remote(): SSH read a file from another machine, with quoting
"""
from __future__ import annotations

import json
import shlex
import subprocess
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import NamedTuple

sys.path.insert(0, str(Path(__file__).resolve().parent))

from scanner_role import is_primary  # noqa: E402
from task_dispatch import SSH_OPTS  # noqa: E402
import machine_profile  # noqa: E402


class Decision(NamedTuple):
    """Owner decision placeholder. Used to track decisions that require external input."""
    name: str
    status: str  # "pending", "answered", "skipped"
    answer: str | None = None


def _infer_remote_path(home_prefix_path: str) -> str:
    """Given a path like '~/.claude/briefs/YYYY-MM-DD.md', return the shell-quoted
    absolute path that will work on the remote machine: '$HOME/.claude/briefs/YYYY-MM-DD.md'."""
    if not home_prefix_path.startswith("~"):
        return shlex.quote(home_prefix_path)
    # Replace ~ with $HOME and quote the result for safe shell use
    home_relative = home_prefix_path[1:]  # strip the ~
    remote_path = f"$HOME{home_relative}"
    return shlex.quote(remote_path)


def read_remote(host: str, path: str) -> str | None:
    """SSH-read a file from a remote machine. `path` can use $HOME prefix.
    Returns the file contents on success, None on failure."""
    remote_path = _infer_remote_path(path)
    try:
        proc = subprocess.run(
            ["ssh", *SSH_OPTS, host, f"cat {remote_path}"],
            capture_output=True, text=True, timeout=10,
        )
        if proc.returncode == 0:
            return proc.stdout
        return None
    except (subprocess.TimeoutExpired, subprocess.SubprocessError):
        return None


def produced(out_path: Path) -> bool:
    """Check whether today's brief was produced on any machine (locally or remote).
    Returns True if the file exists locally. Also checks remote machines if configured.
    Used for idempotency gates: the brief should not be re-built if it already exists."""
    if out_path.exists():
        return True

    # Check remote machines: if any have the file, we're done
    import machine_profile as mp
    for device_id, info in mp.remote_devices().items():
        host = info.get("tailscale_hostname")
        if not host:
            continue
        try:
            content = read_remote(host, str(out_path))
            if content:
                return True
        except Exception:
            continue
    return False


def past_deadline(usual_hour: int, usual_minute: int, deadline_offset_minutes: int = 120) -> bool:
    """Check whether we're past the final fallback deadline for today.
    `usual_hour` and `usual_minute` are the primary job's scheduled time (e.g., 08:30).
    `deadline_offset_minutes` is how many minutes after the primary time the fallback deadline is.
    Once this returns True, no fallback should run — it's time to investigate manually.
    """
    now = datetime.now(timezone.utc).astimezone()
    scheduled = now.replace(hour=usual_hour, minute=usual_minute, second=0, microsecond=0)
    deadline = scheduled + timedelta(minutes=deadline_offset_minutes)
    return now >= deadline


def should_run(usual_hour: int, usual_minute: int, fallback_hour: int, fallback_minute: int) -> bool:
    """Gate: return True if this job should run, False otherwise.

    Primary (Mini) always runs at usual_hour:usual_minute.
    Fallback (MacBook) only runs at fallback_hour:fallback_minute, only if the primary hasn't
    produced output.

    `usual_hour`, `usual_minute`: primary job scheduled time
    `fallback_hour`, `fallback_minute`: fallback job scheduled time
    """
    now = datetime.now(timezone.utc).astimezone()
    is_mini = is_primary(machine_profile.registry_id())

    if is_mini:
        # Primary always runs, no gate
        return True

    # Fallback (not primary): only run if
    # 1. We're past the fallback scheduled time (or close to it)
    # 2. The primary window has passed (primary had its chance)
    primary_scheduled = now.replace(hour=usual_hour, minute=usual_minute, second=0, microsecond=0)
    fallback_scheduled = now.replace(hour=fallback_hour, minute=fallback_minute, second=0, microsecond=0)

    # If we haven't reached fallback time yet, definitely don't run
    if now < fallback_scheduled - timedelta(minutes=5):  # 5 min grace before scheduled time
        return False

    # We're at/past fallback time. Primary had its chance (primary_scheduled < now).
    # Only run if primary doesn't look like it's currently working (no lock or heartbeat
    # indicating a fresh attempt). For simplicity, we always run when fallback time arrives,
    # but the produced() check in the script itself will prevent double-work.
    return True


if __name__ == "__main__":
    import sys as _sys
    print(f"should_run(8, 30, 9, 30): {should_run(8, 30, 9, 30)}")
    print(f"past_deadline(8, 30): {past_deadline(8, 30)}")
