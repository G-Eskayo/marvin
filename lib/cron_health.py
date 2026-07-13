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

Also checks code_sync.py's two synced repos (~/.agents, ~/.claude), added
2026-07-12 after a real incident (see ADR 0022): everything that went wrong
— a machine silently never being a real git clone, conflict markers
propagating through unattended cron cycles — was discovered by accident,
days after it started, while doing unrelated work. Two checks close that
gap: **convergence** (is every known machine actually at the same commit
for each repo — an SSH-based check, since divergence is inherently a
cross-machine question, unlike the log-scanning JOBS checks above) and
**integrity** (does any tracked file in this machine's own copy contain
literal git conflict markers — local-only, since each machine's own
cron-health run already covers itself, no need to reach across SSH twice).
"""
from __future__ import annotations
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

HOME = Path.home()
STATE_PATH = HOME / ".claude" / "logs" / ".cron-health-state.json"
OUTPUT_PATH = HOME / ".claude" / "logs" / "cron-health.md"

sys.path.insert(0, str(HOME / ".agents" / "lib"))
from machine_profile import remote_devices  # noqa: E402

FAILURE_PATTERN = re.compile(
    r"failed|error|traceback|denied|timed out|exception", re.IGNORECASE
)
CONFLICT_MARKER_RE = re.compile(r"^(<{7}|={7}|>{7})(?: |$)", re.MULTILINE)
SSH_OPTS = ["-o", "ConnectTimeout=5", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=accept-new"]

# name -> path relative to $HOME, for the two repos code_sync.py keeps in sync
SYNCED_REPOS = {
    "~/.agents": ".agents",
    "~/.claude": ".claude",
}

# organize/'s classification code, folded from its own disconnected nested
# git repo into ~/.claude's allow-list (2026-07-13) after the whole
# directory vanished from one machine without a trace. See
# check_organize_sync() for why this needs its own check.
ORGANIZE_TRACKED_FILES = (
    "organize/tidy_common.py",
    "organize/tidy_agent.py",
    "organize/sort_desktop.py",
    "organize/find_file.py",
    "organize/triage_iceberg.py",
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


def check_repo_convergence(display_name: str, rel_path: str) -> list[str]:
    """Is every other known machine's HEAD the same as this machine's, for
    this repo? Divergence means code_sync.py's push/pull cycle has stalled
    somewhere — a hook not firing, a machine offline for days, a conflict
    sitting unresolved — the exact class of thing that went unnoticed for a
    week before ADR 0021/0022."""
    repo = HOME / rel_path
    if not (repo / ".git").exists():
        return []
    local_head = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True
    ).stdout.strip()
    if not local_head:
        return []

    problems = []
    for device_id, info in remote_devices().items():
        host = info.get("tailscale_hostname")
        if not host:
            continue
        result = subprocess.run(
            ["ssh", *SSH_OPTS, host, f"git -C {rel_path} rev-parse HEAD"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode != 0:
            problems.append(f"**{display_name} convergence**: couldn't reach {device_id} to compare — {result.stderr.strip()[:150] or 'offline or unreachable'}")
            continue
        remote_head = result.stdout.strip()
        if remote_head and remote_head != local_head:
            problems.append(f"**{display_name} convergence**: {device_id} is at `{remote_head[:8]}`, this machine is at `{local_head[:8]}` — a push/pull cycle may be stalled")
    return problems


def check_repo_integrity(display_name: str, rel_path: str) -> list[str]:
    """Does any tracked file in this machine's copy contain literal git
    conflict markers? Local only — catches corruption from an unresolved
    stash-pop/merge conflict before an automated push can propagate it, per
    the incident in ADR 0022."""
    repo = HOME / rel_path
    if not (repo / ".git").exists():
        return []
    # sorted(set(...)): during an active unresolved merge, `git ls-files`
    # lists a conflicted path once per stage (base/ours/theirs) — found via
    # this exact check reporting "sync-log.md, sync-log.md, sync-log.md" on
    # a real conflict.
    files = sorted(set(subprocess.run(
        ["git", "-C", str(repo), "ls-files"], capture_output=True, text=True
    ).stdout.splitlines()))
    broken = []
    for f in files:
        path = repo / f
        try:
            text = path.read_text(errors="ignore")
        except Exception:
            continue
        if CONFLICT_MARKER_RE.search(text):
            broken.append(f)
    if broken:
        sample = ", ".join(broken[:5])
        more = f" (+{len(broken) - 5} more)" if len(broken) > 5 else ""
        return [f"**{display_name} integrity**: {len(broken)} file(s) with literal conflict markers{more} — `{sample}`"]
    return []


def check_organize_sync() -> list[str]:
    """Neither check above would have caught the 2026-07-13 incident:
    check_repo_convergence only compares HEAD, which a deleted-but-
    uncommitted file doesn't move, and check_repo_integrity's read_text()
    silently skips a file that's gone missing rather than flagging it. This
    checks the specific failure mode directly — a tracked organize/ file
    deleted or edited locally without being committed, so it can't reach
    the other machine at all until someone notices by hand."""
    repo = HOME / ".claude"
    if not (repo / ".git").exists():
        return []
    problems = []
    deleted = subprocess.run(
        ["git", "-C", str(repo), "ls-files", "-d", "--", "organize/"],
        capture_output=True, text=True,
    ).stdout.splitlines()
    if deleted:
        problems.append(
            f"**organize/ sync**: {len(deleted)} tracked file(s) missing from disk — "
            f"`{', '.join(deleted)}` — won't reach the other machine until restored and committed"
        )
    modified = subprocess.run(
        ["git", "-C", str(repo), "diff", "--name-only", "--", "organize/"],
        capture_output=True, text=True,
    ).stdout.splitlines()
    if modified:
        problems.append(
            f"**organize/ sync**: {len(modified)} tracked file(s) locally modified but not committed — "
            f"`{', '.join(modified)}` — won't sync to other machines until committed"
        )
    return problems


def main() -> None:
    now = datetime.now().astimezone()
    state = _load_state()
    problems = []
    for name, (scheduled, log_paths) in JOBS.items():
        result = check_job(name, scheduled, log_paths, state, now)
        if result:
            problems.append(result)
    for display_name, rel_path in SYNCED_REPOS.items():
        problems.extend(check_repo_convergence(display_name, rel_path))
        problems.extend(check_repo_integrity(display_name, rel_path))
    problems.extend(check_organize_sync())
    _save_state(state)

    ts = now.isoformat()
    if problems:
        body = "\n".join(f"- {p}" for p in problems)
        OUTPUT_PATH.write_text(f"# Cron health — {ts}\n\n{body}\n")
    else:
        OUTPUT_PATH.write_text(f"# Cron health — {ts}\n\nAll monitored jobs ran cleanly.\n")


if __name__ == "__main__":
    main()
