"""Brief items shape and mappers from source records (marvin#306)."""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable


@dataclass
class Source:
    """Where an item came from."""
    url: str | None = None
    related: str | None = None


@dataclass
class Item:
    """One piece of content in the morning brief."""
    section: str  # one of SECTIONS below
    rank: int  # 1-indexed, assigned after sorting; 0 during building
    line: str  # one line of text to show
    summary: str  # concise label for internal use (e.g. "PR #123")
    source: Source = field(default_factory=Source)


SECTIONS = ["Needs you", "Waiting on MARVIN", "Overnight", "Today"]


def _safe_line(text: str, max_len: int = 200) -> str:
    """Sanitize a line for display: NFC-normalize, truncate, strip control chars."""
    if not text:
        return ""
    # Normalize to NFC to combine diacritics
    text = unicodedata.normalize("NFC", text)
    # Strip leading/trailing whitespace
    text = text.strip()
    # Remove control characters but keep newlines (which we'll strip anyway)
    text = "".join(c for c in text if unicodedata.category(c)[0] != "C" or c == "\n")
    # Take first line only
    text = text.split("\n")[0].strip()
    # Truncate if needed
    if len(text) > max_len:
        text = text[:max_len - 1] + "…"
    return text


def _ref(item: dict, pr: bool = False) -> str:
    """Format a reference (PR or ticket) with number and title."""
    repo = f"{item['repo']} " if item.get("repo") and item["repo"] != "marvin" else ""
    return f"{repo}{'PR ' if pr else ''}#{item['number']} {_safe_line(item['title'])}"


def _dedup_key(item: Item) -> tuple:
    """Key for deduplication: (reference_type, id_or_prefix)."""
    # Try to extract repo and number from summary first (most reliable)
    if ":" in item.summary:
        prefix, rest = item.summary.split(":", 1)
        # summary format is like "pr:100" or "ticket:14" or "health:Missed purpose"
        try:
            number = int(rest)
            return ("reference", f"{prefix}:{number}")
        except ValueError:
            pass

    # Fallback: extract any #NNN pattern from the line
    m = re.search(r"#(\d+)", item.line)
    if m:
        # Return a consistent key based on the number alone
        # This dedupes tickets/PRs with same number regardless of source
        return ("reference", f"#{m.group(1)}")

    # For text-only items (health checks, ideas), use normalized prefix
    prefix = item.line.split(":")[0].strip().lower()
    # Remove common words to increase dedup chances
    prefix = re.sub(r"\b(the|your|a|an)\b", "", prefix).strip()
    return ("text", prefix)


def _score_item(item: Item, now: datetime) -> float:
    """Deterministic score for sorting: higher = more urgent.

    Priority order (highest to lowest):
    1. Red Health issues (section hint: "Needs you" with label "Missed purpose" etc)
    2. Hard deadlines by proximity
    3. p0 tickets
    4. p1 tickets
    5. Actionable PR reviews
    6. Soft deadlines
    7. Digest/research ideas
    """
    # Health failures at top
    if "Missed purpose" in item.line or ": " in item.line:
        # Heuristic: Health items have label: detail format
        if item.line.count(":") == 1:
            return 1000.0

    # Hard deadline proximity (earlier is higher score)
    if "hard deadline" in item.line.lower():
        # Extract days if present
        m = re.search(r"(\d+)\s+days?\s*\(", item.line)
        if m:
            days = int(m.group(1))
            return 900.0 - days * 10  # 900-1 for 1-90 days

    # p0 tickets
    if ": p0:" in item.line or item.line.startswith("p0:"):
        return 850.0

    # p1 tickets
    if ": p1:" in item.line or item.line.startswith("p1:"):
        return 800.0

    # PR reviews (actionable)
    if "Review" in item.line or "PR #" in item.line:
        return 700.0

    # Soft deadline proximity
    if "days" in item.line.lower() and "deadline" in item.line.lower():
        m = re.search(r"(\d+)\s+days?", item.line)
        if m:
            days = int(m.group(1))
            return 600.0 - days * 5  # 600-1 for 1-120 days

    # Ideas and other items
    return 500.0


# ── Item mappers from source records ────────────────────────────────────

def to_item_auto_merge(source_key: str, record: str | None, now: datetime = None) -> Item | list[Item]:
    """Auto-merge shadow report line."""
    if not record:
        return []
    return Item(section="Needs you", rank=0, line=f"- {record}",
                summary="auto-merge", source=Source(url=None))


def to_item_red_checks(source_key: str, records: list[dict] | None, now: datetime = None) -> Item | list[Item]:
    """Red Health checks."""
    if not records:
        return []
    return [Item(section="Needs you", rank=0, line=f"- {c['label']}: {_safe_line(c['detail'])}",
                 summary=f"health:{c['label']}", source=Source(url=None))
            for c in records]


def to_item_human_tickets(source_key: str, records: list[dict] | None, now: datetime = None) -> Item | list[Item]:
    """Tickets waiting on the human."""
    if not records:
        return []
    return [Item(section="Needs you", rank=0, line=f"- Your task: {_ref(t)}",
                 summary=f"ticket:{t['number']}", source=Source(url=None))
            for t in records]


def to_item_open_prs(source_key: str, records: list[dict] | None, now: datetime = None) -> Item | list[Item]:
    """Open PRs: waiting-on-marvin in one section, needs-review in another."""
    if not records:
        return []
    out = []
    for p in records:
        if p.get("waiting_on_marvin"):
            q = " and you asked a question" if p.get("question") else ""
            out.append(Item(section="Waiting on MARVIN", rank=0,
                           line=f"- {_ref(p, pr=True)}: your decisions are in{q}",
                           summary=f"pr:{p['number']}", source=Source(url=None)))
        else:
            out.append(Item(section="Needs you", rank=0, line=f"- Review {_ref(p, pr=True)}",
                           summary=f"pr:{p['number']}", source=Source(url=None)))
    return out


def to_item_regressions(source_key: str, records: list[dict] | None, now: datetime = None) -> Item | list[Item]:
    """Solved problems that came back (incident ladder)."""
    if not records:
        return []
    out = []
    for r in records:
        section = "Needs you" if r.get("kind") == "needs-you" else "Overnight"
        out.append(Item(section=section, rank=0, line=f"- {r['line']}",
                       summary="regression", source=Source(url=None)))
    return out


def to_item_launches(source_key: str, records: list[dict] | None, now: datetime = None) -> Item | list[Item]:
    """Model runs last night."""
    if not records:
        return Item(section="Overnight", rank=0,
                   line="- Quiet: no model runs or merges in the last day.",
                   summary="quiet-night", source=Source(url=None))
    by_kind: dict[str, int] = {}
    for r in records:
        by_kind[r.get("kind", "?")] = by_kind.get(r.get("kind", "?"), 0) + 1
    cost = sum(r.get("cost_usd") or 0 for r in records)
    line = (f"- {len(records)} model runs (" + ", ".join(f"{n} {k}" for k, n in sorted(by_kind.items()))
            + f"), ${cost:.2f}")
    return Item(section="Overnight", rank=0, line=line,
               summary="launches", source=Source(url=None))


def to_item_merged(source_key: str, records: list[dict] | None, now: datetime = None) -> Item | list[Item]:
    """Recently merged PRs."""
    if not records:
        return []
    return [Item(section="Overnight", rank=0, line=f"- Merged {_ref(p, pr=True)}",
                 summary=f"merged:{p['number']}", source=Source(url=None))
            for p in records]


def to_item_revisited(source_key: str, records: list[dict] | None, now: datetime = None) -> Item | list[Item]:
    """Tickets returned from hold."""
    if not records:
        return []
    return [Item(section="Overnight", rank=0, line=f"- Returned from hold: {_ref(t)}",
                 summary=f"revisited:{t['number']}", source=Source(url=None))
            for t in records]


def to_item_deadlines(source_key: str, records: list[dict] | None, now: datetime = None) -> Item | list[Item]:
    """Project deadlines."""
    if not records:
        return []

    def days_until(date: str, when: datetime) -> int:
        from datetime import datetime as dt
        return (dt.fromisoformat(date).date() - when.astimezone().date()).days

    if now is None:
        now = datetime.now(timezone.utc)
    items = []
    for d in records:
        days = days_until(d["date"], now)
        line = f"- {d['project']}: {days} days ({d['date']}{', hard deadline' if d['hard'] else ''})"
        items.append(Item(section="Today", rank=0, line=line,
                         summary=f"deadline:{d['project']}", source=Source(url=None)))
    return items


def to_item_top_tickets(source_key: str, records: list[dict] | None, now: datetime = None) -> Item | list[Item]:
    """Priority p0/p1 tickets."""
    if not records:
        return []
    return [Item(section="Today", rank=0, line=f"- {t['priority']}: {_ref(t)}",
                 summary=f"ticket:{t['number']}", source=Source(url=None))
            for t in records]


def to_item_digest_idea(source_key: str, record: str | None, now: datetime = None) -> Item | list[Item]:
    """One idea from the daily digest (not part of regular sections)."""
    if not record:
        return []
    # Use a special "ideas" section that render() will handle separately
    return Item(section="__ideas__", rank=0, line=f"- **Compounding move:** {_safe_line(record)}",
               summary="digest-idea", source=Source(url=None))


def to_item_research_idea(source_key: str, record: str | None, now: datetime = None) -> Item | list[Item]:
    """One idea from the research digest (not part of regular sections)."""
    if not record:
        return []
    # Use a special "ideas" section that render() will handle separately
    return Item(section="__ideas__", rank=0, line=f"- **From research:** {_safe_line(record)}",
               summary="research-idea", source=Source(url=None))


def to_item_late_night(source_key: str, record: str | None, now: datetime = None) -> Item | list[Item]:
    """Note about working late (goes to footer, not a brief item)."""
    return []  # Handled separately in render


def mapper_for(source_key: str) -> Callable | None:
    """Get the item mapper for a given source."""
    mappers = {
        "auto_merge": to_item_auto_merge,
        "red_checks": to_item_red_checks,
        "human_tickets": to_item_human_tickets,
        "open_prs": to_item_open_prs,
        "regressions": to_item_regressions,
        "launches": to_item_launches,
        "merged": to_item_merged,
        "revisited": to_item_revisited,
        "deadlines": to_item_deadlines,
        "top_tickets": to_item_top_tickets,
        "digest_idea": to_item_digest_idea,
        "research_idea": to_item_research_idea,
        "late_night": to_item_late_night,
    }
    return mappers.get(source_key)


def select_items(data: dict, now: datetime) -> list[Item]:
    """Build, dedup, score, and sort items from gather() output.

    Args:
        data: dict from gather() with keys being source names
        now: current datetime for scoring context

    Returns:
        list of Item objects (≤5 total) with ranks assigned per section
    """
    # Build all items from each source
    all_items = []
    for source_key, record in data.items():
        if source_key == "missing":
            continue
        mapper = mapper_for(source_key)
        if not mapper or record is None:
            continue
        result = mapper(source_key, record, now)
        if isinstance(result, list):
            all_items.extend(result)
        elif result:
            all_items.append(result)

    # Dedup by key, keeping first occurrence
    seen = set()
    deduped = []
    for item in all_items:
        key = _dedup_key(item)
        if key not in seen:
            seen.add(key)
            deduped.append(item)

    # Separate ideas from main items
    ideas = []
    main_items = []
    for item in deduped:
        if item.section == "__ideas__":
            ideas.append(item)
        else:
            main_items.append(item)

    # Score main items
    scored_main = [(score := _score_item(item, now), item) for item in main_items]

    # Sort main items globally by score, then by section order
    scored_main.sort(key=lambda x: (-x[0], SECTIONS.index(x[1].section) if x[1].section in SECTIONS else 999))

    # Take top 5 main items
    top_main_items = [item for _, item in scored_main[:5]]

    # Group main items by section and assign ranks within each section
    section_items = {}
    for item in top_main_items:
        if item.section not in section_items:
            section_items[item.section] = []
        section_items[item.section].append(item)

    # Assign ranks within each section for main items
    result = []
    for section in SECTIONS:
        if section in section_items:
            for rank, item in enumerate(section_items[section], 1):
                item.rank = rank
            result.extend(section_items[section])

    # Add ideas at the end (they don't count toward 5-item cap)
    for rank, idea in enumerate(ideas, 1):
        idea.rank = rank
    result.extend(ideas)

    return result
