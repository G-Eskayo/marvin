#!/usr/bin/env python3
"""Fallback builder gate for the morning brief, daily digest, and research colony.

One machine (the Mini, the primary) is responsible for each output. The other (the laptop)
only builds if the primary has gone quiet: unreachable, or reachable but its heartbeat/
output is stale. Follows the same shape as scanner_role.should_scan() but checks dated
artifacts (digest files) instead of liveness heartbeats.

Each call site (daily_digest.main(), research_digest.generate(), morning_brief.build CLI)
invokes should_run() before building. The decision is deterministic: call it independently on
both machines, get the same answer (based only on local wall-clock and a stale-check of the
primary's actual output file, read live over SSH).
"""
from __future__ import annotations
import json
import shlex
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import NamedTuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
from scanner_role import is_primary  # noqa: E402
import task_dispatch  # noqa: E402
import machine_profile  # noqa: E402


class Decision(NamedTuple):
    should_build: bool
    reason: str


def _infer_remote_path(local_path: Path) -> str:
    """Infer the remote path for a local path. Generic: works for any home-relative path."""
    home = Path.home()
    try:
        # Try to express the path relative to home
        rel_path = local_path.relative_to(home)
        return f"$HOME/{rel_path}"
    except ValueError:
        # Path is not under home; fall back to just the filename
        return f"$HOME/.claude/{local_path.name}"


def read_remote(remote_path: str, host: str | None = None, run=subprocess.run) -> str | None:
    """Live SSH read of a file from the primary machine. Returns file content on success,
    None on any failure (unreachable, permission denied, file not found, SSH timeout, etc.).
    Fails open: a read error means we'll conservatively assume the primary hasn't produced
    anything yet, so the fallback will attempt to build."""
    if host is None:
        try:
            # Find the primary's Tailscale hostname
            for dev_id, info in machine_profile.remote_devices().items():
                if is_primary(dev_id):
                    host = info.get("tailscale_hostname")
                    break
        except Exception:
            # Registry lookup failed
            return None

        if not host:
            return None

    try:
        # Handle $HOME/ paths: split them so the shell expands $HOME, but safely quote the rest
        if remote_path.startswith("$HOME/"):
            quoted_path = "$HOME/" + shlex.quote(remote_path[6:])
        else:
            quoted_path = shlex.quote(remote_path)

        result = run(
            ["ssh", *task_dispatch.SSH_OPTS, host, f"cat {quoted_path}"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if result.returncode == 0:
            return result.stdout
        return None
    except Exception:
        return None


def produced(local_path: Path, remote_path: str | None = None, host: str | None = None,
             run=subprocess.run) -> bool:
    """Has the output file been produced today? Checks the local copy first, then
    falls back to reading the remote copy live if the local doesn't exist.
    Returns False (not produced) if:
    - File doesn't exist locally or remotely
    - File is empty
    - File contains only whitespace
    - File content is a placeholder error string (e.g. "(claude call failed: ...)")
    - File is unreadable (permission error, etc.)
    Never raises; any error means "not produced yet, try building."""
    # Local check first
    if local_path.exists():
        try:
            content = local_path.read_text()
            if not content or not content.strip():
                return False
            # Detect failure placeholders (from daily_digest.py and research_digest.py)
            if "(claude call failed:" in content:
                return False
            if "_Quarantined by safety-monitor" in content:
                # Quarantined counts as produced — the safety check is an outcome, not an outage
                return True
            return True
        except Exception:
            # Local file unreadable; fall through to remote check
            pass

    # Remote check if local is missing/failed
    if remote_path is None:
        remote_path = _infer_remote_path(local_path)

    remote_content = read_remote(remote_path, host, run=run)
    if remote_content:
        if not remote_content.strip():
            return False
        if "(claude call failed:" in remote_content:
            return False
        if "_Quarantined by safety-monitor" in remote_content:
            return True
        return True

    return False


def past_deadline(now: datetime, usual_hour: int = 8, usual_minute: int = 30,
                  grace_minutes: int = 60) -> bool:
    """Has the primary's usual scheduled time (plus grace period) passed?
    Pure local-clock comparison — never checks the remote machine's clock.
    Grace period lets the primary finish if it starts slightly late."""
    from datetime import timedelta
    # Convert to local wall-clock time before comparing
    local_now = now.astimezone()
    deadline = local_now.replace(hour=usual_hour, minute=usual_minute, second=0, microsecond=0)
    deadline_with_grace = deadline + timedelta(minutes=grace_minutes)
    return local_now >= deadline_with_grace


def should_run(device_id: str | None = None, now: datetime | None = None, local_path: Path | None = None,
               remote_path: str | None = None, usual_hour: int = 8, usual_minute: int = 30,
               grace_minutes: int = 60, run=subprocess.run) -> Decision:
    """Should this machine build the output? Mirrors scanner_role.should_scan().
    Returns (bool, reason_string). Both machines call this independently and get the same answer.

    Args:
        device_id: This machine's ID (defaults to machine_profile.registry_id())
        now: Current time (defaults to now UTC)
        local_path: Path to check locally (used for testing; callers pass the actual output path)
        remote_path: Path to check on the primary (defaults to inferred from local_path)
        usual_hour: Hour of day (local time) when build is scheduled
        usual_minute: Minute of hour when build is scheduled
        grace_minutes: Grace period after usual time before fallback activates
        run: Subprocess runner (for testing/mocking)
    """
    device_id = device_id or machine_profile.registry_id()
    now = now or datetime.now(timezone.utc)

    if is_primary(device_id):
        return Decision(True, "primary")

    # Standby: check if we should cover for the primary
    if not past_deadline(now, usual_hour=usual_hour, usual_minute=usual_minute, grace_minutes=grace_minutes):
        return Decision(False, f"standby: before deadline ({now.astimezone().strftime('%H:%M')} < {usual_hour:02d}:{usual_minute:02d} + {grace_minutes}m)")

    if local_path and produced(local_path, remote_path, run=run):
        return Decision(False, "standby: primary already produced")

    return Decision(True, "fallback: covering for the primary")
