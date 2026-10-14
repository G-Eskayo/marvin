#!/usr/bin/env python3
"""One error log per Mac (marvin#422: errors are never silent).

Every failure MARVIN would otherwise swallow -- a dashboard IPC call, a webhook route, a code-sync pull or push, a
dashboard rebuild, a job's failed run -- appends one JSON line to ~/.claude/logs/errors.jsonl:

    {"t", "machine", "source", "message", "raw"}       (+ "fix": true for something MARVIN repaired itself)

Writers never raise (recording must not break or mask the failure). The log is bounded: when it grows past
MAX_LINES * 1.25 it is trimmed to the newest MAX_LINES and anything older than MAX_AGE_DAYS. Plain causes are worked
out when reading (classify), so JavaScript and bash writers only need the raw text. Health reads `recent` from both
Macs and shows it as "Recent errors".

    error_log.py record --source S --message M [--raw R]     append one error (bash, other languages)
    error_log.py recent [--json] [--hours 24]                folded recent errors, newest first
"""
from __future__ import annotations

import argparse
import fcntl
import json
import os
import re
import socket
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

PATH = Path.home() / ".claude" / "logs" / "errors.jsonl"
MAX_LINES = 2000
MAX_AGE_DAYS = 30
MAX_MESSAGE = 500
MAX_RAW = 4000

# Known failures and the plain cause a person needs. First match wins.
CAUSES = [
    (r"index\.lock'?: File exists", "git is locked by a crashed command"),
    (r"error connecting to api\.github\.com|Could not resolve host|no such host|Network is unreachable|"
     r"getaddrinfo ENOTFOUND|ECONNREFUSED|ETIMEDOUT|connection (refused|timed out)", "no network, or GitHub unreachable"),
    (r"command not found|ENOENT.*spawn|No such file or directory: '(npm|node|gh|git)'", "a job can't find a tool (its PATH is missing Homebrew)"),
    (r"Operation not permitted|EPERM", "macOS privacy blocked it (Full Disk Access)"),
    (r"rate limit|secondary rate|HTTP 403", "GitHub rate limit"),
    (r"No space left on device|ENOSPC", "the disk is full"),
    (r"\bCONFLICT\b|Merge conflict|unmerged files", "a merge conflict needs a person"),
    (r"Authentication failed|gh auth login|HTTP 401|bad credentials", "GitHub sign-in expired"),
]


def _machine() -> str:
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import machine_profile
        return machine_profile.registry_id()
    except Exception:  # noqa: BLE001 -- the log must work even when the profile can't be read
        return socket.gethostname().split(".")[0]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _append(entry: dict, path: Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a+", encoding="utf-8") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        f.flush()
        f.seek(0)
        all_lines = f.read().splitlines()
        if len(all_lines) > MAX_LINES * 1.25:
            cutoff = (_now_for(entry) - timedelta(days=MAX_AGE_DAYS)).isoformat()
            keep = []
            for l in all_lines[-MAX_LINES:]:
                try:
                    if json.loads(l).get("t", "") >= cutoff:
                        keep.append(l)
                except ValueError:
                    continue
            f.seek(0)
            f.truncate()
            f.write("".join(k + "\n" for k in keep))


def _now_for(entry: dict) -> datetime:
    try:
        return datetime.fromisoformat(entry["t"])
    except (KeyError, ValueError):
        return _now()


def record(source: str, message: str, raw: str = "", *, path: Path | None = None, now: datetime | None = None,
           machine: str | None = None, fix: bool = False) -> None:
    """Append one error. Never raises."""
    try:
        entry = {"t": (now or _now()).isoformat(), "machine": machine or _machine(), "source": str(source)[:100],
                 "message": str(message)[:MAX_MESSAGE], "raw": str(raw or "")[:MAX_RAW]}
        if fix:
            entry["fix"] = True
        _append(entry, Path(path or PATH))
    except Exception:  # noqa: BLE001
        pass


def record_fix(source: str, message: str, **kw) -> None:
    """Something MARVIN repaired on its own: logged, but never counted as an error."""
    record(source, message, fix=True, **kw)


def classify(text: str) -> dict:
    for pattern, cause in CAUSES:
        if re.search(pattern, text or "", re.I):
            return {"cause": cause, "known": True}
    first = next((l.strip() for l in (text or "").splitlines() if l.strip()), "unknown error")
    return {"cause": first[:200], "known": False}


def recent(*, path: Path | None = None, now: datetime | None = None, hours: float = 24, include_fixes: bool = False) -> list[dict]:
    """Errors from the last `hours`, folded by (machine, source, cause), newest first."""
    now = now or _now()
    since = (now - timedelta(hours=hours)).isoformat()
    try:
        raw_lines = Path(path or PATH).read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    groups: dict[tuple, dict] = {}
    for l in raw_lines:
        try:
            e = json.loads(l)
        except ValueError:
            continue
        if not isinstance(e, dict) or e.get("t", "") < since or (e.get("fix") and not include_fixes):
            continue
        c = classify(f"{e.get('raw', '')}\n{e.get('message', '')}") if not e.get("fix") else {"cause": e.get("message", ""), "known": True}
        key = (e.get("machine"), e.get("source"), c["cause"])
        g = groups.get(key)
        if g is None:
            groups[key] = {"machine": e.get("machine"), "source": e.get("source"), "cause": c["cause"], "known": c["known"],
                           "message": e.get("message", ""), "raw": e.get("raw", ""), "count": 1, "first_t": e["t"], "last_t": e["t"],
                           **({"fix": True} if e.get("fix") else {})}
        else:
            g["count"] += 1
            if e["t"] >= g["last_t"]:
                g.update(last_t=e["t"], message=e.get("message", ""), raw=e.get("raw", ""))
            g["first_t"] = min(g["first_t"], e["t"])
    return sorted(groups.values(), key=lambda g: g["last_t"], reverse=True)


def severity(group: dict, now: datetime | None = None) -> str:
    """Red while an error keeps repeating within the last hour; amber otherwise (it's in the window)."""
    now = now or _now()
    try:
        recent_hour = now - datetime.fromisoformat(group["last_t"]) <= timedelta(hours=1)
    except (KeyError, ValueError):
        return "amber"
    return "red" if recent_hour and group.get("count", 1) >= 2 else "amber"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("record")
    r.add_argument("--source", required=True)
    r.add_argument("--message", required=True)
    r.add_argument("--raw", default="")
    q = sub.add_parser("recent")
    q.add_argument("--json", action="store_true")
    q.add_argument("--hours", type=float, default=24)
    a = ap.parse_args(argv)
    if a.cmd == "record":
        record(a.source, a.message, a.raw, path=PATH)
        return 0
    groups = recent(path=PATH, hours=a.hours)
    if a.json:
        print(json.dumps(groups))
    else:
        for g in groups:
            print(f"{g['last_t'][:16]}  {g['machine']}  {g['source']}  ×{g['count']}  {g['cause']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
