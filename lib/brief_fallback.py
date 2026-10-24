#!/usr/bin/env python3
"""Brief fallback gate (marvin#458): skip running a brief/digest if it was
already built recently on the primary machine, so the fallback plist on the
laptop never runs when the Mini has already built it.

A brief is "produced" when it was built on any machine and is either:
- newer than its usual-hour deadline (i.e. built today at the scheduled time or later), or
- newer than the previous deadline and still fresh enough (within grace_minutes of the current time).

If a brief IS produced and fresh, `should_run()` returns False and the caller skips.
If a brief is NOT produced or is stale, `should_run()` returns True and the caller builds it.

Fallback plists run at usual_hour + 60 min on the laptop; the main plist runs on the Mini at usual_hour.
Normal day: Mini builds at 8:30, fallback skips at 9:30. If Mini's missing: fallback builds at 9:30.

Written to by every producer (build cli path); read by every consumer's should_run() gate.
"""
from __future__ import annotations

import json
import shlex
import subprocess
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import NamedTuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
from task_dispatch import SSH_OPTS  # noqa: E402
import scanner_role  # noqa: E402
import machine_profile  # noqa: E402


class Decision(NamedTuple):
    """Whether a brief should be built. True = yes, build it. False = skip it (already produced)."""
    should_build: bool
    reason: str
    produced_at: datetime | None = None
    produced_on: str | None = None


def _infer_remote_path(local_path: Path | str) -> str:
    """Infer the remote home-relative path from a local one.

    Examples:
      ~/.claude/briefs/2026-10-24.md -> .claude/briefs/2026-10-24.md
      /Users/gils/.claude/daily-digest/2026-10-24.md -> .claude/daily-digest/2026-10-24.md
    Bare filename (no parent) is also valid; same name is returned.
    """
    local_path = Path(local_path)
    home = Path.home()
    try:
        rel = local_path.relative_to(home)
        return str(rel)
    except ValueError:
        # Not under home; try to extract just the filename or last few parts
        return str(local_path.name if local_path.is_absolute() else local_path)


def read_remote(remote_path: str, host: str | None = None, run=subprocess.run) -> dict | None:
    """Read <remote_path>.built-by.json sidecar from a remote machine over SSH.

    remote_path: home-relative (e.g. ".claude/briefs/2026-10-24.md")
    host: Tailscale hostname; if None, reads the local .built-by.json sidecar instead.

    Returns the parsed JSON dict, or None if the file doesn't exist or is unreadable.
    """
    built_by_path = Path(remote_path).with_name(Path(remote_path).stem + ".built-by.json")
    built_by_rel = str(built_by_path)

    if host is None:
        local_path = Path.home() / built_by_rel
        if not local_path.exists():
            return None
        try:
            return json.loads(local_path.read_text())
        except (json.JSONDecodeError, OSError):
            return None

    # Read over SSH from the remote
    built_by_path_quoted = shlex.quote(built_by_rel)
    script = f'cat "$HOME"/{built_by_path_quoted} 2>/dev/null || echo'
    cmd = ["ssh", *SSH_OPTS, host, "bash -s"]
    try:
        proc = run(cmd, input=script, capture_output=True, text=True, timeout=10)
        if proc.returncode != 0 or not proc.stdout.strip():
            return None
        return json.loads(proc.stdout)
    except (json.JSONDecodeError, subprocess.SubprocessError, OSError):
        return None


def produced(local_path: Path | str, remote_path: str | None = None, host: str | None = None,
             run=subprocess.run) -> tuple[bool, str | None, str | None]:
    """Check if a brief was produced (built) recently.

    Returns (was_produced, machine_id, timestamp_str).
    was_produced=True means the .built-by.json sidecar exists and is parseable.
    If remote_path is None, infer it from local_path.
    If host is None, check only the local sidecar.

    Examples:
      produced(Path.home() / ".claude" / "briefs" / "2026-10-24.md")
        -> reads local .built-by.json
      produced(
          Path.home() / ".claude" / "briefs" / "2026-10-24.md",
          remote_path=".claude/briefs/2026-10-24.md",
          host="gils-mac-mini"
        )
        -> reads local .built-by.json, then remote if local is missing
    """
    remote_path = remote_path or _infer_remote_path(local_path)

    # Try local first
    local_sidecar = Path.home() / remote_path.replace(".built-by.json", "")
    local_sidecar = local_sidecar.with_name(local_sidecar.stem + ".built-by.json")
    try:
        if local_sidecar.exists():
            data = json.loads(local_sidecar.read_text())
            return (True, data.get("built_on"), data.get("built_at"))
    except (json.JSONDecodeError, OSError):
        pass

    # If no local sidecar and host is given, try remote
    if host:
        data = read_remote(remote_path, host=host, run=run)
        if data:
            return (True, data.get("built_on"), data.get("built_at"))

    return (False, None, None)


def past_deadline(now: datetime, usual_hour: int, usual_minute: int, grace_minutes: int = 60) -> bool:
    """Return True if now is past the usual deadline (usual_hour:usual_minute) plus grace.

    grace_minutes extends the deadline window — a brief built at usual_hour is considered fresh
    until usual_hour + grace_minutes has passed.
    """
    deadline = now.astimezone().replace(hour=usual_hour, minute=usual_minute, second=0, microsecond=0)
    grace = timedelta(minutes=grace_minutes)
    return now >= deadline + grace


def should_run(device_id: str | None = None, now: datetime | None = None,
               local_path: Path | str | None = None, remote_path: str | None = None,
               usual_hour: int = 8, usual_minute: int = 30, grace_minutes: int = 60,
               run=subprocess.run) -> Decision:
    """Decide whether a brief should be built.

    Returns a Decision: should_build=True means yes, build it. should_build=False means no, skip it.

    Logic:
    1. If we're on the primary machine (device_id=None or is_primary), always build (should_run=True).
    2. If we're not on the primary machine (fallback context), check if the brief was produced on the primary.
    3. If it was produced and is still fresh (within grace_minutes of deadline), skip it.
    4. Otherwise, build it.

    Args:
      device_id: explicit device ID to check, or None to auto-detect via scanner_role.
      now: datetime.now(timezone.utc) by default.
      local_path: path to the output file (e.g. ~/.claude/briefs/2026-10-24.md).
      remote_path: home-relative path if different from local_path.
      usual_hour, usual_minute: when the job is scheduled to run on the primary.
      grace_minutes: how many minutes past the deadline the brief is still "fresh".
      run: subprocess.run or a mock for testing.
    """
    now = now or datetime.now(timezone.utc)
    local_path = Path(local_path) if local_path else None
    remote_path = remote_path or (str(_infer_remote_path(local_path)) if local_path else None)

    # Check if this is the primary machine (if unspecified, auto-detect)
    if device_id is None:
        device_id = machine_profile.registry_id()
    is_primary = scanner_role.is_primary(device_id)

    # Primary always builds
    if is_primary:
        return Decision(True, "on the primary machine, always build", None, None)

    # Fallback (non-primary) machine: check if brief was produced recently
    if not local_path or not remote_path:
        return Decision(True, "no output path specified, must build", None, None)

    # Find the primary machine's host
    primary_host = None
    for dev_id, info in machine_profile.remote_devices().items():
        if scanner_role.is_primary(dev_id):
            primary_host = info.get("tailscale_hostname")
            break

    if not primary_host:
        return Decision(True, "primary machine not found in registry, must build", None, None)

    # Check if brief was produced on the primary
    was_produced, built_on, built_at = produced(local_path, remote_path, host=primary_host, run=run)

    if not was_produced:
        return Decision(True, f"brief not produced on primary machine", None, None)

    # Brief exists on primary. Check if it's fresh (within grace window of deadline).
    if built_at:
        try:
            built_dt = datetime.fromisoformat(built_at.replace("Z", "+00:00"))
            # Brief is fresh if it was built after (deadline - grace_minutes)
            fresh_after = now.astimezone().replace(hour=usual_hour, minute=usual_minute, second=0, microsecond=0) - timedelta(minutes=grace_minutes)
            if built_dt >= fresh_after:
                return Decision(False, f"brief produced on {built_on} at {built_at}, still fresh", built_dt, built_on)
        except (ValueError, AttributeError):
            pass

    return Decision(True, f"brief on {built_on} is stale, must rebuild", None, None)


def record_built_by(output_path: Path | str, machine: str, mode: str, now: datetime | None = None) -> Path:
    """Write a <output_path stem>.built-by.json sidecar.

    Sidecar format: {"built_at": "<ISO8601>", "built_on": "<machine_id>", "mode": "<mode>"}
    mode: "normal" | "fallback" | other string identifying which plist triggered the build.

    Returns the path to the sidecar file.
    """
    now = now or datetime.now(timezone.utc)
    output_path = Path(output_path)
    sidecar_path = output_path.with_name(output_path.stem + ".built-by.json")

    sidecar_data = {
        "built_at": now.isoformat(),
        "built_on": machine,
        "mode": mode,
    }

    sidecar_path.parent.mkdir(parents=True, exist_ok=True)
    sidecar_path.write_text(json.dumps(sidecar_data, indent=2))
    return sidecar_path
