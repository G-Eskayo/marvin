#!/usr/bin/env python3
"""Primary/standby for the ticket scanner (ADR 0032 follow-up).

Two machines scanning is wasteful and zero machines scanning stalls the board. So the primary (mac-mini) always scans, and
the standby (any other machine) scans only when the primary has gone quiet: unreachable, or reachable but its last scan
is older than STALE_AFTER. Where a ticket then RUNS is unchanged: task_dispatch.select_machine picks any live, idle machine.

Every scan writes a heartbeat; the standby reads the primary's over ssh. Unknowns fail open (scan): a duplicate scan is safe
because claim labels stop a ticket being dispatched twice, a missing scan is not.
"""
from __future__ import annotations
import json
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

HEARTBEAT_PATH = Path.home() / ".claude" / "ticket-scan-heartbeat.json"
PRIMARY_PREFIX = "mac-mini"
STALE_AFTER = 150 * 60   # the scan runs hourly: miss two in a row and the primary is not doing its job


def is_primary(device_id: str) -> bool:
    return device_id.startswith(PRIMARY_PREFIX)


def write_heartbeat(device_id: str, now: float | None = None, path: Path = HEARTBEAT_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"device": device_id, "ts": now if now is not None else time.time()}))


def decide(device_id: str, primary_heartbeat_age: float | None, primary_reachable: bool | None) -> tuple[bool, str]:
    """(should_scan, reason). Age None = could not read a heartbeat; reachable None = could not tell."""
    if is_primary(device_id):
        return True, "primary"
    if primary_reachable is False:
        return True, "standby: primary is unreachable"
    if primary_heartbeat_age is None:
        return True, "standby: primary's heartbeat could not be read"
    if primary_heartbeat_age > STALE_AFTER:
        return True, f"standby: primary last scanned {primary_heartbeat_age / 60:.0f} min ago"
    return False, f"standby: primary scanned {primary_heartbeat_age / 60:.0f} min ago"


def _primary_device():
    import machine_profile
    for dev, info in machine_profile.remote_devices().items():
        if is_primary(dev):
            return dev, info
    return None, None


def check_primary(now: float | None = None, run=subprocess.run) -> tuple[float | None, bool | None]:
    """(heartbeat age in seconds, reachable) for the primary, read over ssh."""
    import task_dispatch
    _dev, info = _primary_device()
    if not info:
        return None, None
    host = info["tailscale_hostname"]
    if host not in task_dispatch._tailscale_online_hosts():
        return None, False
    try:
        proc = run(["ssh", *task_dispatch.SSH_OPTS, host, f"cat {HEARTBEAT_PATH}"], capture_output=True, text=True, timeout=15)
        if proc.returncode != 0:
            return None, None
        ts = float(json.loads(proc.stdout)["ts"])
        return (now if now is not None else time.time()) - ts, True
    except Exception:
        return None, None


def should_scan() -> tuple[bool, str]:
    import machine_profile
    me = machine_profile.registry_id()
    if is_primary(me):
        return True, "primary"
    age, reachable = check_primary()
    return decide(me, age, reachable)
