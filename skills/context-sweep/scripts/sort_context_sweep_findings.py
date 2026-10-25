#!/usr/bin/env python3
"""Sorts findings bucket for context-sweep by priority (highest first).
Generalized from sort_suggestions.py to accept --file parameter.

Splits on entry-header pattern (`## Title`), not a bare separator.
Ties broken by Impact, then by Effort (low wins).

Run standalone after context-sweep findings are added:
    ~/.agents/venv/bin/python sort_context_sweep_findings.py --file PATH
"""
from __future__ import annotations
import argparse
import re
import sys
from pathlib import Path

HEADER_RE = re.compile(r"^## (.+)$", re.MULTILINE)
PRIORITY_RE = re.compile(r"^\*\*Priority\*\*:\s*(\d+)", re.MULTILINE)
IMPACT_RE = re.compile(r"^\*\*Impact\*\*:\s*(\S+)", re.MULTILINE)
EFFORT_RE = re.compile(r"^\*\*Effort\*\*:\s*(\S+)", re.MULTILINE)
STATUS_RE = re.compile(r"^\*\*Status\*\*:\s*(\S+)", re.MULTILINE)

# Impact ranking for context-sweep: contradiction and redundancy (structural issues)
# rank higher than QA gaps (missing verification), following the north-star principle
# that issues affecting maintainability and clarity outrank missing tests.
IMPACT_RANK = {
    "contradiction": 0,
    "redundancy": 1,
    "qa-gap": 2,
}
EFFORT_RANK = {"low": 0, "medium": 1, "high": 2}

DEFAULT_HEADER = """# Context Sweep Findings

Content integrity checks: contradictions, redundancy, QA gaps in MARVIN's own knowledge store.
Highest priority first — kept sorted by this script.
"""


def _split_entries(text: str) -> tuple[str, list[str]]:
    """Split text into preamble and entry blocks on ## headers."""
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
    """Return sort tuple: (resolved, priority, impact_rank, effort_rank).
    Lower tuples sort first (except priority is negated)."""
    status_m = STATUS_RE.search(block)
    status = status_m.group(1) if status_m else "pending"
    # Resolved (done/rejected) entries sink to the bottom
    is_resolved = 0 if status == "pending" else 1

    priority_m = PRIORITY_RE.search(block)
    priority = -int(priority_m.group(1)) if priority_m else 0  # negate: higher priority sorts first

    impact_m = IMPACT_RE.search(block)
    impact_rank = IMPACT_RANK.get(impact_m.group(1) if impact_m else "", 99)

    effort_m = EFFORT_RE.search(block)
    effort_rank = EFFORT_RANK.get(effort_m.group(1) if effort_m else "", 99)

    return (is_resolved, priority, impact_rank, effort_rank)


def sort_findings(file_path: Path | str) -> int:
    """Sort findings in the given file by priority. Returns entry count."""
    file_path = Path(file_path)

    if not file_path.exists() or not file_path.read_text().strip():
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(DEFAULT_HEADER)
        return 0

    text = file_path.read_text()
    preamble, blocks = _split_entries(text)
    if not preamble.strip():
        preamble = DEFAULT_HEADER

    blocks.sort(key=_sort_key)

    new_text = preamble.rstrip("\n") + "\n\n" + "\n".join(b.rstrip("\n") + "\n" for b in blocks)
    file_path.write_text(new_text)
    return len(blocks)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Sort findings by priority")
    parser.add_argument("--file", type=Path, default=Path.home() / ".claude" / "context-sweep-findings.md",
                        help="Path to findings file (default: ~/.claude/context-sweep-findings.md)")
    args = parser.parse_args()

    count = sort_findings(args.file)
    print(f"[sort-context-sweep-findings] {count} entries sorted by priority", file=sys.stderr)
