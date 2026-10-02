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


def record_failure(ticket: int, reason: str, now: datetime | None = None) -> None:
    _append({"t": (now or _now()).isoformat(), "kind": "failure", "ticket": ticket,
             "sig": signature(reason), "reason": (reason or "")[:300]})


def record_success(ticket: int, now: datetime | None = None) -> None:
    _append({"t": (now or _now()).isoformat(), "kind": "success", "ticket": ticket})


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


def tripped(now: datetime | None = None) -> list[dict]:
    """Signatures currently tripped: [{signature, tickets, first_seen, last_seen, example}]."""
    now = now or _now()
    horizon = now - timedelta(hours=WINDOW_HOURS)
    records = [r for r in _read() if r["_t"] >= horizon]
    resets = [r["_t"] for r in records if r["kind"] in ("success", "clear")]
    last_reset = max(resets) if resets else None
    failures = [r for r in records if r["kind"] == "failure" and (last_reset is None or r["_t"] > last_reset)]

    by_sig: dict[str, list[dict]] = {}
    for f in failures:
        by_sig.setdefault(f["sig"], []).append(f)
    result = []
    for sig, group in by_sig.items():
        tickets = sorted({f["ticket"] for f in group})
        if len(tickets) >= MIN_DISTINCT_TICKETS:
            result.append({"signature": sig, "tickets": tickets,
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
    if not trips:
        print("breaker: not tripped")
    for t in trips:
        print(f"TRIPPED {t['signature']} across tickets {t['tickets']} since {t['first_seen']}\n  e.g. {t['example'][:160]}")


if __name__ == "__main__":
    main()
