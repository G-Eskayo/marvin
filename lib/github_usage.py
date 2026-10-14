#!/usr/bin/env python3
"""github_usage.py — this Mac's GitHub use, for the Metrics tab's GitHub section.

Read from the GitHub gate's own logs (bin/gh): every gh call (~/.claude/logs/gh-calls.jsonl) and every reading of
GitHub's allowance (gh-budget.jsonl). Both Macs and every job share one allowance, so this is how to see what spends
it, when it ran low, and what was refused or held back. Not synced (the call log names folders); the dashboard reads
the other Mac's over ssh (lib/usage_report.py).

    github_usage.py     print the summary as JSON (30 days of hourly aggregates; ~/.claude/logs/gh-usage-hourly.json caches them)
"""
from __future__ import annotations
import fcntl
import json
import os
import socket
import sys
import threading
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

LOGS = Path.home() / ".claude" / "logs"
CALLS_PATH = LOGS / "gh-calls.jsonl"
BUDGET_PATH = LOGS / "gh-budget.jsonl"
GROUPS = ("dashboard", "pipeline", "tests", "health", "people", "other")
PIPELINE = ("ticket_pipeline", "ticket-pipeline", "run_ticket", "ticket_queue", "rework_status", "ticket_evidence",
            "ticket_agents", "dispatch", "mr_raiser", "merge", "cleanup", "project_onboard", "code-sync", "code_sync")


def group_of(caller: str) -> str:
    c = (caller or "").lower()
    if "marvin-metrics" in c or "dashboard" in c:
        return "dashboard"
    if "pytest" in c:
        return "tests"
    if "health" in c:
        return "health"
    if any(p in c for p in PIPELINE):
        return "pipeline"
    if c in ("zsh", "bash", "sh", "fish", "shell", "login", "-zsh") or "claude" in c:
        return "people"
    return "other"


def display_name(caller: str) -> str:
    """One name per program: the dashboard app's launchd label carries process ids that change every launch."""
    c = caller or "?"
    if c.startswith("application.") and "marvin-metrics" in c:
        return "MARVIN dashboard app"
    return c.replace("com.marvin.", "") if c.startswith("com.marvin.") else c


def read_jsonl(path: Path) -> list[dict]:
    try:
        lines = Path(path).read_text().splitlines()
    except OSError:
        return []
    out = []
    for l in lines:
        try:
            out.append(json.loads(l))
        except ValueError:
            continue
    return out


# ── hourly aggregates (marvin#417) ──────────────────────────────────────────
# The chart shows each hour's low point of the allowance, not every reading (GitHub refills it hourly, so raw readings
# draw a sawtooth). Hours are kept for 30 days in a small cache that only reads the new bytes of each log, so neither
# the payload nor the read time grows with how long the gate has been running.

HOURLY_PATH = LOGS / "gh-usage-hourly.json"
KEEP_HOURS = 720
CACHE_VERSION = 1
TOP_PER_HOUR = 5


def _hour_key(t: float) -> str:
    return datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%dT%H:00Z")


def _num(v):
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _empty_hour() -> dict:
    return {"total": 0, "refused": 0, "deferred": 0, "groups": {g: 0 for g in GROUPS}, "callers": {},
            "budget_min": None, "budget_readings": 0}


def _new_cache() -> dict:
    return {"version": CACHE_VERSION, "calls": {"offset": 0, "ino": None}, "budget": {"offset": 0, "ino": None},
            "hours": {}, "latest_budget": None}


def _add_call(cache: dict, r: dict) -> None:
    t = _num(r.get("t"))
    if t is None:
        return
    h = cache["hours"].setdefault(_hour_key(t), _empty_hour())
    caller = display_name(str(r.get("caller", "?")))
    h["total"] += 1
    h["groups"][group_of(caller)] += 1
    h["refused"] += 1 if r.get("refused") else 0
    h["deferred"] += 1 if r.get("deferred") else 0
    c = h["callers"].setdefault(caller, {"calls": 0, "refused": 0, "deferred": 0, "cmds": {}})
    c["calls"] += 1
    c["refused"] += 1 if r.get("refused") else 0
    c["deferred"] += 1 if r.get("deferred") else 0
    cmd = r.get("cmd") or "(other)"
    c["cmds"][cmd] = c["cmds"].get(cmd, 0) + 1


def _add_reading(cache: dict, b: dict) -> None:
    at, g = _num(b.get("at")), _num(b.get("graphql"))
    if at is None or g is None:
        return
    h = cache["hours"].setdefault(_hour_key(at), _empty_hour())
    h["budget_min"] = g if h["budget_min"] is None else min(h["budget_min"], g)
    h["budget_readings"] += 1
    latest = cache.get("latest_budget")
    if latest is None or at >= latest["at"]:
        cache["latest_budget"] = {"at": at, "graphql": g, "core": _num(b.get("core"))}


def _parse_lines(data: bytes) -> list[dict]:
    out = []
    for line in data.split(b"\n"):
        if not line.strip():
            continue
        try:
            r = json.loads(line)
        except ValueError:
            continue
        if isinstance(r, dict):
            out.append(r)
    return out


def _read_new(path: Path, state: dict) -> tuple[list[dict], bool]:
    """Rows appended since the last read, and whether the file was replaced or shrank (then rebuild everything).
    A half-written last line is left for next time."""
    try:
        st = os.stat(path)
    except OSError:
        return [], state["offset"] > 0
    if (state["ino"] is not None and st.st_ino != state["ino"]) or st.st_size < state["offset"]:
        return [], True
    with open(path, "rb") as f:
        f.seek(state["offset"])
        data = f.read()
    end = data.rfind(b"\n") + 1
    state["offset"] += end
    state["ino"] = st.st_ino
    return _parse_lines(data[:end]), False


def _load_cache(path: Path) -> dict:
    try:
        c = json.loads(Path(path).read_text())
        if isinstance(c, dict) and c.get("version") == CACHE_VERSION and isinstance(c.get("hours"), dict):
            return c
    except (OSError, ValueError):
        pass
    return _new_cache()


def _save_cache(path: Path, cache: dict) -> None:
    tmp = Path(path).with_name(f".{Path(path).name}.{os.getpid()}.{threading.get_ident()}.tmp")
    tmp.write_text(json.dumps(cache))
    os.replace(tmp, path)


def _prune(cache: dict, now: datetime) -> None:
    oldest = _hour_key((now - timedelta(hours=KEEP_HOURS - 1)).timestamp())
    for k in [k for k in cache["hours"] if k < oldest]:
        del cache["hours"][k]


def update_cache(now: datetime, calls_path: Path, budget_path: Path, cache_path: Path) -> dict:
    """Bring the hourly cache up to date with whatever the gate has logged since last time."""
    Path(cache_path).parent.mkdir(parents=True, exist_ok=True)
    with open(Path(cache_path).with_suffix(".lock"), "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        cache = _load_cache(cache_path)
        for _ in range(2):  # a replaced log means rebuilding from scratch, once
            calls, reset_c = _read_new(calls_path, cache["calls"])
            budget, reset_b = _read_new(budget_path, cache["budget"])
            if reset_c or reset_b:
                cache = _new_cache()
                continue
            for r in calls:
                _add_call(cache, r)
            for b in budget:
                _add_reading(cache, b)
            break
        _prune(cache, now)
        _save_cache(cache_path, cache)
        return cache


def _render(cache: dict, now: datetime, hours: int) -> dict:
    end = now.replace(minute=0, second=0, microsecond=0)
    keys = [_hour_key((end - timedelta(hours=hours - 1 - i)).timestamp()) for i in range(hours)]
    out_hours, day = [], defaultdict(lambda: {"calls": 0, "refused": 0, "deferred": 0, "cmds": Counter()})
    for i, k in enumerate(keys):
        h = cache["hours"].get(k) or _empty_hour()
        top = sorted(h["callers"].items(), key=lambda kv: (-kv[1]["calls"], kv[0]))[:TOP_PER_HOUR]
        out_hours.append({"hour": k, "total": h["total"], "refused": h["refused"], "deferred": h["deferred"],
                          "groups": dict(h["groups"]), "budget_min": h["budget_min"], "budget_readings": h["budget_readings"],
                          "callers": [{"caller": n, "group": group_of(n), "calls": c["calls"]} for n, c in top]})
        if i >= hours - 24:
            for n, c in h["callers"].items():
                d = day[n]
                d["calls"] += c["calls"]
                d["refused"] += c["refused"]
                d["deferred"] += c["deferred"]
                d["cmds"].update(c["cmds"])
    top = sorted(day.items(), key=lambda kv: (-kv[1]["calls"], kv[0]))[:10]
    return {
        "machine": socket.gethostname().split(".")[0],
        "generated_at": now.isoformat(),
        "hours": out_hours,
        "top": [{"caller": k, "group": group_of(k), "calls": v["calls"], "refused": v["refused"], "deferred": v["deferred"],
                 "commands": [{"cmd": c, "calls": n} for c, n in v["cmds"].most_common(4)]} for k, v in top],
        "latest_budget": cache.get("latest_budget"),
    }


def summarize(calls: list[dict], budget: list[dict], now: datetime, hours: int = KEEP_HOURS) -> dict:
    """The summary from raw rows (same aggregation as the cache, without one)."""
    cache = _new_cache()
    for r in calls:
        _add_call(cache, r)
    for b in budget:
        _add_reading(cache, b)
    return _render(cache, now, hours)


def report(now: datetime | None = None, calls_path: Path | None = None, budget_path: Path | None = None,
           cache_path: Path | None = None, hours: int = KEEP_HOURS) -> dict:
    now = now or datetime.now(timezone.utc)
    cache = update_cache(now, Path(calls_path or CALLS_PATH), Path(budget_path or BUDGET_PATH), Path(cache_path or HOURLY_PATH))
    return _render(cache, now, hours)


def main(argv: list[str]) -> int:
    print(json.dumps(report()))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
