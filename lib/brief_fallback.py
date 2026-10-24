#!/usr/bin/env python3
"""Fallback builder execution for morning brief, daily digest, and research colony (ADR 0067).

When the primary builder (Mac Mini) fails to produce an output by a fallback window (one hour after
expected), the standby builder (MacBook) takes over. This module reads the remote builder's state and
decides whether to build locally.

Reuses scanner_role.is_primary/_primary_device, machine_profile.registry_id/remote_devices, and
task_dispatch.SSH_OPTS for consistency.
"""
from __future__ import annotations
import json
import shlex
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import scanner_role
import machine_profile
import task_dispatch


FAILURE_MARKERS = (
    "NOT found at",
    "claude call failed",
)


def _infer_remote_path(local_path: str) -> str:
    """Convert a local path (e.g., /Users/gileskayo/.claude/briefs/2026-10-24.md) to remote notation
    ($HOME/.claude/briefs/2026-10-24.md) safe for SSH."""
    # Expand ~ if present, then make relative to home
    p = Path(local_path).expanduser()
    home = Path.home()
    try:
        rel = p.relative_to(home)
        return f"$HOME/{rel}"
    except ValueError:
        # Absolute path that doesn't start in home — preserve as-is
        return str(p)


def read_remote(remote_host: str, file_path: str, run=subprocess.run) -> str | None:
    """Read a file from a remote machine via SSH.
    file_path should use $HOME notation for cross-machine portability.
    Returns file contents on success, None on failure (including file not found)."""
    if file_path.startswith("$HOME/"):
        quoted_path = "$HOME/" + shlex.quote(file_path[6:])
    else:
        quoted_path = shlex.quote(file_path)
    cmd = ["ssh", *task_dispatch.SSH_OPTS, remote_host, f"cat {quoted_path}"]
    try:
        proc = run(cmd, capture_output=True, text=True, timeout=10)
        return proc.stdout if proc.returncode == 0 else None
    except Exception:
        return None


def _is_failure_placeholder(content: str) -> bool:
    """Detect if a file contains a failure marker instead of real content."""
    return any(marker in content for marker in FAILURE_MARKERS)


def produced(day: str, builder_path: str, remote_host: str | None = None, read_remote_fn=None) -> bool:
    """Check if the primary builder produced the file for this day.
    day: YYYY-MM-DD format
    builder_path: local path on primary (e.g., ~/.claude/briefs/2026-10-24.md)
    remote_host: Tailscale hostname of primary builder (if None, check local)
    read_remote_fn: injectable read_remote function (for testing)
    Returns True only if the file exists and contains real content (not a failure marker)."""
    # Always check local content first
    path = Path(builder_path).expanduser()
    if path.exists():
        content = path.read_text()
        if not _is_failure_placeholder(content):
            return True

    # If no valid local file and remote_host is provided, check remote
    if remote_host is None:
        return False

    read_fn = read_remote_fn or read_remote
    remote_path = _infer_remote_path(builder_path)
    content = read_fn(remote_host, remote_path)
    if not content:
        return False
    return not _is_failure_placeholder(content)


def is_owner() -> bool:
    """This machine should take the fallback role (standby builder).
    Returns True if this is not the primary builder."""
    return not scanner_role.is_primary(machine_profile.registry_id())


def should_build(day: str, output_path: str) -> tuple[bool, str]:
    """Fallback builder: should we build the output (brief/digest) for this day?
    - If this is the primary, never fallback-build (the primary is responsible).
    - If this is standby and the primary has already produced it: skip.
    - If this is standby and the primary hasn't produced it: build.
    Returns (should_build: bool, reason: str) tuple."""
    if not is_owner():
        return (False, "owner")

    # This is the standby. Check if primary produced the output.
    _dev, primary_info = scanner_role._primary_device()
    if not primary_info:
        # No primary registered — we are the fallback, so build.
        return (True, "no-primary-registered")

    primary_host = primary_info.get("tailscale_hostname")
    if not primary_host:
        # Can't reach primary over network — build locally.
        return (True, "primary-unreachable")

    # Check if primary has produced the output.
    if produced(day, output_path, primary_host):
        return (False, "primary-produced")
    return (True, "primary-missing")


def mark_built(output_dir: str, day: str, reason: str) -> None:
    """Record that this output was built and by whom, for debugging fallback decisions.
    output_dir: parent directory (e.g., ~/.claude/briefs)
    day: YYYY-MM-DD format
    reason: why we built it (e.g., "no-primary-registered", "primary-missing")
    Writes a JSON marker file alongside the output."""
    output_path = Path(output_dir)
    marker_path = output_path / f"{day}.built-by"
    marker = {
        "built_by": machine_profile.machine_label(),
        "reason": reason,
        "built_at": datetime.now(timezone.utc).isoformat(),
    }
    marker_path.write_text(json.dumps(marker))


if __name__ == "__main__":
    # Quick test: python3 lib/brief_fallback.py
    print(f"is_owner: {is_owner()}", file=sys.stderr)
    print(f"produced (local test): {produced('2026-10-24', '~/.claude/briefs/2026-10-24.md')}", file=sys.stderr)
