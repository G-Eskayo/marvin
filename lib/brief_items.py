"""Brief items: structured, deduplicated, ranked list items for the morning brief (marvin#462).

An item is a brief, one-line unit with a section, priority tier, and display text. The brief builds
one item at a time from multiple sources; rank_and_cap() deduplicates, sorts by tier and stability,
caps each section at 5, and assigns final rank. render_sections() converts to markdown.

Item structure:
  {
    "section": "your_projects" | "your_day" | "research" | "world_security",
    "tier": 0 | 1 | 2 | 3,  # 0 = highest priority; capped per section
    "line": "markdown line text",
    "order_key": optional sort key (defaults to 0),
    "rank": assigned by rank_and_cap() (0-N per section),
    ... other fields preserved ...
  }
"""
from __future__ import annotations

import re
from typing import Any

SECTIONS = ("your_projects", "your_day", "research", "world_security")
SECTION_LABELS = {
    "your_projects": "Needs you",
    "your_day": "Today",
    "research": "One idea each",
    "world_security": "World",
}


def sanitize(text: str, max_len: int = 300) -> str:
    """Collapse whitespace/control chars, escape markdown special chars, truncate.

    Args:
        text: input line
        max_len: max output length (truncates with '…' if exceeded)

    Returns:
        sanitized line, fit for markdown bullet
    """
    # Collapse runs of whitespace to single space; drop control chars
    text = re.sub(r"[\x00-\x08\x0b-\x0c\x0e-\x1f]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()

    # Escape markdown special chars
    text = re.sub(r"([\[\]<>])", r"\\\1", text)

    # Truncate if needed
    if len(text) > max_len:
        text = text[:max_len - 1].rstrip() + "…"

    return text


def make_item(section: str, tier: int, line: str, **kwargs) -> dict[str, Any]:
    """Build an item, ensuring all three layers are present. Rejects empty lines.

    Args:
        section: one of SECTIONS
        tier: 0-3 (0 = highest priority)
        line: display text (non-empty after sanitize)
        **kwargs: additional fields (number, title, repo, order_key, etc.)

    Returns:
        item dict with section, tier, line, and any extra fields

    Raises:
        ValueError if section invalid, tier out of range, or line empty after sanitize
    """
    if section not in SECTIONS:
        raise ValueError(f"invalid section {section!r}, must be one of {SECTIONS}")
    if not 0 <= tier <= 3:
        raise ValueError(f"tier must be 0-3, got {tier}")

    clean_line = sanitize(line)
    if not clean_line:
        raise ValueError(f"line is empty after sanitize")

    return {"section": section, "tier": tier, "line": clean_line, **kwargs}


def _dedup_key(item: dict) -> tuple:
    """Extract stable dedup key: section + (number, repo) if present, else line.

    Two items with the same key are considered duplicates; only the first (by rank)
    is kept. This handles tickets/PRs by number+repo, and others by text.
    """
    if "number" in item and "repo" in item:
        return (item["section"], "ticket", item["number"], item["repo"])
    return (item["section"], "text", item["line"])


def rank_and_cap(items: list[dict], total_cap: int = 5) -> list[dict]:
    """Sort items by tier/order_key/insertion, dedupe, cap at total 5, assign rank.

    Modifies items in-place to add 'rank' field (0-N per section, global cap).
    Returns the input list (mutated) for chaining. Items beyond the cap are discarded.

    Args:
        items: list of items (each from make_item)
        total_cap: max items total across all sections (default 5)

    Returns:
        same list, sorted and with 'rank' field added (may be shorter than input)
    """
    # Sort by: tier first, then section order, then order_key (or 0), then insertion index.
    # Tier first ensures urgency (tier 0) wins across sections before section order.
    def sort_key(indexed_item):
        idx, item = indexed_item
        tier = item["tier"]
        section_order = SECTIONS.index(item["section"])
        order_key = item.get("order_key", 0)
        return (tier, section_order, order_key, idx)

    indexed = list(enumerate(items))
    indexed.sort(key=sort_key)
    items.clear()
    items.extend(item for _, item in indexed)

    # Deduplicate: keep first by rank, skip later duplicates
    seen = {}
    out = []
    for item in items:
        key = _dedup_key(item)
        if key not in seen:
            out.append(item)
            seen[key] = True

    # Cap at total and assign rank per-section
    section_ranks = {}
    ranked = []
    for item in out:
        if len(ranked) >= total_cap:
            break
        section = item["section"]
        rank = section_ranks.get(section, 0)
        item["rank"] = rank
        ranked.append(item)
        section_ranks[section] = rank + 1

    items.clear()
    items.extend(ranked)
    return items


def render_sections(items: list[dict]) -> str:
    """Render items as markdown bullets, grouped by section in fixed order.

    Skips empty sections. Each section gets a heading and bullet list.

    Args:
        items: list of items (after rank_and_cap)

    Returns:
        markdown string (no leading/trailing blank lines)
    """
    by_section = {s: [] for s in SECTIONS}
    for item in items:
        by_section[item["section"]].append(item)

    lines = []
    for section in SECTIONS:
        section_items = by_section[section]
        if not section_items:
            continue

        label = SECTION_LABELS.get(section, section)
        lines.append(f"## {label}")
        lines.append("")
        for item in section_items:
            lines.append(f"- {item['line']}")
        lines.append("")

    # Remove trailing blank lines
    while lines and lines[-1] == "":
        lines.pop()

    return "\n".join(lines)
