#!/usr/bin/env python3
"""Keeps ~/.claude/suggestions.md sorted by priority (highest first), not
insertion order — the actual mechanism behind "reorderable, like a todo
list" (Gil's direction, 2026-07-09; see ~/.agents/CONTEXT.md's
"Suggestions.md priority backlog" section).

Splits on the entry-header pattern (`## Title`), not a bare separator —
same lesson as process_quarantine_reviews.py: a naive separator can appear
unquoted inside an entry's own body. Ties broken by Impact (token-reduction
speed > organization/robustness, matching SKILL.md's Optimization
Priorities), then by Effort (low wins).

Run standalone or after any edit to suggestions.md:
    ~/.agents/venv/bin/python sort_suggestions.py
"""
from __future__ import annotations
import re
import sys
from pathlib import Path

SUGGESTIONS_FILE = Path.home() / ".claude" / "suggestions.md"

HEADER_RE = re.compile(r"^## (.+)$", re.MULTILINE)
PRIORITY_RE = re.compile(r"^\*\*Priority\*\*:\s*(\d+)", re.MULTILINE)
IMPACT_RE = re.compile(r"^\*\*Impact\*\*:\s*(\S+)", re.MULTILINE)
EFFORT_RE = re.compile(r"^\*\*Effort\*\*:\s*(\S+)", re.MULTILINE)
STATUS_RE = re.compile(r"^\*\*Status\*\*:\s*(\S+)", re.MULTILINE)

IMPACT_RANK = {"token-reduction": 0, "speed": 1, "organization": 2, "pipeline-logic": 3, "reliability": 4, "robustness": 5}
EFFORT_RANK = {"low": 0, "medium": 1, "high": 2}

DEFAULT_HEADER = (
    "# Suggestions\n\n"
    "Priority-ordered backlog of architecture/optimization suggestions, fed by `architecture-review`\n"
    "and `audit`. Highest priority first — kept sorted by `sort_suggestions.py`, not insertion order.\n"
    "Check every session (CLAUDE.md session-start step 2); never implement without explicit approval.\n"
)


def _split_entries(text: str) -> tuple[str, list[str]]:
    matches = list(HEADER_RE.finditer(text))
    if not matches:
        return text, []
    preamble = text[:matches[0].start()]
    blocks = []
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        blocks.append(text[m.start():end])
    return preamble, blocks


def _sort_key(block: str) -> tuple:
    status_m = STATUS_RE.search(block)
    status = status_m.group(1) if status_m else "pending"
    # done/rejected entries sink to the bottom regardless of priority — they're history, not backlog.
    is_resolved = 0 if status == "pending" else 1

    priority_m = PRIORITY_RE.search(block)
    priority = -int(priority_m.group(1)) if priority_m else 0  # negate: higher priority sorts first

    impact_m = IMPACT_RE.search(block)
    impact_rank = IMPACT_RANK.get(impact_m.group(1) if impact_m else "", 99)

    effort_m = EFFORT_RE.search(block)
    effort_rank = EFFORT_RANK.get(effort_m.group(1) if effort_m else "", 99)

    return (is_resolved, priority, impact_rank, effort_rank)


def sort_suggestions() -> int:
    if not SUGGESTIONS_FILE.exists() or not SUGGESTIONS_FILE.read_text().strip():
        SUGGESTIONS_FILE.write_text(DEFAULT_HEADER)
        return 0

    text = SUGGESTIONS_FILE.read_text()
    preamble, blocks = _split_entries(text)
    if not preamble.strip():
        preamble = DEFAULT_HEADER

    blocks.sort(key=_sort_key)

    new_text = preamble.rstrip("\n") + "\n\n" + "\n".join(b.rstrip("\n") + "\n" for b in blocks)
    SUGGESTIONS_FILE.write_text(new_text)
    return len(blocks)


if __name__ == "__main__":
    count = sort_suggestions()
    print(f"[sort-suggestions] {count} entries sorted by priority", file=sys.stderr)
