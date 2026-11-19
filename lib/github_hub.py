#!/usr/bin/env python3
"""Hub election for GitHub reads: one machine is hub, others fall back to cached feed or direct calls (ADR 0082).

The hub is elected across three tiers (fail-open):
  Tier 1: Mac mini (the box, most always-on and disk-rich)
  Tier 2: Macbook Pro (the laptop, when mini is offline)
  Tier 3: Every other machine falls back to the feed or direct calls

Each machine writes an election record with stamped.py so peers can read it. The hub re-elects itself every hour
(a fresh heartbeat), and a machine that sees no fresh heartbeat from the current hub falls through to the next tier.

Usage:
    is_hub, reason = github_hub.decide(tier, heartbeats, now)
    is_hub, reason = github_hub.am_hub()  # convenience, reads heartbeats and decides locally
    github_hub.write_heartbeat(device_id, now)  # hub or standby writes election state
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

HEARTBEAT_PATH = Path.home() / ".claude" / "github-hub-heartbeat.json"
TIER_ORDER = ("mac-mini", "macbook-pro")  # Tier 1 (mac-mini*), Tier 2 (macbook-pro*), Tier 3 (fallback)
HEARTBEAT_STALE_AFTER = 3600  # 1 hour: hub must re-elect itself hourly


def _tier_for_device(device_id: str) -> int:
    """Return tier (0, 1, 2, 3) for device_id. Lower tier = higher priority.
    mac-mini-2012 (box with no GitHub credentials) is explicitly tier 3 (ineligible for hub)."""
    if device_id == "mac-mini-2012":
        return 3  # Tier 3: ineligible (no credentials)
    for i, prefix in enumerate(TIER_ORDER):
        if device_id.startswith(prefix):
            return i
    return 2  # Tier 2: fallback (other machines)


def write_heartbeat(device_id: str, now: float | None = None, path: Path = HEARTBEAT_PATH) -> None:
    """Hub (or the current elected machine) writes a heartbeat to announce its election."""
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = {"device": device_id, "ts": now if now is not None else time.time()}
    path.write_text(json.dumps(doc))


def decide(tier: int, heartbeats: dict[str, float | None], device_id: str | None = None, now: float | None = None) -> tuple[bool, str]:
    """(is_hub, reason) for a machine at `tier` given the dict of {device_id: heartbeat_age_s or None}.

    Fail-open: if any heartbeat cannot be read or is stale, fall through to the next tier.
    Tier 3 (mac-mini-2012, ineligible) can never be hub.
    heartbeats dict: {device_id: age_in_seconds or None}. None = could not read or parse.
    device_id: the calling machine's device_id. If provided, only THIS machine's heartbeat
               matters when deciding at the same tier (prevents double-hub at same tier).
    """
    # Tier 3 is ineligible for hub
    if tier == 3:
        return False, "tier 3 is ineligible for hub (no GitHub credentials)"

    # Find the highest tier with a fresh heartbeat
    hub_tier = None
    hub_device = None
    for check_tier in range(3):  # 0, 1, 2 only (tier 3 is ineligible)
        has_fresh = False
        for d, age in heartbeats.items():
            if _tier_for_device(d) != check_tier:
                continue
            if age is not None and age <= HEARTBEAT_STALE_AFTER:
                has_fresh = True
                hub_device = d
                break
        if has_fresh:
            hub_tier = check_tier
            break

    # If we found a fresh tier, check if this machine could be the hub
    if hub_tier is not None:
        if tier > hub_tier:
            # This machine's tier is higher (lower priority) than the hub tier
            return False, f"tier {hub_tier} is elected; this machine (tier {tier}) is standby"
        elif tier == hub_tier:
            # At the same tier, only be hub if THIS specific machine's heartbeat is fresh
            if device_id is not None:
                # Check only this device's heartbeat
                my_age = heartbeats.get(device_id)
                if my_age is not None and my_age <= HEARTBEAT_STALE_AFTER:
                    return True, f"elected (tier {tier}): my heartbeat is fresh"
                return False, f"tier {tier} exists but my heartbeat is stale; standby"
            # Fallback if device_id not provided: be hub if any device at this tier is fresh
            return True, f"elected (tier {tier}): higher tiers unavailable"
        elif tier < hub_tier:
            # This machine's tier is higher priority than the hub tier.
            # If this machine's heartbeat is fresh, it should become hub.
            if device_id is not None:
                my_age = heartbeats.get(device_id)
                if my_age is not None and my_age <= HEARTBEAT_STALE_AFTER:
                    return True, f"tier {tier}: higher priority than current hub (tier {hub_tier}), taking over"
                return False, f"tier {hub_tier} is elected; this machine (tier {tier}) is standby"
            # Fallback: be hub if tier is higher priority
            return True, f"tier {tier}: higher priority than current hub (tier {hub_tier}), taking over"

    # No fresh heartbeats found at any tier: this machine is the hub only if tier < 3
    if tier == 3:
        return False, "tier 3 is ineligible for hub (no GitHub credentials)"
    return True, f"tier {tier}: all higher tiers stale or unreadable, taking hub"


def am_hub() -> tuple[bool, str]:
    """Convenience: read local heartbeats, decide if this machine is the hub.
    Only the elected hub writes a heartbeat; standby machines do not."""
    import machine_profile
    me = machine_profile.registry_id()
    my_tier = _tier_for_device(me)

    heartbeats = {}
    # Read heartbeats for all known devices AND this machine's own heartbeat
    for device_id in [me] + list((machine_profile.remote_devices() or {}).keys()):
        if device_id == me:
            # Read this machine's own heartbeat from disk
            age = _read_local_heartbeat_age()
        else:
            # Read remote device's heartbeat over ssh
            age = _read_heartbeat_age(device_id)
        heartbeats[device_id] = age

    is_hub, reason = decide(my_tier, heartbeats, device_id=me)

    # Only the elected hub writes a heartbeat so peers know who is in charge
    if is_hub:
        write_heartbeat(me)

    return is_hub, reason


def _read_local_heartbeat_age(now: float | None = None) -> float | None:
    """Read this machine's own heartbeat from disk. Returns age in seconds, or None if missing/unreadable."""
    try:
        doc = json.loads(HEARTBEAT_PATH.read_text())
        ts = float(doc.get("ts", 0))
        age = (now if now is not None else time.time()) - ts
        return age if age >= 0 else None
    except Exception:
        return None


def _read_heartbeat_age(device_id: str, now: float | None = None) -> float | None:
    """Read heartbeat age for a remote device over ssh. Returns age in seconds, or None if unreadable."""
    import machine_profile
    import task_dispatch

    remote_info = machine_profile.remote_devices().get(device_id)
    if not remote_info:
        return None

    host = remote_info.get("tailscale_hostname")
    if not host:
        return None

    if host not in task_dispatch._tailscale_online_hosts():
        return None

    try:
        proc = subprocess.run(
            ["ssh", *task_dispatch.SSH_OPTS, host, f'cat "{HEARTBEAT_PATH}"'],
            capture_output=True, text=True, timeout=15
        )
        if proc.returncode != 0:
            return None
        doc = json.loads(proc.stdout)
        ts = float(doc.get("ts", 0))
        age = (now if now is not None else time.time()) - ts
        return age if age >= 0 else None
    except Exception:
        return None


if __name__ == "__main__":
    is_hub, reason = am_hub()
    print(f"Hub: {is_hub} - {reason}")
