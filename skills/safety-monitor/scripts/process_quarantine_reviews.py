#!/usr/bin/env python3
"""Closes the loop calibrate.py's record_label() was always meant to have.

Found 2026-07-09: quarantine.md has approve/modify/deny checkboxes, and
calibrate.py's record_label() docstring says "Intended caller: the
quarantine review workflow, once built" — but nothing ever read the
checkboxes back into calibration. Zero of 18 boxes had ever been checked,
tau.json didn't exist, and every daily_digest/research_colony run was
getting quarantined at the frozen default threshold forever, with no way
for the system to learn from real review decisions.

Splits quarantine.md on its entry-header pattern (`## YYYY-MM-DD — name
[SAFETY, ...]`), not the plain "---" separator — a bare "---" can appear
inside a quoted entry's own body (found 2026-07-09: a pre-2026-07-08-fix
legacy entry only quoted its first line, leaving a literal unquoted "---"
markdown divider in its body, which broke a first attempt at splitting on
that instead). The header pattern is specific enough not to collide with
real digest content. Finds entries with a checked box, calls
calibrate.record_label() for each (approve/modify -> 0 "was actually fine",
deny -> 1 "was actually bad"), then removes those entries from quarantine.md
so they don't get re-processed and the pending count stays accurate.

Run standalone or via launchd: ~/.agents/venv/bin/python process_quarantine_reviews.py
"""
from __future__ import annotations
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from calibrate import record_label  # noqa: E402

QUARANTINE_FILE = Path.home() / ".claude" / "quarantine.md"

HEADER_RE = re.compile(r"^## (\d{4}-\d{2}-\d{2}) — (\S+) \[SAFETY, score ([\d.]+), tau ([\d.]+)\]", re.MULTILINE)
CHECKBOX_RE = re.compile(r"^- \[([ xX])\] (approve|deny|modify)")


def _split_entries(text: str) -> tuple[str, list[str]]:
    """Splits on the entry-header pattern, not "---" (which can appear
    unquoted inside a legacy entry's own body). Returns (preamble, blocks) —
    each block starts right at its own "## date — name [SAFETY..." header."""
    matches = list(HEADER_RE.finditer(text))
    if not matches:
        return text, []
    preamble = text[:matches[0].start()]
    blocks = []
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        blocks.append(text[m.start():end])
    return preamble, blocks


def _parse_block(block: str) -> dict | None:
    header_match = HEADER_RE.search(block)
    if not header_match:
        return None
    date, loop_name, score_str, tau_str = header_match.groups()

    checked_kind = None
    for line in block.splitlines():
        cb = CHECKBOX_RE.match(line.strip())
        if cb and cb.group(1).strip().lower() == "x":
            checked_kind = cb.group(2)
            break

    return {
        "date": date, "loop_name": loop_name, "score": float(score_str),
        "tau": float(tau_str), "checked": checked_kind,
    }


def process() -> tuple[int, int]:
    """Returns (processed_count, remaining_count)."""
    if not QUARANTINE_FILE.exists():
        return 0, 0
    text = QUARANTINE_FILE.read_text()

    preamble, entry_blocks = _split_entries(text)

    processed = 0
    remaining_blocks = []

    for block in entry_blocks:
        info = _parse_block(block)
        if info is None or info["checked"] is None:
            remaining_blocks.append(block)
            continue

        # approve/modify -> the artifact was actually fine (label 0, not a
        # dangerous fabrication, at most needed a tweak); deny -> genuinely
        # bad (label 1).
        label = 1 if info["checked"] == "deny" else 0
        record_label(info["loop_name"], info["score"], label)
        processed += 1
        print(f"[process-quarantine-reviews] recorded {info['loop_name']} "
              f"score={info['score']:.2f} label={label} ({info['checked']})", file=sys.stderr)

    new_text = preamble + "".join(f"\n---\n{b}" for b in remaining_blocks)
    if processed:
        QUARANTINE_FILE.write_text(new_text)

    return processed, len(remaining_blocks)


if __name__ == "__main__":
    processed, remaining = process()
    print(f"[process-quarantine-reviews] {processed} review(s) processed, {remaining} still pending", file=sys.stderr)
