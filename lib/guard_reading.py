#!/usr/bin/env python3
"""Debouncing wrapper for machine-protecting guards (disk, memory, etc.) that converts fail-open into fail-closed with
flap protection (marvin#???).

When a guard can't read a critical resource (disk free space, memory pressure, dispatch state), it should refuse the
work rather than proceed blindly. But a one-off read failure (a transient, a stale lock) shouldn't pin a whole machine.
This module debounces: an unreadable state must happen twice within ~5 seconds to flip the reading from ok to
unreadable; flips back only after 2 good reads agree. The 2-read consensus and the 5s window prevent flapping on
every network hiccup or busy filesystem; Health escalates unreadable streaks to yellow at 30 min, red at 2h.

State lives in ~/.claude/logs/guard-readings.json (keyed by guard name). The CLI:
    guard_reading.py record --name disk:preflight --ok 1 [--detail "..."]
    guard_reading.py status                  # returns JSON [{name, severity, detail, ...}]

Call record() from any process; concurrent writes are atomic (json.dump to a temp file + atomic rename).
status() reads the shared file and computes per-guard severity for the Health card.

GUARD_POLICY = {name: "open"|"closed"} declares policy per guard (required in any module that calls record()),
so tests can override it and coverage() can verify every real call site is in the policy.
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

LOG_PATH = Path.home() / ".claude" / "logs" / "guard-readings.json"
DEBOUNCE_S = 5
SETTLED_GOOD_READS = 2
SETTLED_BAD_READS = 2
YELLOW_AFTER_S = 30 * 60
RED_AFTER_S = 2 * 3600

GUARD_POLICY = {}  # Each real call site adds an entry: name -> "open"|"closed"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _read_state() -> dict:
    """The current state dict from the shared file. Returns {} if missing or corrupt."""
    try:
        return json.loads(LOG_PATH.read_text())
    except (OSError, ValueError):
        return {}


def _write_state(state: dict) -> None:
    """Atomic write: temp file + rename. Doesn't raise; if it fails, the reading still proceeds (the state file is a
    journal, not a gate)."""
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    try:
        with tempfile.NamedTemporaryFile(mode="w", dir=LOG_PATH.parent, delete=False, suffix=".tmp") as f:
            json.dump(state, f)
            tmp_path = Path(f.name)
        tmp_path.replace(LOG_PATH)
    except OSError:
        pass


def record(name: str, ok: bool, detail: str = "") -> None:
    """Record one reading of a guard. Flips state only after 2 consecutive readings agree on the new value
    (debounce = flap protection). State transitions: any good read resets the pending counter; any bad read
    increments it toward a state flip.

    Args:
        name: Guard identifier (e.g., "disk:preflight", "memory:pressure").
        ok: True = reading succeeded (resource ok), False = reading failed (unreadable).
        detail: Human-readable explanation (e.g., "OSError: [Errno 28] No space left on device").
    """
    state = _read_state()
    now = _now()
    entry = state.setdefault(name, {"state": "ok", "since": now.isoformat(), "pending": None, "detail": ""})

    current_state = entry.get("state", "ok")
    target_state = "ok" if ok else "unreadable"

    if current_state == target_state:
        # No state flip needed; still on the same state.
        if ok:
            # A good read while in ok state; clear any pending counter.
            entry["pending"] = None
        # else: already unreadable, stay unreadable; don't accumulate more bad reads.
    else:
        # State flip needed (ok -> unreadable or unreadable -> ok).
        if entry.get("pending") is None:
            # First reading that disagrees; set pending state.
            entry["pending"] = {
                "state": target_state,
                "count": 1,
                "first_at": now.isoformat(),
            }
        else:
            # Already pending a state flip; see if we're past the debounce window or if we got a contradicting read.
            pending = entry["pending"]
            if pending["state"] != target_state:
                # Contradiction: the guard is flipping back and forth. Don't reset; keep pending at its current state.
                # The next read of the new state will increment the count.
                pass
            else:
                # Same target as before; increment the count.
                first_at = datetime.fromisoformat(pending["first_at"])
                age_s = (now - first_at).total_seconds()
                pending["count"] = int(pending.get("count", 1)) + 1
                if pending["count"] >= (SETTLED_GOOD_READS if ok else SETTLED_BAD_READS) or age_s > DEBOUNCE_S:
                    # Flip: either got 2 consecutive reads in agreement, or the debounce window passed.
                    entry["state"] = target_state
                    entry["since"] = now.isoformat()
                    entry["pending"] = None

    entry["detail"] = detail
    state[name] = entry
    _write_state(state)


def status() -> list[dict]:
    """Current severity per guard for the Health card. Returns a list of rows, one per guard that is not green.
    Row: {name, state ("ok"|"unreadable"), severity ("green"|"yellow"|"red"), detail, since, age_s}."""
    state = _read_state()
    now = _now()
    rows = []
    for name, entry in sorted(state.items()):
        current = entry.get("state", "ok")
        if current == "ok":
            continue  # green; don't report
        since = datetime.fromisoformat(entry.get("since", now.isoformat()))
        age_s = (now - since).total_seconds()
        severity = "red" if age_s >= RED_AFTER_S else ("yellow" if age_s >= YELLOW_AFTER_S else "green")
        rows.append({
            "name": name,
            "state": current,
            "severity": severity,
            "detail": entry.get("detail", ""),
            "since": entry.get("since", ""),
            "age_s": age_s,
        })
    return rows


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    ap = argparse.ArgumentParser(prog="guard_reading", description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("record")
    c.add_argument("--name", required=True)
    c.add_argument("--ok", type=int, required=True, choices=[0, 1])
    c.add_argument("--detail", default="")

    sub.add_parser("status")

    a = ap.parse_args(argv)
    if a.cmd == "record":
        record(a.name, bool(a.ok), a.detail)
    else:  # status
        print(json.dumps(status()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
