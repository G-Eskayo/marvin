"""The rules behind the ticket agents, as pure functions (no GitHub, no clock): what blocks a ticket,
when a claim is stale, how urgent a ticket is, whether a new ticket is ready for an agent.
`ticket_agents.py` applies them; the dashboard's board derives the same blocked/stale states in JS
(dashboard/electron/main/board.js) -- keep the two in step.

Tickets are dicts shaped like `gh issue list --json number,title,labels,body,createdAt,updatedAt`.
"""
from __future__ import annotations
import re
from datetime import datetime, timezone

STALE_CLAIM_HOURS = 48
PRIORITY_LABELS = ("priority:p0", "priority:p1", "priority:p2", "priority:p3")
STATE_LABELS = {"ready-for-agent", "ready-for-human", "needs-info", "needs-reengagement", "wontfix"}
SKIP_LABELS = {"pinned"}  # a person has taken the wheel: no agent touches it


def label_names(issue: dict) -> list[str]:
    return [l["name"] for l in issue.get("labels", [])]


def _parse(ts):
    try:
        d = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


# ── blockers ────────────────────────────────────────────────────────────────

def parse_blocked_by(body: str) -> set[int]:
    body = body or ""
    out = {int(n) for n in re.findall(r"\bBlocked by\s+(?:[\w.-]+/[\w.-]+)?#(\d+)", body, re.I)}
    sec = re.search(r"##\s*Blocked by\s*\n(.*?)(?=\n##\s|\Z)", body, re.I | re.S)
    if sec:
        out |= {int(n) for n in re.findall(r"#(\d+)", sec.group(1))}
    return out


def open_blockers(issue: dict, open_numbers: set[int]) -> list[int]:
    return sorted(n for n in parse_blocked_by(issue.get("body", "")) if n in open_numbers)


# ── claims ──────────────────────────────────────────────────────────────────

def claim_of(issue: dict) -> str | None:
    return next((l[len("claimed:"):] for l in label_names(issue) if l.startswith("claimed:")), None)


def stale_claim(issue: dict, now: datetime, hours: int = STALE_CLAIM_HOURS) -> dict | None:
    machine = claim_of(issue)
    touched = _parse(issue.get("updatedAt"))
    if not machine or touched is None:
        return None
    idle = (now - touched).total_seconds() / 3600
    return {"machine": machine, "idle_hours": round(idle)} if idle > hours else None


# ── priority ────────────────────────────────────────────────────────────────

BUG_WEIGHT = 10  # a bare bug scores p1 (priority_for: >= 10)
# Scaffolding other work builds on, even before anything is formally blocked by it (design session 2026-10-08, #276).
# Strong next to "unblocks N" (3 per ticket), below a hard deadline within a month (ADR 0047).
FOUNDATION_WEIGHT = 6

def priority_rank(issue: dict) -> int | None:
    for l in label_names(issue):
        m = re.fullmatch(r"priority:p([0-3])", l)
        if m:
            return int(m.group(1))
    return None


_BUCKET = re.compile(r"^\s*\[([A-Za-z0-9]+)\]")


def bucket_of(issue: dict) -> str | None:
    """A ticket's bucket: the '[X]' prefix its title carries (clarity-captions uses A-G, L, V, W)."""
    m = _BUCKET.match(issue.get("title") or "")
    return m.group(1).upper() if m else None


def score_ticket(issue: dict, blocks_count: int, due: dict | None, now: datetime) -> tuple[float, list[str]]:
    """Urgency, with the reasons. Leverage first (what it unblocks), then deadlines, then type and age."""
    score, why = 0.0, []
    if blocks_count:
        pts = min(blocks_count * 3, 12)
        score += pts
        why.append(f"unblocks {blocks_count} ticket{'s' if blocks_count != 1 else ''} (+{pts:g})")
    # A project deadline covers its launch work, not its whole backlog: tickets in a bucket the project marked as not
    # part of it (clarity-captions' V: iPad, Mac, Watch, Android) get no deadline weight (Gil, 2026-10-07).
    excluded = {str(b).upper() for b in (due or {}).get("excludes", [])}
    if due and due.get("date") and bucket_of(issue) not in excluded:
        d = _parse(due["date"] + "T00:00:00+00:00")
        if d is not None:
            days = (d - now).total_seconds() / 86400
            hard = bool(due.get("hard"))
            # A hard deadline is a strong weight from weeks out, not only in the final fortnight (Gil, 2026-10-06; ADR 0047):
            # enough to put it ahead of ordinary work, not a strict tier, so a high-leverage bug can still slip in ahead.
            pts = ((30 if days <= 3 else 24 if days <= 14 else 16 if days <= 30 else 8 if days <= 60 else 4) if hard
                   else (6 if days <= 7 else 3 if days <= 30 else 0))
            if pts:
                score += pts
                why.append(f"{'hard' if hard else 'soft'} deadline in {max(0, round(days))} days (+{pts})")
    names = label_names(issue)
    if "foundation" in names:
        score += FOUNDATION_WEIGHT
        why.append(f"foundation other work builds on (+{FOUNDATION_WEIGHT})")
    if "bug" in names:
        # Bugs before features (Gil, 2026-10-07; ADR 0054): a bug on its own lands in p1, ordinary features in p2/p3.
        score += BUG_WEIGHT
        why.append(f"bug (+{BUG_WEIGHT})")
    if "breaking-change" in names:
        score += 2
        why.append("breaking change (+2)")
    if "needs-reengagement" in names:
        score += 3
        why.append("already invested in, sent back (+3)")
    created = _parse(issue.get("createdAt"))
    if created is not None:
        age = min(max((now - created).days, 0), 50) * 0.1
        if age >= 0.5:
            score += age
            why.append(f"waiting {int(age * 10)} days (+{age:.1f})")
    return round(score, 1), why


def priority_for(score: float) -> str:
    return PRIORITY_LABELS[0] if score >= 20 else PRIORITY_LABELS[1] if score >= 10 else PRIORITY_LABELS[2] if score >= 4 else PRIORITY_LABELS[3]


# ── triage ──────────────────────────────────────────────────────────────────

_HUMAN_TITLE = re.compile(r"\b(design session|decide|choose|pick a|usability test|interview|paid|account|purchase|review with)\b", re.I)
_BUG = re.compile(r"\b(bug|broken|crash(es|ed)?|error|fails?|failing|regression|wrong)\b", re.I)


# A ticket handed to the owner must say exactly what to do, so nobody has to ask in a chat what it wants. A "## Your task"
# section with these four bold fields (docs/agents/human-task-template.md).
HUMAN_TASK_FIELDS = ("What I need from you", "Where", "How", "What to send back")


def human_task_gaps(body: str) -> list[str]:
    """What is missing from a ticket's 'Your task' section: [] when it names all four fields with content."""
    m = re.search(r"^##\s*Your task\s*$([\s\S]*?)(?=^##\s|\Z)", body or "", re.I | re.M)
    if not m:
        return ["a 'Your task' section"]
    section = m.group(1)
    labels = "|".join(re.escape(f) for f in HUMAN_TASK_FIELDS)
    gaps = []
    for field in HUMAN_TASK_FIELDS:
        fm = re.search(rf"\*\*{re.escape(field)}:?\*\*:?([\s\S]*?)(?=\*\*(?:{labels}):?\*\*|\Z)", section, re.I)
        if not fm or not fm.group(1).strip():
            gaps.append(field)
    return gaps


def triage_verdict(issue: dict, recheck: bool = False) -> dict | None:
    """What to do with an untriaged ticket, deterministically (no model, no tokens): None if it is
    already triaged or pinned. `state` is one of ready-for-agent / ready-for-human / needs-info.
    `recheck`: look again at a needs-info ticket (the triage agent re-checks the ones it parked)."""
    names = set(label_names(issue))
    states = (STATE_LABELS - {"needs-info"}) if recheck else STATE_LABELS
    if names & states or names & SKIP_LABELS or any(l.startswith("claimed:") for l in names):
        return None
    body = issue.get("body") or ""
    title = issue.get("title") or ""
    # A parent PRD is not agent-sized work and has no acceptance criteria by design: never nag it.
    if re.match(r"\s*PRD\b", title, re.I) or re.search(r"##\s*(Problem Statement|User Stories)", body, re.I):
        return None
    category = None if names & {"bug", "enhancement"} else ("bug" if _BUG.search(title) else "enhancement")
    # A ticket that says what to build under another common heading counts (#240, #218, #230, #217 sat parked for
    # writing "Solution"); "## Acceptance" with checkboxes counts as criteria.
    has_what = bool(re.search(r"##\s*(What to build|What|Summary|Description|Solution|Approach|Proposal|Design|Build|Problem|Convention)\b", body, re.I))
    has_ac = bool(re.search(r"##\s*Acceptance(?:\s+criteria)?\b[\s\S]*?- \[[ x]\]", body, re.I))
    missing = [m for m, ok in (("a 'What to build' section", has_what), ("acceptance criteria", has_ac)) if not ok]
    if missing:
        return {"state": "needs-info", "category": category, "missing": missing,
                "why": "missing " + " and ".join(missing)}
    if _HUMAN_TITLE.search(title):
        gaps = human_task_gaps(body)
        if gaps:
            return {"state": "needs-info", "category": category, "missing": gaps,
                    "why": "for you, but it does not say exactly what to do: needs " + ", ".join(gaps) + " (a 'Your task' section)"}
        return {"state": "ready-for-human", "category": category, "missing": [], "why": "a decision or action only a person can take"}
    return {"state": "ready-for-agent", "category": category, "missing": [], "why": "has a description and acceptance criteria"}
