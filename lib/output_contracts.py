#!/usr/bin/env python3
"""Output contracts (marvin#305, ADR 0059 decision 2): every producer declares where its output goes, who or what
acts on it, and how soon. Output nobody consumes in time becomes a Health finding instead of a silent pile, and a
producer whose output hasn't been consumed for 30 days is a removal candidate (the Watts check: thought serving
itself).

Each contract can read its own state: the dates of items still waiting, and the dates items were consumed
(resolved, promoted, declined, reviewed, fixed). A contract that can't measure consumption yet says so and names
the consumer that will.

    output_contracts.py health    # the findings, as JSON
    output_contracts.py promote   # ticket promotion: the top pending suggestions, capped per day
"""
from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

sys.path.insert(0, str(Path(__file__).resolve().parent))

CLAUDE = Path.home() / ".claude"
SUGGESTIONS = CLAUDE / "suggestions.md"
QUEUE = CLAUDE / "improvement-queue.md"
QUARANTINE = CLAUDE / "quarantine.md"
CALIBRATION = CLAUDE / "safety-monitor" / "calibration.jsonl"
AUTO_FIX_LOG = CLAUDE / "auto-fix-log.md"
CUT_AFTER_DAYS = 30
PROMOTE_PER_DAY = 2

_DATE = r"(\d{4}-\d{2}-\d{2})"


def _day(s: str) -> datetime:
    return datetime.fromisoformat(s[:10]).replace(tzinfo=timezone.utc)


@dataclass(frozen=True)
class Contract:
    producer: str
    output: str
    consumer: str
    within_days: int
    state: Callable[[], tuple[list[datetime], list[datetime]]] | None  # (pending dates, consumed dates)


# ── state readers ────────────────────────────────────────────────────────────────────────────────────────────

def _blocks(text: str) -> list[str]:
    return re.split(r"^(?=## )", text, flags=re.M)[1:]


def suggestions_state(text: str) -> tuple[list[datetime], list[datetime]]:
    pending, consumed = [], []
    for block in _blocks(text):
        status = re.search(r"^\*\*Status\*\*:\s*(\w+)(?:\s+" + _DATE + ")?", block, re.M)
        added = re.search(r"^\*\*Added\*\*:\s*" + _DATE, block, re.M)
        if not status:
            continue
        if status.group(1) == "pending" and added:
            pending.append(_day(added.group(1)))
        elif status.group(2):
            consumed.append(_day(status.group(2)))
    return pending, consumed


def _read(path: Path) -> str:
    return path.read_text(errors="ignore") if path.exists() else ""


def _suggestions() -> tuple[list[datetime], list[datetime]]:
    return suggestions_state(_read(SUGGESTIONS))


def _queue() -> tuple[list[datetime], list[datetime]]:
    pending = [_day(m) for m in re.findall(r"^## " + _DATE, _read(QUEUE), re.M)]
    consumed = [_day(m.group(1)) for m in re.finditer(r"^## " + _DATE + r"T[^\n]*\n(\d+) candidate\(s\) found, ([1-9]\d*) fixed",
                                                        _read(AUTO_FIX_LOG), re.M)]
    return pending, consumed


def _quarantine() -> tuple[list[datetime], list[datetime]]:
    pending = [_day(m) for m in re.findall(r"^## " + _DATE + r" — \S+ \[SAFETY", _read(QUARANTINE), re.M)]
    consumed = []
    for line in _read(CALIBRATION).splitlines():
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        when = rec.get("at") or rec.get("timestamp") or rec.get("date")
        if when:
            consumed.append(_day(when))
    return pending, consumed


CONTRACTS: list[Contract] = [
    Contract("architecture-review", "~/.claude/suggestions.md",
             f"ticket promotion (daily, top {PROMOTE_PER_DAY}, as needs-triage tickets) or Gil", 14, _suggestions),
    Contract("improvement-sweep", "~/.claude/improvement-queue.md", "auto-fix (naming/verbosity) or Gil", 14, _queue),
    Contract("safety-monitor", "~/.claude/quarantine.md", "Gil's approve/deny review", 7, _quarantine),
    Contract("daily-digest", "~/.claude/digest/<day>.md", "the morning brief (#306)", 1, None),
    Contract("research-digest", "~/.claude/research-digest/<day>.md", "the morning brief (#306)", 1, None),
]


# ── health ───────────────────────────────────────────────────────────────────────────────────────────────────

def evaluate(contract: Contract, now: datetime) -> dict:
    cid, label = f"contract:{contract.producer}", f"Output: {contract.producer}"
    if contract.state is None:
        return {"id": cid, "label": label, "severity": "yellow",
                "detail": f"consumption not measured yet; its consumer will be {contract.consumer}"}
    pending, consumed = contract.state()
    last = max(consumed) if consumed else None
    overdue = [p for p in pending if (now - p).days > contract.within_days]
    if pending and (last is None or (now - last).days > CUT_AFTER_DAYS):
        since = "never consumed" if last is None else f"last consumed {(now - last).days} days ago"
        return {"id": cid, "label": label, "severity": "red",
                "detail": f"{len(pending)} item(s) waiting, {since}: removal candidate (30-day cut rule) unless "
                          f"{contract.consumer} starts acting on it"}
    if overdue:
        oldest = (now - min(overdue)).days
        return {"id": cid, "label": label, "severity": "yellow",
                "detail": f"{len(overdue)} item(s) past the {contract.within_days}-day deadline (oldest {oldest} days) "
                          f"in {contract.output}; consumer: {contract.consumer}"}
    return {"id": cid, "label": label, "severity": "green",
            "detail": f"{len(pending)} waiting, all within {contract.within_days} days; consumer: {contract.consumer}"}


def health_findings(now: datetime | None = None) -> list[dict]:
    now = now or datetime.now(timezone.utc)
    out = []
    for c in CONTRACTS:
        try:
            out.append(evaluate(c, now))
        except Exception as exc:  # noqa: BLE001
            out.append({"id": f"contract:{c.producer}", "label": f"Output: {c.producer}", "severity": "yellow",
                        "detail": f"couldn't read its state: {exc}"})
    return out


# ── ticket promotion: the consumer the analysts never had ──────────────────────────────────────────────────

def promote_pending(text: str, now: datetime, limit: int = PROMOTE_PER_DAY,
                    promote: Callable[[str], dict] | None = None) -> str:
    """Send the top `limit` pending suggestions (the file is priority-sorted) through ticket promotion, and
    record each decision in the suggestion's Status line, which is what makes it consumed."""
    if promote is None:
        import ticket_promotion
        promote = ticket_promotion.promote_finding
    today = now.date().isoformat()
    head, *blocks = re.split(r"^(?=## )", text, flags=re.M)
    done = 0
    for i, block in enumerate(blocks):
        if done >= limit or not re.search(r"^\*\*Status\*\*:\s*pending\b", block, re.M):
            continue
        decision = promote(block.strip())
        done += 1
        ref = decision.get("ticket_ref")
        if decision.get("promoted") and ref == "NOTHING_LEFT":
            status = f"resolved {today} (ticket promotion: its own updates say nothing remains)"
        elif decision.get("promoted") and ref:
            status = f"promoted {today} {ref}"
        elif decision.get("promoted"):
            continue  # no ticket came out: stays pending, tried again another day
        else:
            reason = re.sub(r"\s+", " ", decision.get("reasoning") or "").strip()[:160]
            status = f"declined {today} ({reason})"
        blocks[i] = re.sub(r"^\*\*Status\*\*:\s*pending\b.*$", f"**Status**: {status}", block, count=1, flags=re.M)
    return head + "".join(blocks)


def run_promotion(now: datetime | None = None) -> None:
    now = now or datetime.now(timezone.utc)
    if not SUGGESTIONS.exists():
        return
    updated = promote_pending(SUGGESTIONS.read_text(), now)
    tmp = SUGGESTIONS.with_suffix(".md.tmp")
    tmp.write_text(updated)
    tmp.replace(SUGGESTIONS)


if __name__ == "__main__":
    if sys.argv[1:] == ["health"]:
        print(json.dumps(health_findings(), indent=2))
    elif sys.argv[1:] == ["promote"]:
        run_promotion()
    else:
        sys.exit("usage: output_contracts.py health | promote")
