#!/usr/bin/env python3
"""GitHub hub claim mechanism: a stamped file naming the current hub (mini/box/laptop), when it claimed it, and a lease.

Deterministic order (Mini → box relay → laptop) beats true consensus: whichever machine runs first and acquires the lock
gets to be the hub. The claim is stamped so other machines see not just the name but how old it is; past the lease term,
another machine can claim it. Priority: Mini > box (via relay) > laptop. First one to write wins.

Lock is fcntl.flock over a lockfile (reusing the pattern from bin/gh's _State), extended across machines via the same
stamped-copy read every watcher already polls (not a timer). The claim file (~/.claude/github-hub.json) holds the current
hub, since-when, and a lease term.

marvin#: TBD (plan step 3)
"""
from __future__ import annotations

import contextlib
import fcntl
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import stamped

UTC = timezone.utc
CLAIM_PATH = Path.home() / ".claude" / "github-hub.json"
LOCK_PATH = Path.home() / ".claude" / ".github-hub.lock"
LEASE_S = 3600  # 1 hour: if the hub is silent for an hour, another machine can claim it


@contextlib.contextmanager
def claim_lock():
    """Context manager: acquire an fcntl lock over the lockfile. Blocks until acquired."""
    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    lock_fd = os.open(str(LOCK_PATH), os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        yield lock_fd
    finally:
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
        except Exception:
            pass
        try:
            os.close(lock_fd)
        except Exception:
            pass


def write_claim(hub_id: str) -> dict:
    """Write a claim naming this machine as the hub. Stamped, atomic (temp + rename)."""
    host, uuid = stamped._me()
    now = datetime.now(UTC)
    data = {
        "hub": hub_id,
        "claimed_by": host,
        "hardware_uuid": uuid,
        "claimed_at": now.isoformat(),
        "lease_s": LEASE_S,
    }
    return stamped.write(CLAIM_PATH, data, tolerance_s=LEASE_S, now=now)


def read_claim() -> stamped.Copy:
    """Read the current hub claim. Returns a stamped.Copy (value, stale, age_s, etc.)."""
    try:
        return stamped.read(CLAIM_PATH, default_tolerance_s=LEASE_S)
    except Exception:
        return stamped.Copy(value=None, missing=True, stale=True)


def try_claim(hub_id: str, force: bool = False) -> tuple[bool, str]:
    """Try to claim the hub. Returns (success, reason). If force=True, claim even if one exists (for testing)."""
    with claim_lock():
        current = read_claim()
        if not force and not current.stale and not current.missing:
            return False, f"hub is {current.value.get('hub')} (claimed {stamped._ago(current.age_s)})"
        try:
            write_claim(hub_id)
            return True, f"claimed as hub ({LEASE_S}s lease)"
        except Exception as e:
            return False, f"write failed: {e}"


def current_hub(registry: dict | None = None) -> str | None:
    """The current hub id, or None if no current claim or stale. If a registry is provided, resolve by hardware_uuid."""
    claim = read_claim()
    if claim.missing or claim.stale:
        return None
    hub_id = claim.value.get("hub")
    if not hub_id:
        return None
    # If provided a registry, verify the hub_id exists in it
    if registry and hub_id not in registry:
        return None
    return hub_id


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "claim":
        hub_id = sys.argv[2] if len(sys.argv) > 2 else stamped._me()[0] or "unknown"
        success, reason = try_claim(hub_id)
        print(f"{'OK' if success else 'FAIL'}: {reason}")
        sys.exit(0 if success else 1)
    elif len(sys.argv) > 1 and sys.argv[1] == "read":
        claim = read_claim()
        print(json.dumps({"hub": claim.value.get("hub") if claim.value else None, "age_s": claim.age_s, "stale": claim.stale}))
        sys.exit(0)
    else:
        print(__doc__.strip())
        sys.exit(2)
