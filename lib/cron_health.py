#!/usr/bin/env python3
"""Daily watcher for MARVIN's launchd cron jobs.

Answers "did this run, did it fail, why" for the recurring automation jobs
that otherwise only write to log files nobody watches — the same gap that
let cross-machine-merge fail silently on both remotes for at least two
days (2026-07-08 incident). Run once daily, after the last monitored job's
scheduled time, via com.marvin.cron-health.

Only scans bytes appended since the last run (tracked in a state file) so
old, already-seen failures don't re-trigger forever and log files with no
per-line timestamps still work. Writes ~/.claude/logs/cron-health.md,
which CLAUDE.md's session-start check reads.
"""
from __future__ import annotations
import json
import re
from datetime import datetime, timezone
from pathlib import Path

HOME = Path.home()
STATE_PATH = HOME / ".claude" / "logs" / ".cron-health-state.json"
OUTPUT_PATH = HOME / ".claude" / "logs" / "cron-health.md"

FAILURE_PATTERN = re.compile(
    r"failed|error|traceback|denied|timed out|exception", re.IGNORECASE
)

# name -> (scheduled HH:MM, [log paths to scan])
JOBS = {
    "daily-digest": (
        "08:30",
        [".claude/logs/daily-digest.log", ".claude/logs/daily-digest-error.log"],
    ),
    "research-colony": (
        "09:00",
        [".claude/logs/research-colony.log", ".claude/logs/research-colony-error.log"],
    ),
    "cross-machine-merge": (
        "09:30",
        [".claude/logs/cross-machine-merge.log", ".claude/logs/cross-machine-merge-error.log"],
    ),
    "tidy-agent": (
        "03:00",
        [".claude/organize/agent.out.log", ".claude/organize/agent.err.log"],
    ),
}

GRACE_MINUTES = 30


def _load_state() -> dict:
    try:
        return json.loads(STATE_PATH.read_text())
    except Exception:
        return {}


def _save_state(state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=2))


def _new_content(path: Path, last_offset: int) -> tuple[str, int]:
    if not path.exists():
        return "", last_offset
    size = path.stat().st_size
    if size < last_offset:  # log rotated/truncated
        last_offset = 0
    with path.open("rb") as f:
        f.seek(last_offset)
        data = f.read()
    return data.decode("utf-8", errors="replace"), size


def check_job(name: str, scheduled: str, log_paths: list[str], state: dict, now: datetime) -> str | None:
    """Returns a status line if there's something to report, else None."""
    sched_hour, sched_min = (int(x) for x in scheduled.split(":"))
    scheduled_today = now.replace(hour=sched_hour, minute=sched_min, second=0, microsecond=0)
    overdue = (now - scheduled_today).total_seconds() / 60 > GRACE_MINUTES

    ran_today = False
    failures: list[str] = []
    job_state = state.setdefault(name, {})

    for rel in log_paths:
        path = HOME / rel
        first_run_for_log = rel not in job_state
        last_offset = job_state.get(rel, 0)
        new_text, new_offset = _new_content(path, last_offset)
        job_state[rel] = new_offset
        if path.exists() and datetime.fromtimestamp(path.stat().st_mtime, tz=now.tzinfo) >= scheduled_today:
            ran_today = True
        if first_run_for_log:
            continue  # establish baseline only — don't report pre-existing history as new
        for line in new_text.splitlines():
            if FAILURE_PATTERN.search(line):
                failures.append(line.strip())

    if failures:
        sample = failures[:3]
        more = f" (+{len(failures) - 3} more)" if len(failures) > 3 else ""
        return f"**{name}**: {len(failures)} failure indicator(s) since last check{more} — e.g. `{sample[0][:150]}`"
    if overdue and not ran_today:
        return f"**{name}**: scheduled {scheduled}, no log activity since — may not have run today"
    return None


def main() -> None:
    now = datetime.now().astimezone()
    state = _load_state()
    problems = []
    for name, (scheduled, log_paths) in JOBS.items():
        result = check_job(name, scheduled, log_paths, state, now)
        if result:
            problems.append(result)
    _save_state(state)

    ts = now.isoformat()
    if problems:
        body = "\n".join(f"- {p}" for p in problems)
        OUTPUT_PATH.write_text(f"# Cron health — {ts}\n\n{body}\n")
    else:
        OUTPUT_PATH.write_text(f"# Cron health — {ts}\n\nAll monitored jobs ran cleanly.\n")


if __name__ == "__main__":
    main()
