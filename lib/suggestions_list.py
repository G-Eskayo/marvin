#!/usr/bin/env python3
"""Reads ~/.claude/suggestions.md, parses entries, outputs JSON for the dashboard.

Reuses _split_entries, field regexes, and sort order from
architecture-review/scripts/sort_suggestions.py. No file writes — read-only.
"""
import json
import sys
from pathlib import Path

# Reuse the exact parsing from sort_suggestions (worktree-safe path)
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills" / "architecture-review" / "scripts"))

_sort_suggestions_cache = None
_import_error = None

def _load_sort_suggestions():
  global _sort_suggestions_cache, _import_error
  if _sort_suggestions_cache is not None:
    return _sort_suggestions_cache
  try:
    from sort_suggestions import _split_entries, HEADER_RE, PRIORITY_RE, IMPACT_RE, EFFORT_RE, STATUS_RE, SUGGESTIONS_FILE
    _sort_suggestions_cache = {
        '_split_entries': _split_entries,
        'HEADER_RE': HEADER_RE,
        'PRIORITY_RE': PRIORITY_RE,
        'IMPACT_RE': IMPACT_RE,
        'EFFORT_RE': EFFORT_RE,
        'STATUS_RE': STATUS_RE,
        'SUGGESTIONS_FILE': SUGGESTIONS_FILE,
    }
    return _sort_suggestions_cache
  except ImportError as e:
    _import_error = e
    return None


def suggestions_list(suggestions_file=None):
    """Read suggestions.md, return JSON array of entries.

    Args:
        suggestions_file: Optional Path override for testing.
    """
    cache = _load_sort_suggestions()
    if cache is None:
        raise _import_error

    split_entries = cache['_split_entries']
    header_re = cache['HEADER_RE']
    priority_re = cache['PRIORITY_RE']
    impact_re = cache['IMPACT_RE']
    effort_re = cache['EFFORT_RE']
    status_re = cache['STATUS_RE']
    suggestions_file_path = cache['SUGGESTIONS_FILE']

    file_path = suggestions_file or suggestions_file_path

    if not file_path.exists():
        return []

    text = file_path.read_text(encoding="utf-8")
    if not text.strip():
        return []

    preamble, blocks = split_entries(text)
    if not blocks:
        return []

    entries = []
    for block in blocks:
        # Extract title from the first "## Title" line
        title_match = header_re.search(block)
        if not title_match:
            # Malformed entry without a header; skip it
            continue

        title = title_match.group(1)

        # Extract fields
        priority_m = priority_re.search(block)
        priority = int(priority_m.group(1)) if priority_m else None

        status_m = status_re.search(block)
        status = status_m.group(1) if status_m else "pending"

        impact_m = impact_re.search(block)
        impact = impact_m.group(1) if impact_m else None

        effort_m = effort_re.search(block)
        effort = effort_m.group(1) if effort_m else None

        # Body = the full block minus its "## Title" header line
        # Strip the header line but keep the rest for markdown rendering
        lines = block.split("\n")
        body_lines = []
        skip_next = True
        for line in lines:
            if skip_next and line.startswith("## "):
                skip_next = False
                continue
            body_lines.append(line)
        body = "\n".join(body_lines).strip()

        entries.append({
            "title": title,
            "priority": priority,
            "status": status,
            "impact": impact,
            "effort": effort,
            "body": body
        })

    return entries


if __name__ == "__main__":
    try:
        result = suggestions_list()
        print(json.dumps(result))
    except Exception as e:
        # Always output valid JSON on error, never crash with a traceback
        print(json.dumps([]))
        print(f"Error reading suggestions: {e}", file=sys.stderr)
        sys.exit(1)
