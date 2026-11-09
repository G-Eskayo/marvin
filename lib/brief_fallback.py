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


REPO = Path(__file__).resolve().parent.parent
# Each output's two launchd jobs: the primary's (the Mini) and the fallback's (the other Macs). The primary plist's own
# schedule is the output's usual time, so the gate and the schedule can't drift apart. Found 2026-11-04 (#1123 0.4):
# the laptop ran the primary plists, at or before the usual time + GRACE, so every fallback skipped every day.
PAIRS = {
    "daily-digest": ("skills/improve/com.marvin.daily-digest.plist",
                     "skills/improve/com.marvin.daily-digest-fallback.plist"),
    "research-colony": ("skills/research-colony/com.marvin.research-colony.plist",
                        "skills/research-colony/com.marvin.research-colony-fallback.plist"),
    "morning-brief": ("config/launchd/com.marvin.morning-brief.plist",
                      "config/launchd/com.marvin.morning-brief-fallback.plist"),
}
GRACE_MINUTES = 60            # how long a standby waits past the usual time before it covers
FALLBACK_MARGIN_MINUTES = 5   # a fallback is scheduled at least this long after its deadline


def plists(job: str) -> tuple[Path, Path]:
    """(primary plist, fallback plist) in this checkout. KeyError for a job that has no pair."""
    primary, fallback = PAIRS[job]
    return REPO / primary, REPO / fallback


def _calendar(path: Path) -> tuple[int, int]:
    import plistlib
    when = plistlib.loads(path.read_bytes())["StartCalendarInterval"]
    return int(when["Hour"]), int(when.get("Minute", 0))


def usual_time(job: str) -> tuple[int, int]:
    """(hour, minute), local: when the primary builds `job`, read from its plist."""
    return _calendar(plists(job)[0])


def _launchctl(cmd: list[str]) -> int:
    return subprocess.run(cmd, capture_output=True, text=True).returncode


def install(job: str, primary: bool, home: Path | None = None, run=None, uid: int | None = None) -> dict:
    """Install the one job of the pair this Mac should run, and boot out and remove the other one's copy (a copy of a
    repo file, so nothing is lost). Identical and already installed: left alone."""
    import os
    want, other = plists(job) if primary else plists(job)[::-1]
    home = Path(home or Path.home())
    run = run or _launchctl
    uid = os.getuid() if uid is None else uid
    agents = home / "Library" / "LaunchAgents"
    label, other_label = (f"com.marvin.{job}", f"com.marvin.{job}-fallback")[::1 if primary else -1]
    removed = None
    other_path = agents / f"{other_label}.plist"
    if other_path.exists():
        run(["launchctl", "bootout", f"gui/{uid}/{other_label}"])
        other_path.unlink()
        removed = other_label
    dest = agents / f"{label}.plist"
    data = want.read_bytes()
    if dest.exists() and dest.read_bytes() == data:
        return {"job": job, "installed": label, "removed": removed, "ok": True}
    agents.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, dest)
    run(["launchctl", "bootout", f"gui/{uid}/{label}"])   # fails harmlessly when it wasn't loaded
    ok = run(["launchctl", "bootstrap", f"gui/{uid}", str(dest)]) == 0
    return {"job": job, "installed": label, "removed": removed, "ok": ok}


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
                  grace_minutes: int = GRACE_MINUTES) -> bool:
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
               grace_minutes: int = GRACE_MINUTES, run=subprocess.run) -> Decision:
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


def main(argv: list[str]) -> int:
    """brief_fallback.py install [job...]: install this Mac's half of each pair (all three by default)."""
    import json
    if not argv or argv[0] != "install":
        print("usage: brief_fallback.py install [" + "|".join(PAIRS) + " ...]", file=sys.stderr)
        return 2
    me = machine_profile.registry_id()
    results = [install(job, primary=is_primary(me)) for job in (argv[1:] or list(PAIRS))]
    print(json.dumps(results))
    return 0 if all(r["ok"] for r in results) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
