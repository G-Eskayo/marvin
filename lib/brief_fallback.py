#!/usr/bin/env python3
"""Resilience layer for morning-brief, daily-digest, and research-colony (ADR 0066).

When a scheduled job (brief, digest, colony) runs on the wrong machine (primary offline, fallback
doesn't know to run), it produces nothing. This module provides a gating mechanism so jobs can skip
when their content has already been produced on another machine, and a health-check function to detect
when a deadline-constrained job hasn't produced in too long.

Design:
- Jobs gate on whether their output already exists and was produced on another machine (content check,
  via .built-by sidecar; if standby and output missing, can SSH-read from primary).
- A fallback job runs *after* the primary's scheduled time has elapsed (e.g., fallback runs 1h after
  primary), ensuring the primary had its chance.
- Deadlines are soft (warn on health check, yellow), hard (warn + escalate, red).
- The system is resilient: no fallback → still red (detected by health check), but interactive work
  continues (no automated alarm or retry, human-in-the-loop per policy).

Terminology:
- "producer": the machine that wrote a specific file (inferred from its .built-by sidecar file). The
  .built-by file is attribution-only; it does not affect gating (content does).
- "produced": the output file exists and its content was produced elsewhere (content check, not attribution).
- "deadline": a time when the job *should* have run. Soft deadlines trigger yellow in health;
  hard deadlines (specified in a Decision) trigger red.
"""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import NamedTuple

sys.path.insert(0, str(Path(__file__).resolve().parent))

import scanner_role  # noqa: E402
import machine_profile  # noqa: E402
import task_dispatch  # noqa: E402


class Decision(NamedTuple):
    """A scheduled job's target deployment and timing (ADR 0066, Decisions section)."""
    name: str  # e.g. "morning-brief", "daily-digest", "research-colony"
    primary_machine: str  # e.g. "mac-mini"
    primary_hour: int
    primary_minute: int
    fallback_machine: str  # e.g. "macbook-pro"
    fallback_hour: int
    fallback_minute: int
    soft_deadline_hours: int  # yellow in health check
    hard_deadline_hours: int | None  # red in health check (None = no hard deadline)


def _infer_remote_path(local_path: Path, device_id: str) -> str:
    """The same file path on a remote machine, as it sees its own filesystem.
    For $HOME-relative paths, use SSH 'echo $HOME' style expansion; for absolute paths, return as-is.
    """
    if local_path.is_absolute():
        # Absolute paths (unlikely for briefs, but handle correctly anyway).
        return str(local_path)
    # Relative to $HOME: re-root on the remote side.
    home_part = str(local_path)
    return f"$HOME/{home_part.removeprefix(str(Path.home()) + '/')}"


def read_remote(local_path: Path, device_id: str, timeout_sec: int = 15) -> str | None:
    """Read a file from another machine via SSH, returning its contents or None if unreachable/not-found."""
    devices = machine_profile.remote_devices()
    if device_id not in devices:
        return None
    info = devices[device_id]
    host = info.get("tailscale_hostname")
    if not host:
        return None
    # Check if the host is even online before trying to read.
    if host not in task_dispatch._tailscale_online_hosts():
        return None

    remote_path = _infer_remote_path(local_path, device_id)
    try:
        proc = subprocess.run(
            ["ssh", *task_dispatch.SSH_OPTS, host, f"cat '{remote_path}'"],
            capture_output=True, text=True, timeout=timeout_sec,
        )
        if proc.returncode == 0:
            return proc.stdout
        return None
    except subprocess.TimeoutExpired:
        return None
    except Exception:
        return None


def mark_built(path: Path) -> None:
    """Write the .built-by sidecar before writing the body. Identifies which machine built this output."""
    sidecar = path.parent / f"{path.name}.built-by"
    builder_id = machine_profile.registry_id()
    sidecar.write_text(builder_id)


def builder_of(path: Path) -> str | None:
    """Return the machine ID that built this file, or None if not found."""
    sidecar = path.parent / f"{path.name}.built-by"
    if not sidecar.exists():
        return None
    try:
        return sidecar.read_text().strip()
    except Exception:
        return None


def produced_locally(path: Path) -> bool:
    """True if the file exists locally (not checking if it was produced by another machine).
    Use this to gate operations that don't care about who built it.
    """
    return path.exists()


def _home_relative(path: Path) -> Path:
    """Return path relative to $HOME, preserving subdirectories. For SSH reroot."""
    if path.is_absolute() and path.parts[0] == "/" and Path.home() in path.parents:
        return path.relative_to(Path.home())
    return path


def produced(path: Path) -> bool:
    """True if the output's content was already produced (check local first, then remote if standby).
    Used to gate scheduled jobs: if the brief/digest/colony was already produced by another machine,
    the standby should skip to avoid duplicates and overlapped execution.
    """
    # First: check if the content is present locally (with sidecar or legacy no-sidecar).
    if produced_locally(path):
        sidecar = path.parent / f"{path.name}.built-by"
        if not sidecar.exists():
            # File exists but no sidecar — assume it's ours (legacy brief from before we added sidecars).
            # Jobs gate on 'produced()', so a file with no sidecar is treated as already produced,
            # which is safe: the fallback will skip, and if the file is stale, health check will catch it.
            return True
        try:
            builder = sidecar.read_text().strip()
            my_id = machine_profile.registry_id()
            return builder != my_id
        except Exception:
            # Malformed or unreadable sidecar — assume the file is OK (be lenient).
            return True

    # Second: if I'm not the primary, check if the primary has produced it remotely.
    my_id = machine_profile.registry_id()
    if not scanner_role.is_primary(my_id):
        # Find the primary machine from remote_macs() and try to read from it.
        for mac_id in machine_profile.remote_macs().keys():
            content = read_remote(path, mac_id)
            if content is not None:
                return True

    # File not found locally and (I'm primary or primary is offline).
    return False


def past_deadline(path: Path, deadline_hours: int, usual_hour: int, usual_minute: int, now: datetime | None = None) -> bool:
    """True if a file hasn't been produced AND we've passed the deadline.
    The deadline is computed as: today at usual_hour:usual_minute (local), plus deadline_hours.
    Used by health check: `past_deadline(brief_path, 4, 9, 45)` = red if the brief wasn't built by 13:45 (9:45 + 4h).
    """
    if produced(path):
        return False

    # Compute the anchor time: today at usual_hour:usual_minute in the local timezone.
    now = now or datetime.now(timezone.utc).astimezone()
    anchor = now.replace(hour=usual_hour, minute=usual_minute, second=0, microsecond=0)
    deadline = anchor + timedelta(hours=deadline_hours)

    # Return True if we've passed the deadline.
    return now >= deadline


def health_severity(
    path: Path,
    usual_hour: int,
    usual_minute: int,
    soft_deadline_hours: int,
    hard_deadline_hours: int | None = None,
    now: datetime | None = None,
) -> str:
    """Assess the health of a scheduled output for the health check.
    Returns 'green' (produced recently), 'yellow' (past soft deadline), or 'red' (past hard deadline).
    Deadline is computed as: today at usual_hour:usual_minute + deadline_hours (local time).
    """
    if produced(path):
        return "green"
    if hard_deadline_hours is not None and past_deadline(path, hard_deadline_hours, usual_hour, usual_minute, now):
        return "red"
    if past_deadline(path, soft_deadline_hours, usual_hour, usual_minute, now):
        return "yellow"
    return "green"


def should_run(
    local_path: Path,
    usual_hour: int,
    usual_minute: int,
    fallback_offset_hours: int = 1,
) -> bool:
    """Gate for a scheduled job: run if the output hasn't been produced yet, OR if we're the fallback
    and the primary's time has passed.

    - If `produced(local_path)` is True: skip (another machine already built it today).
    - If we're the primary (per scanner_role.is_primary): run (primary always runs).
    - If we're the fallback and it's at or past (usual_hour + fallback_offset_hours): run.
    - Otherwise: skip (let the primary have its chance).
    """
    # First: if it's already produced, don't run.
    if produced(local_path):
        return False

    my_id = machine_profile.registry_id()
    # Second: if we're the primary, always run.
    if scanner_role.is_primary(my_id):
        return True

    # Third: if we're the standby, check if it's time for fallback (past primary's scheduled time).
    now = datetime.now(timezone.utc).astimezone()
    primary_time = now.replace(hour=usual_hour, minute=usual_minute, second=0, microsecond=0)
    fallback_time = primary_time + timedelta(hours=fallback_offset_hours)
    return now >= fallback_time


if __name__ == "__main__":
    # Simple test: print whether the brief should be produced on this machine.
    if len(sys.argv) > 1 and sys.argv[1] == "test":
        briefs = Path.home() / ".claude" / "briefs"
        today = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d")
        path = briefs / f"{today}.md"
        print(f"Brief path: {path}")
        print(f"Produced: {produced(path)}")
        print(f"Should run: {should_run(path, 9, 45)}")
    else:
        sys.exit("usage: brief_fallback.py test")
