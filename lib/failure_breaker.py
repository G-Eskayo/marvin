#!/usr/bin/env python3
"""Cross-ticket circuit breaker for the ticket pipeline.

The per-ticket 3-strike guard (run_ticket.py) cannot see a SYSTEMIC failure: when
the environment is broken, every ticket in the queue fails the same way in
sequence, each burning its own strikes while the pipeline cheerfully "moves on"
to the next one. Found 2026-10-01 (vitest crashing on '#' in worktree paths
failed #32/#35/#37/#38 back to back); earlier, blind measures drove thousands of
wasted attempts. Nothing automated consumed the failures -- only displays did.

Every failure is reduced to a signature; if the SAME signature hits
MIN_DISTINCT_TICKETS different tickets within WINDOW_HOURS with no success since,
the breaker trips: ticket_pipeline stops dispatching and the Health tab goes red
with the evidence. One ticket failing repeatedly never trips it (that is the
per-ticket guard's job). Any real success clears it -- it proves the environment
works again. Deterministic and token-free.

State is a per-machine append-only log (~/.claude/logs/pipeline-failures.jsonl),
so each machine judges the dispatches it ran itself.

Stale code (marvin#458) is the other environment fault that pauses dispatch. On 2026-10-24/25 a ticket needing a
person was rebuilt ~122 times: the fix that skips such tickets had been on main for three days, but that Mac's
~/.agents code sync was stuck on an unresolved merge conflict, so the pipeline ran three-day-old code and nobody was
told. code_trip() is a live reading, not a log entry (nothing is stored): the checkout is behind origin/main by
changes that landed more than CODE_STALE_GRACE_HOURS ago, or code sync is stuck on a conflict or leftover stash. It
pauses every project (the scanner's own code is suspect) and clears by itself once the checkout catches up.

CLI:  failure_breaker.py status | clear     (status and --json include the stale-code trip)
"""
from __future__ import annotations
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

LOG_PATH = Path.home() / ".claude" / "logs" / "pipeline-failures.jsonl"
WINDOW_HOURS = 2
MIN_DISTINCT_TICKETS = 3


def _now() -> datetime:
    return datetime.now(timezone.utc)


def signature(reason: str) -> str:
    """Collapse the many spellings of one failure into a stable key."""
    r = reason or ""
    low = r.lower()
    m = re.search(r"(vitest|pytest) produced no test summary", low)
    if m:
        return f"measure:{m.group(1)}-no-summary"
    m = re.search(r"final verdict: (\w+)", low)
    if m:
        return f"verdict:{m.group(1)}"
    if re.search(r"the [\w-]+ model run failed", low):
        return "model-unavailable"   # usage limit or outage: every ticket fails alike, so three in a row pause dispatch
    if re.search(r"claude'\s*,", low) and "timed out" in low:   # the path is absolute in real runs (#597)
        return "claude-timeout"
    if "no such file or directory: 'claude'" in low:
        return "claude-not-found"
    if "'npm', 'run', 'build'" in low:
        return "npm-build-failed"
    if "'git', 'worktree', 'add'" in low or "'git', 'branch'" in low or "git worktree add failed" in low:
        return "git-worktree-add-failed"
    cleaned = re.sub(r"/[\w./%#@+-]*", "<path>", low)       # paths
    cleaned = re.sub(r"\d+", "", cleaned)                    # numbers
    return "other:" + re.sub(r"\s+", " ", cleaned).strip()[:60]


def _append(record: dict) -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("a") as fh:
        fh.write(json.dumps(record) + "\n")


MARVIN = "G-Eskayo/marvin"


def record_failure(ticket: int, reason: str, now: datetime | None = None, project: str = MARVIN) -> None:
    _append({"t": (now or _now()).isoformat(), "kind": "failure", "ticket": ticket, "project": project,
             "sig": signature(reason), "reason": (reason or "")[:300]})


def record_success(ticket: int, now: datetime | None = None, project: str = MARVIN) -> None:
    _append({"t": (now or _now()).isoformat(), "kind": "success", "ticket": ticket, "project": project})


def clear(now: datetime | None = None) -> None:
    _append({"t": (now or _now()).isoformat(), "kind": "clear"})


def _read() -> list[dict]:
    if not LOG_PATH.exists():
        return []
    out = []
    for line in LOG_PATH.read_text().splitlines():
        try:
            rec = json.loads(line)
            rec["_t"] = datetime.fromisoformat(rec["t"])
            out.append(rec)
        except (ValueError, KeyError, TypeError):
            continue  # a corrupt line must never take the breaker down
    return out


def tripped(now: datetime | None = None, project: str | None = None) -> list[dict]:
    """Signatures currently tripped, per project: [{project, signature, tickets, first_seen, last_seen,
    example}]. One project's broken environment (say, a missing Xcode) must not pause the others, and a
    success in one project only proves THAT project's environment works. Log lines from before projects
    existed belong to marvin."""
    now = now or _now()
    horizon = now - timedelta(hours=WINDOW_HOURS)
    records = [r for r in _read() if r["_t"] >= horizon]
    for r in records:
        r.setdefault("project", MARVIN)
    result = []
    for proj in sorted({r["project"] for r in records}):
        if project is not None and proj != project:
            continue
        mine = [r for r in records if r["project"] == proj]
        # a success only proves its own project works; a manual `clear` is a person saying "all clear"
        resets = [r["_t"] for r in mine if r["kind"] == "success"] + [r["_t"] for r in records if r["kind"] == "clear"]
        last_reset = max(resets) if resets else None
        failures = [r for r in mine if r["kind"] == "failure" and (last_reset is None or r["_t"] > last_reset)]
        by_sig: dict[str, list[dict]] = {}
        for f in failures:
            by_sig.setdefault(f["sig"], []).append(f)
        for sig, group in by_sig.items():
            tickets = sorted({f["ticket"] for f in group})
            if len(tickets) >= MIN_DISTINCT_TICKETS:
                result.append({"project": proj, "signature": sig, "tickets": tickets,
                               "first_seen": min(f["_t"] for f in group).isoformat(),
                               "last_seen": max(f["_t"] for f in group).isoformat(),
                               "example": group[-1].get("reason", "")})
    return result


# ── stale code (marvin#458) ──────────────────────────────────────────────

CODE_STALE_SIGNATURE = "code-stale"
ALL_PROJECTS = "*"            # a stale-code trip pauses every project: it is the scanner's own code that is old
CODE_STALE_GRACE_HOURS = 2    # code sync runs every 30 min: four missed cycles is stuck, not drift
CODE_REPO_REL = ".agents"     # the checkout that runs the pipeline, relative to $HOME (code_sync's ~/.agents)


def code_freshness(repo_rel: str = CODE_REPO_REL, now: datetime | None = None,
                   grace_hours: float = CODE_STALE_GRACE_HOURS) -> dict:
    """How current the pipeline's own checkout is. {state, detail, behind, oldest_hours}, state one of
    current | stale | stuck | unknown. Reads origin/main as the last fetch left it (code sync and the health sweep
    already fetch): no network. Never raises. Reuses health_checks' repo-state script (the same measurement the
    repo:sync card shows) and code_sync's own stuck-tree test (the same one that makes sync refuse).

    unknown fails OPEN: if origin/main can't be read we can't tell stale from fine, and halting every project on
    any git hiccup would make this guard the single point that stops all work. The caller logs a warning. A
    conflict or stash is local, certain evidence, so `stuck` is judged first and does not need origin/main."""
    now = now or _now()
    out = {"state": "unknown", "detail": "", "behind": None, "oldest_hours": None}
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import code_sync
        import health_checks
        repo = Path.home() / repo_rel
        if not (repo / ".git").exists():
            out["detail"] = f"~/{repo_rel} is not a git checkout"
            return out
        stuck = code_sync._stuck_from_previous_run(repo)
        if stuck:
            return {**out, "state": "stuck", "detail": stuck}
        state = health_checks.parse_repo_state(health_checks._run_repo_state(None, repo_rel, fetch=False))
    except Exception as exc:  # noqa: BLE001 -- the guard must never take the scan down
        out["detail"] = f"could not read ~/{repo_rel}: {type(exc).__name__}: {exc}"
        return out
    if not state["head"]:
        out["detail"] = f"could not read HEAD of ~/{repo_rel}"
        return out
    if not state["origin_ok"]:
        out["detail"] = f"no origin/main ref in ~/{repo_rel} (never fetched?)"
        return out
    behind = state["behind"]
    out["behind"] = behind
    if not behind:
        return {**out, "state": "current", "detail": "up to date with origin/main (as of the last fetch)"}
    ts = state["behind_oldest_ts"]
    if ts is None:
        out["detail"] = f"{behind} commit(s) behind origin/main, but their age could not be read"
        return out
    hours = (now - datetime.fromtimestamp(ts, tz=timezone.utc)).total_seconds() / 3600
    out["oldest_hours"] = hours
    if hours < grace_hours:
        return {**out, "state": "current", "detail": f"{behind} behind, oldest {hours:.1f}h: within the {grace_hours:g}h grace"}
    return {**out, "state": "stale", "detail": f"{behind} commit(s) behind origin/main, oldest {hours:.0f}h"}


def _machine() -> str:
    try:
        import machine_profile
        return machine_profile.registry_id()
    except Exception:  # noqa: BLE001
        return "this Mac"


def code_trip(repo_rel: str = CODE_REPO_REL, now: datetime | None = None,
              grace_hours: float = CODE_STALE_GRACE_HOURS, freshness: dict | None = None) -> dict | None:
    """A breaker-shaped trip while the pipeline's code is stale or its sync is stuck, else None."""
    now = now or _now()
    f = freshness or code_freshness(repo_rel, now, grace_hours)
    if f["state"] == "stale":
        n = f["behind"]
        fix = (f"this Mac's MARVIN code is {n} commit{'s' if n != 1 else ''} behind main (oldest {f['oldest_hours']:.0f}h): "
               "code sync is stuck; resolve it (see repo:sync)")
    elif f["state"] == "stuck":
        fix = f"this Mac's MARVIN code sync is stuck ({f['detail']}); resolve it by hand (see repo:sync)"
    else:
        return None
    return {"project": ALL_PROJECTS, "signature": CODE_STALE_SIGNATURE, "machine": _machine(), "tickets": [],
            "first_seen": now.isoformat(), "last_seen": now.isoformat(), "example": fix, "fix": fix}


def main() -> None:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    if cmd == "clear":
        clear()
        print("breaker cleared")
        return
    trips = tripped()
    stale = code_trip()
    if stale:
        trips.append(stale)
    if "--json" in sys.argv:
        print(json.dumps(trips, indent=2))
        return
    if not trips:
        print("breaker: not tripped")
    for t in trips:
        if t.get("fix"):
            print(f"TRIPPED {t['signature']}: {t['fix']}")
            continue
        print(f"TRIPPED {t['signature']} across tickets {t['tickets']} since {t['first_seen']}\n  e.g. {t['example'][:160]}")


if __name__ == "__main__":
    main()
