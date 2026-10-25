#!/usr/bin/env python3
"""Fallback mechanism for brief generation (ADR 0067).

When a digest job normally runs on the primary (Mini), a secondary machine (MacBook)
should only build it if the primary hasn't produced output by GRACE_HOURS after the
scheduled time. Prevents double-building across machines while respecting the brief-first
design where the Mini is authoritative.

>>> from datetime import datetime, timezone, timedelta
>>> now = datetime(2026, 10, 24, 9, 0, 0, tzinfo=timezone.utc)
>>> past_deadline(datetime(2026, 10, 24, 8, 30, 0, tzinfo=timezone.utc), now)
True
>>> past_deadline(datetime(2026, 10, 24, 9, 30, 0, tzinfo=timezone.utc), now)
False

Usage:
    from brief_fallback import should_run
    if should_run("daily-digest", "08:30", out_path):
        # build and write digest
        ...
"""
from __future__ import annotations

import shlex
import subprocess
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import scanner_role  # noqa: E402
import machine_profile  # noqa: E402
import task_dispatch  # noqa: E402

GRACE = timedelta(hours=1)


def past_deadline(scheduled: datetime, now: datetime) -> bool:
    """Check if grace period has passed (scheduled time + 1 hour)."""
    deadline = scheduled + GRACE
    return now >= deadline


def _infer_remote_path(local_path: Path) -> str:
    """Convert a local path to a shell command for remote use.

    ~/.claude/daily-digest/2026-10-24.md → $HOME/.claude/daily-digest/2026-10-24.md
    (uses $HOME for cross-machine portability; different user accounts have different home paths)
    """
    home = Path.home()
    try:
        rel = local_path.relative_to(home)
        return f'"$HOME/{shlex.quote(str(rel))}"'
    except ValueError:
        # Path is not under home; use absolute path instead
        return shlex.quote(str(local_path))


def read_remote(remote_path: str, host: str, run=subprocess.run) -> str | None:
    """Read a remote file over SSH. Returns file contents or None if unreadable."""
    try:
        result = run(
            ["ssh", *task_dispatch.SSH_OPTS, host, f"cat {remote_path}"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            return result.stdout
    except Exception:
        pass
    return None


def _is_real(text: str | None) -> bool:
    """Check if text is non-empty and looks like real content (not an error message)."""
    if not text:
        return False
    stripped = text.strip()
    # Reject error messages and placeholder content
    if stripped.startswith("(") and stripped.endswith(")"):
        return False
    if "could not" in stripped.lower() or "failed" in stripped.lower():
        return False
    return len(stripped) > 20  # at least some real content


def produced(local_path: Path, host: str | None = None, run=subprocess.run) -> bool:
    """Check if a digest file exists and contains real content.

    Checks locally if host is None, else checks on the remote host.
    """
    if host is None:
        # Check locally
        if not local_path.exists():
            return False
        content = local_path.read_text()
        return _is_real(content)
    else:
        # Check remotely over SSH
        remote_path = _infer_remote_path(local_path)
        content = read_remote(remote_path, host, run=run)
        return _is_real(content)


def primary_host() -> str | None:
    """Determine the primary host's tailscale hostname.

    Returns the host string suitable for SSH (e.g. 'mac-mini' or None if not found).
    """
    for device_id, info in machine_profile.remote_devices().items():
        if scanner_role.is_primary(device_id):
            return info.get("tailscale_hostname")
    return None


def should_run(
    job_name: str,
    scheduled: str,
    out_path: Path,
    device_id: str | None = None,
    now: datetime | None = None,
    run=subprocess.run,
) -> bool:
    """Gate: should this device build the digest right now?

    Args:
        job_name: Job identifier (e.g. "daily-digest", "research-colony", "morning-brief") for logging
        scheduled: Scheduled build time as "HH:MM" (UTC)
        out_path: Output file path (e.g. ~/.claude/daily-digest/2026-10-24.md)
        device_id: This machine's device ID (defaults to machine_profile.registry_id())
        now: Current time (defaults to now)
        run: subprocess.run function (for testing)

    Returns:
        True if this device should proceed with the build:
        - False if output already exists (idempotency)
        - Always True if this is the primary device
        - True if primary hasn't produced the file and grace period has passed
        - False otherwise
    """
    now = now or datetime.now(timezone.utc)

    # Idempotency first: if output already exists, don't build again
    if produced(out_path):
        return False

    device_id = device_id or machine_profile.registry_id()

    # If this is the primary, always run
    if scanner_role.is_primary(device_id):
        return True

    # If we're not primary, only run if:
    # 1. The primary hasn't produced output, AND
    # 2. Grace period has passed

    primary = primary_host()
    if not primary:
        # Can't determine primary, fail open (allow run)
        return True

    # Check if primary has produced the file
    if produced(out_path, host=primary, run=run):
        return False

    # Parse scheduled time to datetime for deadline check
    # Create a UTC datetime for "today at scheduled time"
    try:
        hour, minute = map(int, scheduled.split(":"))
        scheduled_dt = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    except (ValueError, AttributeError):
        # Malformed scheduled time, fail open
        return True

    # If grace period has passed, we can run as fallback
    return past_deadline(scheduled_dt, now)
