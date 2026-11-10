#!/usr/bin/env python3
"""Stamped copies: every per-Mac file says which Mac made it and how old it is (marvin#1223; piece 2 of
instance/docs/plans/data-freshness-2026-11-09.md). The JS twin is dashboard/electron/main/stamped.js; both run
dashboard/test/fixtures/stamped_cases.json, so they can't drift.

On 2026-11-09 the laptop showed its own 11-day-old Health file as current ("9 criticals vs 16"), and its frozen board
registry still listed an archived repo. A copy that stops updating looked identical to a live one. The fix is the
envelope the github feed already uses (github_feed.js): flat top-level keys on the file's own JSON object,

    host           the producing Mac's registry id        hardware_uuid  the same Mac, surviving a rename
    generated_at   when the data was made                 alive_at       when the producer last confirmed it current
    tolerance_s    how old it may get before it is stale

Flat, not nested, so a reader that predates the stamp (on the other Mac, mid-rollout) keeps working. `read` returns a
Copy: the value plus host, age and stale. Age is measured on the reader's clock from the newer of generated_at and
alive_at, never negative (a future time is age 0 and flagged). A file with no stamp is "legacy": dated by its own
generated_at or, failing that, its mtime, with the caller's default tolerance. Exactly at tolerance is not stale.
No file, or one that isn't a JSON object, is "missing" (and stale), never an exception.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

UTC = timezone.utc
STAMP_KEYS = ("host", "hardware_uuid", "generated_at", "alive_at", "tolerance_s")


@dataclass
class Copy:
    value: dict | None
    host: str | None = None
    hardware_uuid: str | None = None
    generated_at: str | None = None
    age_s: int | None = None
    tolerance_s: int | None = None
    stale: bool = False
    legacy: bool = False
    missing: bool = False
    future: bool = False
    path: str | None = None


def _me() -> tuple[str | None, str | None]:
    try:
        import machine_profile
        return machine_profile.registry_id(), (machine_profile.load_or_build().get("hardware_uuid") or None)
    except Exception:  # noqa: BLE001  (a stamp without a host still dates the file)
        return None, None


def _time(v) -> datetime | None:
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        try:
            return datetime.fromtimestamp(v / 1000 if v > 1e11 else v, tz=UTC)  # ms (the github feed) or seconds
        except (OverflowError, OSError, ValueError):
            return None
    if isinstance(v, str):
        try:
            t = datetime.fromisoformat(v.replace("Z", "+00:00"))
        except ValueError:
            return None
        return t if t.tzinfo else t.replace(tzinfo=UTC)
    return None


def stamp(data: dict, *, tolerance_s: int, now: datetime | None = None, alive_at: datetime | None = None) -> dict:
    """`data` with the envelope added. A writer's own generated_at is kept; alive_at is now unless given."""
    if not isinstance(data, dict):
        raise TypeError("only a JSON object can carry a stamp")
    if isinstance(tolerance_s, bool) or not isinstance(tolerance_s, int) or tolerance_s <= 0:
        raise ValueError("tolerance_s must be a positive whole number of seconds")
    now = (now or datetime.now(UTC)).astimezone(UTC)
    host, uuid = _me()
    out = dict(data)
    if host:
        out["host"] = host
    if uuid:
        out["hardware_uuid"] = uuid
    out.setdefault("generated_at", now.isoformat())
    out["alive_at"] = (alive_at or now).astimezone(UTC).isoformat()
    out["tolerance_s"] = tolerance_s
    return out


def write(path: Path, data: dict, *, tolerance_s: int, now: datetime | None = None, indent: int | None = 2) -> dict:
    """Stamp and write whole or not at all (temp file + rename): a reader never sees half a file."""
    out = stamp(data, tolerance_s=tolerance_s, now=now)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(out, indent=indent) + "\n")
    os.replace(tmp, path)
    return out


def from_data(data, *, now: datetime | None = None, default_tolerance_s: int = 600, mtime: float | None = None,
              path: str | None = None) -> Copy:
    """A Copy from already-parsed JSON (a file, or a peer's reply)."""
    if not isinstance(data, dict):
        return Copy(value=None, missing=True, stale=True, path=path)
    now = now or datetime.now(UTC)
    legacy = not data.get("host")
    tol = data.get("tolerance_s")
    tol = tol if isinstance(tol, int) and not isinstance(tol, bool) and tol > 0 else default_tolerance_s
    times = [t for t in (_time(data.get("generated_at")), _time(data.get("alive_at"))) if t]
    if not times and legacy and mtime is not None:
        times = [datetime.fromtimestamp(mtime, tz=UTC)]
    if not times:
        return Copy(value=data, host=data.get("host"), hardware_uuid=data.get("hardware_uuid"), age_s=None,
                    tolerance_s=tol, stale=True, legacy=legacy, path=path)
    newest = max(times)
    raw = (now - newest).total_seconds()
    age = max(0, int(round(raw)))
    return Copy(value=data, host=data.get("host"), hardware_uuid=data.get("hardware_uuid"),
                generated_at=data.get("generated_at") if isinstance(data.get("generated_at"), str) else None,
                age_s=age, tolerance_s=tol, stale=age > tol, legacy=legacy, future=raw < 0, path=path)


def read(path: Path, *, now: datetime | None = None, default_tolerance_s: int = 600) -> Copy:
    path = Path(path)
    try:
        text = path.read_text(errors="replace")
        mtime = path.stat().st_mtime
        data = json.loads(text)
    except (OSError, ValueError):
        return Copy(value=None, missing=True, stale=True, path=str(path))
    return from_data(data, now=now, default_tolerance_s=default_tolerance_s, mtime=mtime, path=str(path))


def producer(c: Copy, registry: dict) -> str | None:
    """The registry id of the Mac that made this copy: by hardware_uuid first (a Mac can be renamed), else host."""
    if c.hardware_uuid:
        for dev, info in (registry or {}).items():
            if (info or {}).get("hardware_uuid", "").upper() == c.hardware_uuid.upper():
                return dev
    return c.host


def _ago(age_s: int | None) -> str:
    if age_s is None:
        return "age unknown"
    if age_s < 60:
        return "just now"
    if age_s < 3600:
        return f"{age_s // 60} min ago"
    if age_s < 2 * 86400:
        return f"{age_s // 3600} h ago"
    return f"{age_s // 86400} days ago"


def describe(c: Copy, registry: dict, this_mac: str | None = None) -> str:
    """"Mac mini, as of 2 min ago" (+ " · stale"). The words every screen uses for a copy's source and age."""
    if c.missing:
        return "no data yet"
    dev = producer(c, registry)
    if dev is None:
        who = "this Mac (unstamped)" if this_mac else "an unknown Mac (unstamped)"
    else:
        who = ((registry or {}).get(dev) or {}).get("label") or dev
    return f"{who}, as of {_ago(c.age_s)}" + (" · stale" if c.stale else "")


def newer(a: Copy, b: Copy) -> Copy:
    """The fresher of two copies of the same file (ours and the producer's): the one with the smaller age."""
    if a.missing or a.age_s is None:
        return b if not b.missing else a
    if b.missing or b.age_s is None:
        return a
    return a if a.age_s <= b.age_s else b
