#!/usr/bin/env python3
"""Fallback system for morning-brief, daily-digest, and research-colony jobs.

When the primary builder (mini) misses its deadline, the standby machine (laptop) picks up
the work after a grace period. This module decides whether the fallback should run and reads
the primary's output if it exists.

Implements a pattern analogous to scanner_role.decide() for the three periodic digests:
- morning-brief: primary=mini, fallback=laptop, primary deadline 09:45 (grace +60min)
- daily-digest: primary=mini, fallback=laptop, primary deadline 08:30 (grace +60min)
- research-colony: primary=mini, fallback=laptop, primary deadline 09:00 (grace +60min)
"""
from __future__ import annotations
import shlex
import subprocess
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import machine_profile  # noqa: E402
import scanner_role  # noqa: E402
import task_dispatch  # noqa: E402

HOME = Path.home()


def _infer_remote_path(local_path: Path, local_file_suffix: str = "") -> str:
    """Infer the remote path for a local brief/digest file.

    local_path: ~/claude/briefs/2026-10-24.md or ~/claude/daily-digest/2026-10-24.md
    Returns: $HOME/.claude/briefs/2026-10-24.md as a shell-safe string for the remote machine.
    """
    try:
        relative = local_path.relative_to(HOME)
        return str(Path("$HOME") / relative)
    except ValueError:
        return ""


def _is_valid_content(content: str | None) -> bool:
    """Check if content is valid: non-empty and no failure markers."""
    if not content or not content.strip():
        return False
    if "(claude call failed:" in content:
        return False
    return True


def _quote_remote_path(remote_path: str) -> str:
    """Quote a remote path for shell execution, but preserve $HOME prefix.

    Quotes everything except a literal $HOME/ prefix so it stays variable-expanded
    on the remote machine.
    """
    if remote_path.startswith("$HOME/"):
        return "$HOME/" + shlex.quote(remote_path[6:])
    return shlex.quote(remote_path)


def produced(path: Path) -> bool:
    """Check if a file was actually produced (has content and no failure markers).

    Returns True if:
    - File exists
    - Has non-empty content
    - Does not contain "(claude call failed:" or equivalent error marker

    Returns False if the file doesn't exist, is empty, or looks like a failed run.
    Fail-closed: any read error returns False (assume not produced).
    """
    if not path.exists():
        return False
    try:
        content = path.read_text()
    except Exception:
        return False
    return _is_valid_content(content)


def read_remote(remote_path: str, remote_host: str, run=subprocess.run) -> str | None:
    """Read a file from the remote machine over SSH. Returns None on any error."""
    if not remote_path or not remote_host:
        return None
    try:
        quoted_path = _quote_remote_path(remote_path)
        proc = run(
            ["ssh", *task_dispatch.SSH_OPTS, remote_host, f"cat {quoted_path}"],
            capture_output=True, text=True, timeout=15
        )
        if proc.returncode != 0:
            return None
        return proc.stdout
    except Exception:
        return None


def _read_primary_output(local_path: Path, run=subprocess.run) -> str | None:
    """Read the primary's (mini's) output over SSH, return None on any failure."""
    try:
        for dev, info in machine_profile.remote_macs().items():
            if scanner_role.is_primary(dev):
                primary_host = info.get("tailscale_hostname")
                if primary_host:
                    remote_path = _infer_remote_path(local_path)
                    if remote_path:
                        return read_remote(remote_path, primary_host, run=run)
    except Exception:
        pass
    return None


def safe_registry_id() -> str:
    """Get the machine's registry_id, returning a fallback on any error."""
    try:
        return machine_profile.registry_id()
    except Exception:
        return "unknown"


def past_deadline(now: datetime, usual_hour: int, usual_minute: int, grace_minutes: int = 60) -> bool:
    """Check if we're past the primary's deadline including grace period.

    Deadline = usual_hour:usual_minute in the machine's local timezone.
    We return True if now >= deadline + grace_minutes.
    """
    local_now = now.astimezone()
    deadline = local_now.replace(hour=usual_hour, minute=usual_minute, second=0, microsecond=0)
    deadline_with_grace = deadline + timedelta(minutes=grace_minutes)
    return local_now >= deadline_with_grace


def should_run(local_path: Path, usual_hour: int = 8, usual_minute: int = 30,
               grace_minutes: int = 60, now: datetime | None = None) -> tuple[bool, str]:
    """Decide whether the fallback builder should run.

    Returns (should_run, reason) tuple like scanner_role.decide().

    Strategy:
    1. Check if this machine is the primary (mini) — if so, always False (primary doesn't check fallback)
    2. Check if the primary's output file was already produced — if so, False (nothing to do)
    3. Check if we're past the deadline+grace window — if not, False (too early)
    4. If all checks pass, True (fallback should build)

    Failures in looking up the remote/profile default to True, returning a fallback reason.
    """
    try:
        me = machine_profile.registry_id()
    except Exception:
        return True, "fallback: identity lookup failed, building defensively"

    # Check if this machine is the primary (always "mini")
    if scanner_role.is_primary(me):
        return True, "primary"

    # Check if the file was already produced locally
    if produced(local_path):
        return False, "output file already produced locally"

    # Try to read the primary's copy
    primary_content = _read_primary_output(local_path)
    if primary_content and _is_valid_content(primary_content):
        return False, "output file already produced on primary"

    # Check if we're past the deadline
    if now is None:
        now = datetime.now(timezone.utc)
    if not past_deadline(now, usual_hour, usual_minute, grace_minutes):
        local_now = now.astimezone()
        deadline = local_now.replace(hour=usual_hour, minute=usual_minute, second=0, microsecond=0)
        deadline_with_grace = deadline + timedelta(minutes=grace_minutes)
        minutes_until = (deadline_with_grace - local_now).total_seconds() / 60
        return False, f"fallback: too early, deadline+grace in {minutes_until:.0f} min"

    return True, "fallback: primary builder missed deadline+grace window"
