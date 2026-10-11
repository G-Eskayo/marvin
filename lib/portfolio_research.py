#!/usr/bin/env python3
"""Research evidence logging for portfolio pages (ADR 0051).

Parses evidence logs from projects, renders them into portfolio content sections, and updates
content files with research findings. Markdown evidence logs contain structured entries with
source links, key findings, confidence levels, and public/internal classification.

Usage:
    portfolio_research.py <repo_path> <content.json>
"""
from __future__ import annotations

import html
import json
import os
import re
import sys
from pathlib import Path
from tempfile import NamedTemporaryFile

# ── parse_evidence_log ──

def parse_evidence_log(text: str) -> dict:
    """Parse markdown-formatted evidence log into structured entries.

    Returns:
        {
            "entries": [
                {
                    "source_title": str,
                    "source_url": str,
                    "source_html": str,  # rendered <a> tag
                    "takeaway": str,  # HTML-escaped
                    "confidence": str,
                    "decision": str,  # HTML-escaped
                    "public": "Yes" | "Careful" | None,
                },
                ...
            ],
            "warnings": [str, ...],
        }
    """
    entries = []
    warnings = []

    # Extract the Evidence section if it exists, otherwise use whole text
    match = re.search(r"##\s+Evidence\s*\n(.*?)(?=##|\Z)", text, re.DOTALL | re.IGNORECASE)
    section_text = match.group(1) if match else text

    if not section_text.strip():
        warnings.append("No 'Evidence' section found in markdown")
        return {"entries": [], "warnings": warnings}

    # Split into bullet-point entries (lines starting with "- Source:")
    entry_blocks = re.split(r"(?=\n-\s+Source:)", section_text)

    found_any_source = False
    for block in entry_blocks:
        block = block.lstrip()
        if not block.strip() or "Source:" not in block:
            continue

        found_any_source = True
        entry, warning = _parse_entry_block(block)
        if entry:
            entries.append(entry)
            if warning:
                warnings.append(warning)
            if "decision" not in entry:
                warnings.append(f"Entry '{entry.get('source_title', 'unknown')}' missing 'decision' field")
        else:
            warnings.append(f"Malformed entry in evidence log")

    if not found_any_source and not match:
        warnings.append("No 'Evidence' section found in markdown")

    return {"entries": entries, "warnings": warnings}


def _parse_entry_block(block: str) -> tuple[dict | None, str | None]:
    """Parse a single entry block from the evidence section.

    Returns:
        (entry_dict, warning_str | None)
    """
    entry = {}
    warning = None

    # Extract Source: [Title](URL)
    source_match = re.search(r"Source:\s*\[([^\]]+)\]\(([^)]+)\)", block, re.IGNORECASE)
    if source_match:
        entry["source_title"] = source_match.group(1)
        entry["source_url"] = source_match.group(2)
        entry["source_html"] = f'<a href="{source_match.group(2)}">{source_match.group(1)}</a>'
    else:
        return None, None

    # Extract Takeaway (optional but warn if missing with decision)
    takeaway_match = re.search(r"Takeaway:\s*(.+?)(?=\n\s+\w+:|$)", block, re.IGNORECASE | re.DOTALL)
    if takeaway_match:
        entry["takeaway"] = html.escape(takeaway_match.group(1).strip())

    # Extract Confidence (optional)
    confidence_match = re.search(r"Confidence:\s*(.+?)(?=\n\s+\w+:|$)", block, re.IGNORECASE | re.DOTALL)
    if confidence_match:
        entry["confidence"] = confidence_match.group(1).strip()

    # Extract Decision (optional)
    decision_match = re.search(r"Decision:\s*(.+?)(?=\n\s+\w+:|$)", block, re.IGNORECASE | re.DOTALL)
    if decision_match:
        entry["decision"] = html.escape(decision_match.group(1).strip())

    # Extract Public field (must be exactly "Yes" or "Careful")
    public_match = re.search(r"Public:\s*(.+?)(?=\n|$)", block, re.IGNORECASE)
    if public_match:
        public_value = public_match.group(1).strip()
        if public_value in ("Yes", "Careful"):
            entry["public"] = public_value
        else:
            entry["public"] = None
            warning = f"Entry '{entry.get('source_title', 'unknown')}': Public field value '{public_value}' is not 'Yes' or 'Careful'"
    else:
        entry["public"] = None

    return entry, warning


# ── render_research_section ──

def render_research_section(entries: list[dict], style: str = "option_a") -> dict:
    """Render research entries into HTML callout markup.

    Returns:
        {
            "html": str,  # .longform-callout markup
            "shown": int,  # count of public entries
            "hidden_internal": int,  # count of internal entries
            "warnings": [str, ...],
        }
    """
    warnings = []
    shown_count = 0
    hidden_count = 0
    html_parts = []

    if style == "option_a" or style == "default":
        # Single shared callout for all entries
        html_parts.append('<div class="longform-callout">')
        html_parts.append('<h3>Research Behind It</h3>')
        html_parts.append('<ul>')

        for entry in entries:
            if not entry.get("source_html") or not entry.get("takeaway"):
                warnings.append(f"Entry missing required fields (source_html or takeaway)")
                continue

            if entry.get("public") in ("Yes", "Careful"):
                shown_count += 1
            else:
                hidden_count += 1

            source = entry.get("source_html", "")
            takeaway = entry.get("takeaway", "")
            confidence = entry.get("confidence", "")
            decision = entry.get("decision", "")

            html_parts.append(f'<li>{source}: {takeaway}')
            if confidence:
                html_parts.append(f' <span class="confidence">[{confidence}]</span>')
            if decision:
                html_parts.append(f' <em>{decision}</em>')
            html_parts.append('</li>')

        html_parts.append('</ul>')
        html_parts.append('</div>')

    return {
        "html": "".join(html_parts),
        "shown": shown_count,
        "hidden_internal": hidden_count,
        "warnings": warnings,
    }


# ── insert_or_update_section ──

def insert_or_update_section(
    sections: list[dict],
    role: str,
    heading: str,
    body_html: str,
    template: dict | None = None,
) -> list[dict]:
    """Insert or update a research section in the sections list.

    - If body_html is empty/None and a research section exists, remove it
    - If template specifies an index, insert at that position
    - Otherwise, replace existing section with same role or append
    """
    # Remove existing section with this role
    sections = [s for s in sections if s.get("role") != role]

    # If body is empty, return without adding
    if not body_html:
        return sections

    # Build the new section
    new_section = {
        "role": role,
        "heading": heading,
        "body_html": body_html,
    }

    # Insert at template index or append
    if template and "index" in template:
        idx = template["index"]
        sections.insert(idx, new_section)
    else:
        sections.append(new_section)

    return sections


# ── generate ──

def generate(repo_path: str, content_path: str) -> dict:
    """Generate research section from evidence log and update content file.

    Args:
        repo_path: Path to the project repository
        content_path: Path to the content JSON file

    Returns:
        {
            "sections": [...],  # updated sections list
            "warnings": [...],
            "status": "updated" | "removed" | "unchanged",
        }

    Raises:
        FileNotFoundError: If content_path or evidence-log.md doesn't exist
        PermissionError: If files aren't readable/writable
        json.JSONDecodeError: If content file isn't valid JSON
    """
    repo_path = Path(repo_path)
    content_path = Path(content_path)

    # Check content file exists
    if not content_path.exists():
        raise FileNotFoundError(f"Content file not found: {content_path}")

    # Find evidence log (looking in docs/research/evidence-log.md)
    evidence_log_path = repo_path / "docs" / "research" / "evidence-log.md"
    if not evidence_log_path.exists():
        raise FileNotFoundError(f"Evidence log not found: {evidence_log_path}")

    try:
        evidence_text = evidence_log_path.read_text()
    except (OSError, IOError) as e:
        raise PermissionError(f"Cannot read evidence log: {e}")

    try:
        content_text = content_path.read_text()
        content = json.loads(content_text)
    except json.JSONDecodeError as e:
        raise json.JSONDecodeError(f"Invalid JSON in content file", content_text, e.pos)
    except (OSError, IOError) as e:
        raise PermissionError(f"Cannot read content file: {e}")

    # Parse evidence log
    log_result = parse_evidence_log(evidence_text)
    entries = log_result["entries"]
    warnings = log_result["warnings"]

    # If no public entries, remove research section
    if not any(e.get("public") in ("Yes", "Careful") for e in entries):
        updated_sections = insert_or_update_section(
            content.get("sections", []),
            role="research",
            heading="Research Behind It",
            body_html="",
        )
        status = "removed"
    else:
        # Render research section
        render_result = render_research_section(entries, style="option_a")
        warnings.extend(render_result["warnings"])

        # Update sections
        updated_sections = insert_or_update_section(
            content.get("sections", []),
            role="research",
            heading="Research Behind It",
            body_html=render_result["html"],
        )
        status = "updated"

    # Update content
    content["sections"] = updated_sections

    # Write atomically
    try:
        with NamedTemporaryFile(
            mode="w",
            dir=content_path.parent,
            delete=False,
            suffix=".json",
        ) as tmp:
            tmp_path = Path(tmp.name)
            json.dump(content, tmp, indent=2)
        os.replace(tmp_path, content_path)
    except (OSError, IOError) as e:
        raise PermissionError(f"Cannot write content file: {e}")

    return {
        "sections": updated_sections,
        "warnings": warnings,
        "status": status,
    }


def main() -> None:
    """CLI entry point: portfolio_research.py <repo_path> <content_path>"""
    if len(sys.argv) < 3:
        print("Usage: portfolio_research.py <repo_path> <content_path>", file=sys.stderr)
        sys.exit(1)

    repo_path = sys.argv[1]
    content_path = sys.argv[2]

    try:
        result = generate(repo_path, content_path)
        for warning in result["warnings"]:
            print(f"Warning: {warning}", file=sys.stderr)
        print(f"Status: {result['status']}", file=sys.stderr)
    except (FileNotFoundError, PermissionError, json.JSONDecodeError) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
