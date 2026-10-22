"""Where a sent-back ticket stands, so its PR card never just says "a new version is coming".

A PR whose ticket was sent back for rework (label `needs-reengagement`) waits for the pipeline to rebuild it. From the
outside that looks identical whether it is running right now, third in a queue, paused by the circuit breaker, held by
a person, or out of attempts (2026-10-07: two PRs sat "sent back" for hours with no way to tell which). `status_for` is
pure over what the pipeline already knows; `collect` gathers it; `python rework_status.py report` prints JSON that the
dashboard reads: {"<repo>#<n>": {state, headline, detail, ...}}.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))


def ordinal(n: int) -> str:
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def _names(ticket: dict) -> set[str]:
    return {l["name"] if isinstance(l, dict) else l for l in ticket.get("labels", [])}


def _minutes(since: datetime | None, now: datetime) -> str:
    if since is None:
        return "a while"
    m = max(0, int((now - since).total_seconds() // 60))
    return f"{m} min" if m < 120 else f"{m // 60} h"


def _hold_detail(events: list, comments: list, label_names: set) -> dict | None:
    """Parse hold details from GitHub events and comments. Returns {date, added_by, comment}."""
    if not label_names:
        return None
    import ticket_policy as pol
    hold_labels = label_names & pol.HOLD_LABELS
    if not hold_labels:
        return None

    # Find the most recent labeled event for any hold label
    labeled_events = [e for e in events if e.get("event") == "labeled"]
    labeled_events = [e for e in labeled_events if e.get("label", {}).get("name") in hold_labels]
    if not labeled_events:
        return None

    # Filter for events with valid createdAt (guard against malformed gh output)
    def sort_key(e):
        date_str = e.get("createdAt")
        if date_str and isinstance(date_str, str):
            try:
                return datetime.fromisoformat(date_str.replace("Z", "+00:00"))
            except (ValueError, TypeError):
                return datetime(1900, 1, 1, tzinfo=timezone.utc)
        return datetime(1900, 1, 1, tzinfo=timezone.utc)
    most_recent = max(labeled_events, key=sort_key) if labeled_events else None
    if not most_recent:
        return None
    event_date = most_recent.get("createdAt")
    actor = most_recent.get("actor")
    added_by = (actor.get("login", "unknown") if isinstance(actor, dict) else None) or "unknown"
    label = most_recent.get("label", {}).get("name", "held")

    # Find the nearest comment within a short time window (30 minutes)
    comment_text = None
    if event_date and comments:
        try:
            event_dt = datetime.fromisoformat(event_date.replace("Z", "+00:00"))
            for c in comments:
                c_date = c.get("createdAt")
                if not c_date:
                    continue
                try:
                    c_dt = datetime.fromisoformat(c_date.replace("Z", "+00:00"))
                    if abs((c_dt - event_dt).total_seconds()) <= 30 * 60:
                        comment_text = c.get("body", "").split("\n")[0][:100]
                        break
                except (ValueError, TypeError):
                    continue
        except (ValueError, TypeError):
            pass

    return {"date": event_date, "added_by": added_by, "label": label, "comment": comment_text}


def _read_diagnosis(ticket_number: int, repo: str) -> dict | None:
    """Read the latest diagnosis for a ticket from denial_diagnosis.jsonl."""
    try:
        import denial_diagnosis as dd
        # repo can be either "marvin" or "G-Eskayo/marvin"; match both
        full_repo = repo if "/" in repo else f"G-Eskayo/{repo}"
        recs = [r for r in dd._read() if r.get("ticket") == ticket_number and r.get("project") == full_repo]
        if recs:
            latest = max(recs, key=lambda r: r.get("_t", datetime.min(timezone.utc)))
            return {"kind": latest.get("diagnosis_kind"), "route": latest.get("route")}
    except (ImportError, Exception):
        pass
    return None


def status_for(ticket: dict, ctx: dict) -> dict:
    """One of: running, held, needs-person, paused, blocked, queued, not-queued. `ctx`: queue (identifiers, in dispatch
    order), key (this ticket's identifier, default its number), attempts (PRs already raised), max_attempts,
    claim_started, paused (breaker text or None), blockers, running (what is running now), project, machines, now, hold."""
    import ticket_policy as pol  # lazy import, matching the file's existing lazy-import style
    names = _names(ticket)
    me = ctx.get("key", ticket["number"])
    attempts, cap = ctx.get("attempts", 0), ctx.get("max_attempts", 3)
    now = ctx.get("now") or datetime.now(timezone.utc)
    project = ctx.get("project", "G-Eskayo/marvin")

    result = {}

    claim = next((n[len("claimed:"):] for n in names if n.startswith("claimed:")), None)
    if claim:
        result = {"state": "running", "headline": "Being rebuilt right now",
                "detail": f"Running on {claim} for {_minutes(ctx.get('claim_started'), now)} (attempt {attempts + 1} of {cap}). It updates this same PR when it finishes."}
    elif names & pol.HOLD_LABELS:
        held_label = next((l for l in names if l in pol.HOLD_LABELS), "held")
        detail = f"A person asked the pipeline not to touch this ticket ({held_label}), so it will not be rebuilt until that label is removed."
        hold_info = ctx.get("hold")
        if hold_info:
            detail += f" (added by {hold_info.get('added_by', '?')} on {hold_info.get('date', '?')}"
            if hold_info.get("comment"):
                detail += f": {hold_info.get('comment')}"
            detail += ")"
        result = {"state": "held", "headline": "On hold", "detail": detail}
    elif attempts >= cap:
        result = {"state": "needs-person", "headline": "Needs you",
                "detail": f"It has been rebuilt {attempts} times and still does not pass, so the pipeline stopped. Look at the denial comments on its ticket."}
    elif "ready-for-agent" not in names:
        result = {"state": "needs-person", "headline": "Parked: the pipeline stopped trying",
                "detail": "It failed its automated attempts, so the pipeline took off ready-for-agent (and the claim) to stop retrying. "
                          "Read the latest comment on the ticket for why, fix that, then add ready-for-agent back and it is rebuilt."}
    elif ctx.get("paused"):
        result = {"state": "paused", "headline": f"Paused: {ctx.get('project', 'this project')} is not being dispatched",
                "detail": f"The circuit breaker stopped dispatch after {ctx['paused']}. Nothing starts until that is fixed or cleared."}
    elif ctx.get("blockers"):
        result = {"state": "blocked", "headline": "Waiting on another ticket",
                "detail": "It cannot start until " + ", ".join(f"#{b}" for b in ctx["blockers"]) + " is closed."}
    else:
        queue = ctx.get("queue", [])
        if me in queue:
            pos, total = queue.index(me) + 1, len(queue)
            running = ctx.get("running") or []
            now_running = f"Running now: {'; '.join(running)}." if running else "Nothing is running right now, so it starts at the next scan (after any merge, or on the hour)."
            result = {"state": "queued", "headline": f"Queued: {ordinal(pos)} of {total} waiting", "position": pos, "of": total,
                    "detail": f"Tickets run one at a time per machine, ordered by priority, deadline and age. {now_running}"}
        else:
            result = {"state": "not-queued", "headline": "Not queued",
                    "detail": "It is not in the dispatch queue and nothing explains why (no hold, pause or blocker). Check its labels and the scan log."}

    # Add diagnosis if available
    diagnosis = _read_diagnosis(ticket["number"], project)
    if diagnosis:
        result["diagnosis"] = diagnosis

    return result


def collect(repos: list[str] | None = None) -> dict:
    """{"<repo>#<n>": status} for every open ticket currently sent back, across the dispatchable projects."""
    import failure_breaker
    import project_profile as pp
    import ticket_pipeline as tp
    import ticket_policy
    import ticket_stages as ts

    now = datetime.now(timezone.utc)
    repos = repos or [tp.REPO, *pp.dispatchable_repos()]
    # The same order the scan uses: every eligible ticket across projects, by priority, then urgency, then age.
    # One read of each project's open tickets answers both the queue and which tickets were sent back (#324).
    open_by_repo = {r: tp._open_issues(r) for r in repos}
    eligible = []
    for r in repos:
        if open_by_repo[r] is None:
            continue
        for t in tp._unclaimed_ready_tickets(repo=r, issues=open_by_repo[r]):
            eligible.append((r, t))
    eligible.sort(key=lambda rt: tp._order_key(rt[1]))
    queue = [f"{r}#{t['number']}" for r, t in eligible]

    running = []
    ps = subprocess.run(["ps", "-axo", "command"], capture_output=True, text=True).stdout
    for m in re.finditer(r"run_ticket\.py\s+(?:(\S+)#)?(\d+)", ps):
        running.append(f"{(m.group(1) or tp.REPO).split('/')[-1]} #{m.group(2)}")

    tripped = {t.get("project", tp.REPO): f"{t['signature']} failed across tickets {', '.join(map(str, t['tickets']))}" for t in failure_breaker.tripped()}
    out = {}
    for r in repos:
        if open_by_repo[r] is None:
            continue
        open_numbers = {i["number"] for i in open_by_repo[r]}
        for t in (i for i in open_by_repo[r] if "needs-reengagement" in _names(i)):
            n = t["number"]
            stages = ts.read_stages(n, None if r == tp.REPO else r)
            starts = [e["timestamp"] for e in stages if e.get("stage") == "claimed" and e.get("status") == "started"]
            started = datetime.fromisoformat(starts[-1].replace("Z", "+00:00")) if starts else None

            hold_info = None
            names = _names(t)
            if names & ticket_policy.HOLD_LABELS:
                # Fetch events and comments for held tickets to provide more detail
                try:
                    proc = subprocess.run(
                        ["gh", "api", f"repos/{r}/issues/{n}/events", "-H", "Accept: application/vnd.github.v3+json"],
                        capture_output=True, text=True, timeout=10
                    )
                    events = json.loads(proc.stdout) if proc.returncode == 0 else []
                except (subprocess.TimeoutExpired, json.JSONDecodeError, ValueError):
                    events = []

                try:
                    proc = subprocess.run(
                        ["gh", "issue", "view", str(n), "--repo", r, "--json", "comments"],
                        capture_output=True, text=True, timeout=10
                    )
                    comments = json.loads(proc.stdout).get("comments", []) if proc.returncode == 0 else []
                except (subprocess.TimeoutExpired, json.JSONDecodeError, ValueError, KeyError):
                    comments = []

                hold_info = _hold_detail(events, comments, names)

            out[f"{r}#{n}"] = status_for(t, dict(
                queue=queue, key=f"{r}#{n}", attempts=tp._attempts(r, n), max_attempts=tp.MAX_REENGAGE_ATTEMPTS,
                claim_started=started, paused=tripped.get(r), blockers=ticket_policy.open_blockers(t, open_numbers),
                running=running, project=r.split("/")[-1], now=now, hold=hold_info))
    return out


def main() -> None:
    if len(sys.argv) != 2 or sys.argv[1] != "report":
        sys.exit("usage: rework_status.py report")
    print(json.dumps(collect()))


if __name__ == "__main__":
    main()
