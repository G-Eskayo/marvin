#!/usr/bin/env python3
"""Pipeline purpose: diagnose why a PR hasn't been raised or a ticket isn't moving.

The reason ladder (I5 from ADR 0080): when a ticket is ready but no PR was raised,
apply reasons in order: breaker trip → stale code → guard refusal → stage failure → no run → unknown.

Each reason is a pure function that returns None (reason doesn't apply) or a detail string.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path


def pr_raised_since(repo: str, now: datetime, days: int = 1) -> str | None:
    """Check if a PR for this repo was raised in the last `days`. Returns None if one was raised;
    otherwise a reason string."""
    try:
        import subprocess
        import json as j
        result = subprocess.run(
            ["gh", "pr", "list", "--repo", repo, "--state", "open", "--json", "number,createdAt", "-L", "50"],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode != 0:
            return None
        prs = j.loads(result.stdout)
        threshold = now - timedelta(days=days)
        for pr in prs:
            try:
                created = datetime.fromisoformat(pr["createdAt"].replace("Z", "+00:00"))
                if created >= threshold:
                    return None
            except (ValueError, KeyError):
                continue
    except Exception:
        pass
    return f"no PR was raised in the last {days} day(s)"


def stage_failure_reason(repo: str | None, ticket_number: int, now: datetime, stages_dir: Path | None = None,
                         n_recent: int = 3) -> str | None:
    """Check if the ticket's most recent stage failed. Returns None if no failure;
    otherwise a reason string with failure details (last N failures)."""
    if stages_dir is None:
        stages_dir = Path.home() / ".claude" / "logs" / "ticket-stages"
    try:
        import ticket_stages as ts
        old_dir = ts.STAGES_DIR
        ts.STAGES_DIR = stages_dir
        try:
            events = ts.read_stages(ticket_number, repo)
        finally:
            ts.STAGES_DIR = old_dir
    except Exception:
        events = []
    if not events:
        return None
    failures = [e for e in events if e.get("status") == "failed"]
    if not failures:
        return None
    recent_failures = failures[-n_recent:]
    details = []
    for f in recent_failures:
        stage = f.get("stage", "?")
        detail = f.get("detail", "")[:100]
        details.append(f"{stage}: {detail}" if detail else stage)
    return f"stage failed: {'; '.join(details)}"


def no_run_dispatched(repo: str, ticket_number: int, now: datetime, job_log_path: Path | None = None,
                      hours: int = 4) -> str | None:
    """Check if no run was dispatched for this ticket in the last `hours`. Returns None if
    a run was dispatched; otherwise a reason string."""
    if job_log_path is None:
        job_log_path = Path.home() / ".claude" / "logs" / "jobs" / "ticket-pipeline.json"
    if not job_log_path.exists():
        return "ticket-pipeline job log not found"
    try:
        data = json.loads(job_log_path.read_text())
        runs = data.get("runs", [])
        threshold = now - timedelta(hours=hours)
        for run in reversed(runs[-20:]):
            try:
                started = datetime.fromisoformat(run["started_at"].replace("Z", "+00:00"))
                if started < threshold:
                    break
                for step in run.get("steps", []):
                    step_detail = step.get("detail", "")
                    if f"#{ticket_number}" in step_detail or f"ticket {ticket_number}" in step_detail:
                        return None
            except (ValueError, KeyError, TypeError):
                continue
    except Exception:
        return "couldn't read ticket-pipeline job log"
    return f"no run dispatched in the last {hours}h"


def guard_refusal_reason(repo: str | None = None) -> str | None:
    """Check if the guard (failure_breaker) has refused the repo. Returns None if not;
    otherwise a reason string."""
    try:
        import failure_breaker
        trips = failure_breaker.tripped(project=repo)
        if trips:
            sigs = [t.get("signature") for t in trips]
            detail = "; ".join(sigs[:3])
            return f"breaker refused: {detail}"
    except Exception:
        pass
    return None


def missed_purpose(repo: str, machine: str, now: datetime, ready_count: int,
                   breaker_trips: list[dict] | None = None, job_runs: dict | None = None,
                   stages_dir: Path | None = None) -> tuple[str | None, str | None]:
    """Apply the reason ladder to explain why a PR hasn't been raised.

    Returns (None, None) if a PR was raised or if there are no ready tickets.
    Otherwise returns (reason_id, reason_detail) where reason_id is used for Health card IDs."""
    if ready_count == 0:
        return (None, None)
    if stages_dir is None:
        stages_dir = Path.home() / ".claude" / "logs" / "ticket-stages"
    breaker_trips = breaker_trips or []
    job_runs = job_runs or {}

    for trip in breaker_trips:
        if trip.get("project") == repo or trip.get("project") == "*":
            reason = trip.get("example", trip.get("signature", "circuit breaker"))
            return ("breaker-trip", reason)

    code_stale = guard_refusal_reason(repo)
    if code_stale:
        return ("stale-code", code_stale)

    if pr_raised_since(repo, now, days=1) is None:
        return (None, None)

    stage_reason = stage_failure_reason(repo, 0, now, stages_dir)
    if stage_reason:
        return ("stage-failed", stage_reason)

    job_path = job_runs.get("path") if job_runs else None
    dispatch_reason = no_run_dispatched(repo, 0, now, job_log_path=job_path, hours=4)
    if dispatch_reason:
        return ("no-run", dispatch_reason)

    return ("unknown", "no PR raised but no specific reason identified")


def due_blocks(repo: str, now: datetime) -> tuple[str, str] | None:
    """Decide amber vs red for due tickets. Returns (severity, detail) or None if no blocking due tickets."""
    try:
        import ticket_agents as ta
        due = ta.due_for_repo(repo)
        if not due:
            return None
        due_date = due.get("date")
        if not due_date:
            return None
        due_dt = datetime.fromisoformat(due_date.replace("Z", "+00:00")) if isinstance(due_date, str) else due_date
        is_hard = due.get("hard", False)
        hours_until = (due_dt - now).total_seconds() / 3600
        if hours_until < 0:
            severity = "red" if is_hard else "yellow"
            return (severity, f"due date {'passed' if is_hard else 'soft past'}")
        elif hours_until < 24:
            return ("amber" if not is_hard else "red", f"due in {hours_until:.0f}h {'(hard deadline)' if is_hard else ''}")
    except Exception:
        pass
    return None
