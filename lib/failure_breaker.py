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

CLI:  failure_breaker.py status | clear
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
    if "'claude'" in low and "timed out" in low:
        return "claude-timeout"
    if "no such file or directory: 'claude'" in low:
        return "claude-not-found"
    if "'npm', 'run', 'build'" in low:
        return "npm-build-failed"
    if "'git', 'worktree', 'add'" in low or "'git', 'branch'" in low:
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


def ticket_streak(ticket: int, project: str = MARVIN, now: datetime | None = None) -> dict:
    """Trailing failures for ONE ticket in ONE project since its last recorded success.
    Returns {"count": int, "signatures": [sig, ...]} (oldest-to-newest).
    Empty/no entries -> count 0. A success resets the streak."""
    now = now or _now()
    records = _read()
    for r in records:
        r.setdefault("project", MARVIN)
    my_records = [r for r in records if r["ticket"] == ticket and r["project"] == project]
    my_records.sort(key=lambda r: r["_t"])

    # Find the last success; everything after it is the streak
    last_success_idx = -1
    for i, r in enumerate(my_records):
        if r["kind"] == "success":
            last_success_idx = i

    streak_records = my_records[last_success_idx + 1:]
    failures = [r for r in streak_records if r["kind"] == "failure"]

    return {
        "count": len(failures),
        "signatures": [f.get("sig", "") for f in failures]
    }


def should_hold(ticket: int, project: str = MARVIN, threshold: int = 3, now: datetime | None = None) -> dict | None:
    """Decide whether to hold a ticket based on its failure streak.
    Returns None if not yet due to hold.
    Else returns {"reason": "n-failures"|"repeat-signature", "count": int, "signatures": [...]}.

    A ticket is held if:
    1. It has N consecutive failures (reason="n-failures"), OR
    2. Its last two failures have the same signature (reason="repeat-signature").
    """
    if threshold is None:
        threshold = 3
    if threshold <= 0:
        return None  # Defensive: don't hold if threshold is invalid

    streak = ticket_streak(ticket, project, now)
    count = streak["count"]
    sigs = streak["signatures"]

    # Case 2: last two failures have identical signature (even if count < threshold)
    if len(sigs) >= 2 and sigs[-1] == sigs[-2]:
        return {"reason": "repeat-signature", "count": count, "signatures": sigs}

    # Case 1: N consecutive failures
    if count >= threshold:
        return {"reason": "n-failures", "count": count, "signatures": sigs}

    return None


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


def main() -> None:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    if cmd == "clear":
        clear()
        print("breaker cleared")
        return
    trips = tripped()
    if "--json" in sys.argv:
        print(json.dumps(trips, indent=2))
        return
    if not trips:
        print("breaker: not tripped")
    for t in trips:
        print(f"TRIPPED {t['signature']} across tickets {t['tickets']} since {t['first_seen']}\n  e.g. {t['example'][:160]}")


if __name__ == "__main__":
    main()
