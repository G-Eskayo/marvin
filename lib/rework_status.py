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


def status_for(ticket: dict, ctx: dict) -> dict:
    """One of: running, held, needs-person, paused, blocked, queued, not-queued. `ctx`: queue (identifiers, in dispatch
    order), key (this ticket's identifier, default its number), attempts (PRs already raised), max_attempts,
    claim_started, paused (breaker text or None), blockers, running (what is running now), project, machines, now."""
    names = _names(ticket)
    me = ctx.get("key", ticket["number"])
    attempts, cap = ctx.get("attempts", 0), ctx.get("max_attempts", 3)
    now = ctx.get("now") or datetime.now(timezone.utc)

    claim = next((n[len("claimed:"):] for n in names if n.startswith("claimed:")), None)
    if claim:
        return {"state": "running", "headline": "Being rebuilt right now",
                "detail": f"Running on {claim} for {_minutes(ctx.get('claim_started'), now)} (attempt {attempts + 1} of {cap}). It updates this same PR when it finishes."}
    if names & {"held", "pinned"}:
        return {"state": "held", "headline": "On hold",
                "detail": "A person asked the pipeline not to touch this ticket (held or pinned), so it will not be rebuilt until that label is removed."}
    if attempts >= cap:
        return {"state": "needs-person", "headline": "Needs you",
                "detail": f"It has been rebuilt {attempts} times and still does not pass, so the pipeline stopped. Look at the denial comments on its ticket."}
    if ctx.get("paused"):
        return {"state": "paused", "headline": f"Paused: {ctx.get('project', 'this project')} is not being dispatched",
                "detail": f"The circuit breaker stopped dispatch after {ctx['paused']}. Nothing starts until that is fixed or cleared."}
    if ctx.get("blockers"):
        return {"state": "blocked", "headline": "Waiting on another ticket",
                "detail": "It cannot start until " + ", ".join(f"#{b}" for b in ctx["blockers"]) + " is closed."}
    queue = ctx.get("queue", [])
    if me in queue:
        pos, total = queue.index(me) + 1, len(queue)
        running = ctx.get("running") or []
        now_running = f"Running now: {'; '.join(running)}." if running else "Nothing is running right now, so it starts at the next scan (after any merge, or on the hour)."
        return {"state": "queued", "headline": f"Queued: {ordinal(pos)} of {total} waiting", "position": pos, "of": total,
                "detail": f"Tickets run one at a time per machine, ordered by priority, deadline and age. {now_running}"}
    return {"state": "not-queued", "headline": "Not queued",
            "detail": "It is not in the dispatch queue and nothing explains why (no hold, pause or blocker). Check its labels and the scan log."}


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
    eligible = []
    for r in repos:
        for t in tp._unclaimed_ready_tickets(repo=r):
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
        p = subprocess.run(["gh", "issue", "list", "-R", r, "--state", "open", "--label", "needs-reengagement", "--limit", "100",
                            "--json", "number,title,labels,body"], capture_output=True, text=True, timeout=30)
        if p.returncode != 0:
            continue
        issues = json.loads(p.stdout)
        open_numbers = {i["number"] for i in issues}
        for t in issues:
            n = t["number"]
            stages = ts.read_stages(n, None if r == tp.REPO else r)
            starts = [e["timestamp"] for e in stages if e.get("stage") == "claimed" and e.get("status") == "started"]
            started = datetime.fromisoformat(starts[-1].replace("Z", "+00:00")) if starts else None
            out[f"{r}#{n}"] = status_for(t, dict(
                queue=queue, key=f"{r}#{n}", attempts=tp._attempts(r, n), max_attempts=tp.MAX_REENGAGE_ATTEMPTS,
                claim_started=started, paused=tripped.get(r), blockers=ticket_policy.open_blockers(t, open_numbers),
                running=running, project=r.split("/")[-1], now=now))
    return out


def main() -> None:
    if len(sys.argv) != 2 or sys.argv[1] != "report":
        sys.exit("usage: rework_status.py report")
    print(json.dumps(collect()))


if __name__ == "__main__":
    main()
