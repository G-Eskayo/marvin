"""Parallel ticket dispatch: the settings and the guard rails (ADR 0052, ticket #194).

`config/dispatch.json` is one synced file. With `parallel` off every other field is ignored and each machine
runs one ticket at a time, as before. `can_start_another` answers "may this machine start another ticket right
now?" with a plain-language reason when not; every reader is injected, so the rules are tested without a
network or disk. A guard that cannot be read never blocks (an unreadable budget must not stall dispatch).
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

PATH = Path(__file__).resolve().parents[1] / "config" / "dispatch.json"
MAX_LIMIT = 8

DEFAULTS = {
    "parallel": False,
    "max_total": 2,
    "max_per_project": 1,
    "machine_slots": {"mac-mini-1": 2, "macbook-pro-1": 1},
    "guards": {"min_disk_gb": 15, "min_github_budget_pct": 20},
}


def _whole(v) -> bool:
    return isinstance(v, int) and not isinstance(v, bool) and 1 <= v <= MAX_LIMIT


def validate(raw: dict) -> tuple[dict, list[str]]:
    """The settings with every invalid field replaced by its default, and one sentence per field that was invalid."""
    raw = raw if isinstance(raw, dict) else {}
    out = json.loads(json.dumps(DEFAULTS))
    problems: list[str] = []
    if "parallel" in raw:
        if isinstance(raw["parallel"], bool):
            out["parallel"] = raw["parallel"]
        else:
            problems.append("parallel must be true or false")
    for key in ("max_total", "max_per_project"):
        if key in raw:
            if _whole(raw[key]):
                out[key] = raw[key]
            else:
                problems.append(f"{key} must be a whole number from 1 to {MAX_LIMIT}")
    if isinstance(raw.get("machine_slots"), dict):
        for machine, n in raw["machine_slots"].items():
            if _whole(n):
                out["machine_slots"][machine] = n
            else:
                problems.append(f"machine_slots.{machine} must be a whole number from 1 to {MAX_LIMIT}")
    guards = raw.get("guards")
    if isinstance(guards, dict):
        for key, hi in (("min_disk_gb", 10_000), ("min_github_budget_pct", 100)):
            if key in guards:
                v = guards[key]
                if isinstance(v, (int, float)) and not isinstance(v, bool) and 0 <= v <= hi:
                    out["guards"][key] = v
                else:
                    problems.append(f"guards.{key} must be a number from 0 to {hi}")
    return out, problems


def load(path: Path | None = None) -> dict:
    """Missing, unreadable or invalid settings fall back to the safe defaults, field by field, never to an error."""
    try:
        raw = json.loads(Path(path or PATH).read_text())
    except (OSError, ValueError):
        return json.loads(json.dumps(DEFAULTS))
    return validate(raw)[0]


def save(settings: dict, path: Path | None = None) -> dict:
    """Write validated settings atomically; invalid ones are refused (ValueError) and nothing is written."""
    clean, problems = validate(settings)
    if problems:
        raise ValueError("; ".join(problems))
    target = Path(path or PATH)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=target.parent, suffix=".tmp")
    with os.fdopen(fd, "w") as f:
        json.dump(clean, f, indent=2)
        f.write("\n")
    os.replace(tmp, target)
    return clean


def effective_limit(settings: dict, machine: str) -> int:
    """Tickets this machine may run at once: one when parallel is off, else the smaller of its slots and max_total."""
    if not settings.get("parallel"):
        return 1
    return max(1, min(settings["machine_slots"].get(machine, 1), settings["max_total"]))


def _safe(reader, *args):
    try:
        return reader(*args)
    except Exception:  # noqa: BLE001 -- an unreadable guard must not stall dispatch
        return None


def can_start_another(machine: str, settings: dict, *, slots_in_use, disk_free_gb, github_budget_pct,
                      breaker_tripped, missing_tools) -> tuple[bool, str | None]:
    limit = effective_limit(settings, machine)
    used = slots_in_use(machine)
    if used >= limit:
        return False, f"{machine} is full: {used} of {limit} slots in use"
    if not settings.get("parallel"):
        return True, None  # off: exactly today's behaviour, no extra guards
    g = settings["guards"]
    disk = _safe(disk_free_gb, machine)
    if disk is not None and disk < g["min_disk_gb"]:
        return False, f"disk {disk:g} GB free on {machine}, minimum {g['min_disk_gb']:g}"
    pct = _safe(github_budget_pct)
    if pct is not None and pct < g["min_github_budget_pct"]:
        return False, f"GitHub request budget {pct:g}% left, minimum {g['min_github_budget_pct']:g}%"
    trips = _safe(breaker_tripped) or []
    if trips:
        t = trips[0]
        return False, f"circuit breaker tripped for {str(t.get('project', '?')).split('/')[-1]}: {t.get('signature', '?')}"
    missing = _safe(missing_tools, machine) or []
    if missing:
        return False, f"{machine} lacks tools the project needs: {', '.join(missing)}"
    return True, None


def _cli(argv: list[str]) -> int:
    """`dispatch_concurrency.py get` prints the settings; `set '<json>'` validates and saves them (the dashboard's
    control), exiting 1 with the reasons on stderr if any field is invalid."""
    import sys
    if argv[:1] == ["get"]:
        print(json.dumps(load()))
        return 0
    if argv[:1] == ["set"] and len(argv) == 2:
        try:
            print(json.dumps(save(json.loads(argv[1]))))
            return 0
        except (ValueError, TypeError) as exc:
            print(str(exc), file=sys.stderr)
            return 1
    print("usage: dispatch_concurrency.py get | set '<json>'", file=sys.stderr)
    return 2


if __name__ == "__main__":
    import sys
    sys.exit(_cli(sys.argv[1:]))
