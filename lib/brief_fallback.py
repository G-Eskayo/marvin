#!/usr/bin/env python3
"""Brief generation fallback scheduling (ADR 0067): stand by for a primary, build if it doesn't.

Used by daily_digest.py, research_digest.py, and morning_brief.py to decide whether a standby
machine (laptop) should rebuild today's brief/digest — primary (mac-mini) should have done it.
Standby builds only if past the deadline AND the primary hasn't produced anything usable.

Directly mirrors scanner_role.py's primary/standby pattern, applied to dated output files rather than
heartbeats. Primary always returns (should_build=True, reason='primary'); standby checks deadline,
then checks if the primary has produced usable output.
"""
from __future__ import annotations
import shlex
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import NamedTuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
import machine_profile  # noqa: E402
import task_dispatch  # noqa: E402


class Decision(NamedTuple):
    """Describes a should_run() result."""
    should_build: bool
    reason: str


def _infer_remote_path(local_path: Path, remote_device_id: str) -> str:
    """Map a local path to a remote path for SSH.

    If local_path is under $HOME, produce a remote path under the remote $HOME matching the
    relative subdirectory. If it's outside $HOME, fall back to $HOME/.claude/<filename>.
    This is to preserve ~/.claude/briefs/ -> ~/.claude/briefs/, not drop down to ~/.claude/FILENAME.

    Returns a remote path string for use in an SSH command: e.g. '$HOME/.claude/briefs/2026-10-25.md'.
    Never returns a shell-special-char-escaped string — the caller (read_remote) handles quoting.
    """
    home = Path.home()
    try:
        rel = local_path.relative_to(home)
        return f"$HOME/{rel}"
    except ValueError:
        # Outside $HOME; fall back to ~/.claude/<filename>
        return f"$HOME/.claude/{local_path.name}"


def read_remote(remote_path: str, remote_device_id: str, run=subprocess.run) -> str | None:
    """Read a file from a remote machine over SSH, with safe quoting.

    remote_path: a path string that may contain $HOME (which gets expanded by the remote shell),
                 e.g. '$HOME/.claude/briefs/2026-10-25.md'. The $HOME part is left unquoted so
                 the shell expands it; the remainder is shlex.quote()'d for safety.
    run: callable(command_list, ...) for testing; default subprocess.run.

    Returns the file contents as a string, or None if unreachable, unreadable, or the registry
    lookup fails. Fails closed: any error returns None, not an exception.
    """
    try:
        import machine_profile
        remote_devices = machine_profile.remote_macs()
        if remote_device_id not in remote_devices:
            return None
        info = remote_devices[remote_device_id]
        host = info.get("tailscale_hostname")
        if not host:
            return None
    except Exception:
        return None

    # Split the path at $HOME so we can leave $HOME unquoted and quote the remainder.
    if remote_path.startswith("$HOME/"):
        prefix = "$HOME/"
        remainder = remote_path[6:]  # everything after "$HOME/"
    else:
        # Fallback: if someone passes a literal /Users/... path, quote the whole thing.
        prefix = ""
        remainder = remote_path

    quoted_remainder = shlex.quote(remainder) if remainder else ""
    full_path = prefix + quoted_remainder

    try:
        proc = run(
            ["ssh", *task_dispatch.SSH_OPTS, host, f"cat {full_path}"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if proc.returncode != 0:
            return None
        return proc.stdout
    except Exception:
        return None


def produced(local_path: Path, remote_device_id: str | None = None) -> bool:
    """Has the primary machine produced usable output?

    Checks local_path first: if it exists and contains non-trivial text, it's produced.
    Empty, whitespace-only, or '(claude call failed: ...)' placeholder files are not produced.
    Quarantined files (containing '_Quarantined by safety-monitor') count as produced per
    Decision A: the machine did its job, a held item is an outcome, not an outage.

    If local_path doesn't exist or isn't produced locally, falls back to a remote SSH read
    of the same file on the remote device (if remote_device_id is provided). This handles
    genuine cross-machine scenarios where the primary's output exists only over SSH.

    Returns False on any unreadable case (no file, permission error, registry lookup failure).
    Never raises.
    """
    if not local_path.exists():
        # Not local — try remote
        if remote_device_id is None:
            return False
        remote_path = _infer_remote_path(local_path, remote_device_id)
        content = read_remote(remote_path, remote_device_id)
        return _is_produced_content(content) if content is not None else False

    # Local file exists — read it
    try:
        text = local_path.read_text(errors="ignore")
    except Exception:
        # Unreadable (permission); fall back to remote
        if remote_device_id is None:
            return False
        remote_path = _infer_remote_path(local_path, remote_device_id)
        content = read_remote(remote_path, remote_device_id)
        return _is_produced_content(content) if content is not None else False

    return _is_produced_content(text)


def _is_produced_content(text: str) -> bool:
    """Determine if text counts as 'produced' output.

    Empty, whitespace, or '(claude call failed: ...)' → False.
    '_Quarantined by safety-monitor' → True (Decision A: quarantine counts as produced).
    Any other non-empty text → True.
    """
    if not text or not text.strip():
        return False
    if text.startswith("(claude call failed:"):
        return False
    if "_Quarantined by safety-monitor" in text:
        return True  # Decision A default
    return True


def past_deadline(local_now: datetime, usual_hour: int, usual_minute: int) -> bool:
    """Is it past the deadline for a standby to take over? Pure local clock only.

    Calculates the deadline as (usual_hour, usual_minute + 1 hour) in the local timezone.
    Example: if usual_hour=8, usual_minute=30, then deadline is 09:30. Past deadline means
    the standby's next opportunity to build has passed.

    local_now: datetime in the local timezone (not UTC).
    Returns True if the local time is past the deadline, False otherwise.
    """
    deadline = local_now.replace(hour=usual_hour, minute=usual_minute, second=0, microsecond=0)
    deadline = deadline.replace(hour=(deadline.hour + 1) % 24)
    return local_now >= deadline


def should_run(
    local_path: Path,
    usual_hour: int,
    usual_minute: int,
) -> Decision:
    """Decide whether this machine should build (or rebuild) the brief/digest.

    Primary (mac-mini) always builds: returns (should_build=True, reason='primary').
    Standby (laptop) builds only if both:
      1. Past the deadline (usual_hour + 1 hour)
      2. The primary hasn't produced usable output

    local_path: the local file to check/write (e.g., ~/.claude/briefs/2026-10-25.md).
    usual_hour, usual_minute: the primary's scheduled run time (e.g., 9, 15 for 09:15).

    Returns a Decision: (should_build, reason_string).
    """
    import scanner_role

    try:
        me = machine_profile.registry_id()
    except Exception:
        return Decision(True, "identity lookup failed — building to be safe")

    if scanner_role.is_primary(me):
        return Decision(should_build=True, reason="primary")

    local_now = datetime.now(tz=timezone.utc).astimezone()

    if not past_deadline(local_now, usual_hour, usual_minute):
        return Decision(should_build=False, reason=f"standby: waiting for deadline ({usual_hour + 1}:{usual_minute:02d})")

    # Past deadline — check if the primary has produced
    primary_device_id = _find_primary_device_id()
    if primary_device_id and produced(local_path, remote_device_id=primary_device_id):
        return Decision(should_build=False, reason="standby: primary has produced")

    # Primary hasn't produced — we should build
    return Decision(should_build=True, reason="standby: primary unreachable or has not produced")


def _find_primary_device_id() -> str | None:
    """Find the device ID of the primary machine. Returns None if not found in registry."""
    import scanner_role
    try:
        for dev in machine_profile.remote_macs():
            if scanner_role.is_primary(dev):
                return dev
    except Exception:
        pass
    return None
