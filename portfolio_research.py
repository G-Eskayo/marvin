#!/usr/bin/env python3
"""Parse evidence logs from project repos and render them as portfolio research sections.

Usage: portfolio_research.py <repo-path> <content.json>

Reads docs/research/evidence-log.md from the repo, parses entries by their visibility tier
(Yes/Careful/Internal), renders the public ones as HTML, and inserts or updates the "research"
section in the longform content JSON (atomic write via temp file + os.replace).

Each entry in the evidence log is a markdown heading ## E<n>. <title> with fields:
  - Source: where the research came from
  - What we took: what insight we extracted
  - Confidence: Strong/Moderate/Weak/Ours
  - Drives: what decision it shaped
  - Public use: Yes/Careful/Internal

Entries marked "Yes" or "Careful" render on the portfolio page; "Internal" entries are logged
but hidden. "Careful" entries carry a caveat marker.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from pathlib import Path


def parse_evidence_log(text: str) -> dict:
    """Parse a markdown evidence log, returning entries and any parsing warnings.

    Returns: {"entries": [...], "warnings": [...]}
    """
    entries = []
    warnings = []

    # Find all ## EN. Title entries
    pattern = r"^## (E\d+)\.\s+(.+)$"
    for match in re.finditer(pattern, text, re.MULTILINE):
        entry_id = match.group(1)
        title = match.group(2).strip()

        # Extract the section from this entry until the next ## or end of text
        start_pos = match.end()
        next_heading = re.search(r"^##", text[start_pos:], re.MULTILINE)
        end_pos = start_pos + next_heading.start() if next_heading else len(text)
        section_text = text[start_pos:end_pos]

        # Parse fields: each is a line like "- **Field:** value."
        fields = {}
        for field_pattern in [
            (r"- \*\*Source:\*\* (.+?)(?=\n|$)", "source"),
            (r"- \*\*What we took:\*\* (.+?)(?=\n|$)", "took"),
            (r"- \*\*Confidence:\*\* (.+?)(?=\n|$)", "confidence"),
            (r"- \*\*Drives:\*\* (.+?)(?=\n|$)", "drives"),
            (r"- \*\*Public use:\*\* (.+?)(?=\n|$)", "public"),
        ]:
            field_match = re.search(field_pattern[0], section_text)
            if field_match:
                value = field_match.group(1).strip()
                fields[field_pattern[1]] = value
            elif field_pattern[1] in ("source", "took", "confidence", "drives", "public"):
                # Required fields
                warnings.append(f"{entry_id}: missing required field '{field_pattern[1]}'")

        if fields:
            # Extract "Careful" caveat if present in the public field
            public_raw = fields.get("public", "")
            # Extract just the first word (e.g., "Yes." or "Careful" or "Internal")
            public_match = re.match(r"(\w+)", public_raw)
            public_main = public_match.group(1) if public_match else ""
            caveat = None
            if " (" in public_raw:
                caveat = public_raw[public_raw.index("("):].rstrip(".")

            entries.append({
                "id": entry_id,
                "title": title,
                "source": fields.get("source", ""),
                "took": fields.get("took", ""),
                "confidence": fields.get("confidence", ""),
                "drives": fields.get("drives", ""),
                "public": public_main,
                "caveat": caveat,
            })

    return {"entries": entries, "warnings": warnings}


def render_research_section(entries: list[dict]) -> dict:
    """Render parsed evidence entries as HTML for the portfolio.

    Filters by visibility (internal entries are hidden), marks Careful entries with a caveat.

    Returns: {"html": str, "shown": [ids], "hidden_internal": [ids], "warnings": [...]}
    """
    if not entries:
        return {"html": "", "shown": [], "hidden_internal": [], "warnings": []}

    shown = []
    hidden = []
    html_parts = []

    for entry in entries:
        if entry["public"] == "Internal":
            hidden.append(entry["id"])
            continue

        shown.append(entry["id"])

        # Build HTML for this entry
        caveat_html = ""
        if entry["public"] == "Careful" and entry.get("caveat"):
            caveat_html = f' <span class="research-caveat">{entry["caveat"]}</span>'

        html_parts.append(f"""
<div class="research-entry" data-entry-id="{entry['id']}">
  <dt>{entry['id']}. {entry['title']}{caveat_html}</dt>
  <dd>{entry['took']}</dd>
</div>
""".strip())

    html = "\n".join(html_parts)
    if html:
        html = f'<dl class="research-entries">\n{html}\n</dl>'

    return {
        "html": html,
        "shown": shown,
        "hidden_internal": hidden,
        "warnings": [],
    }


def insert_or_update_section(sections: list[dict], role: str, heading: str, body_html: str,
                             template: dict | None = None) -> list[dict]:
    """Insert or update a section in the sections list.

    If a section with this role already exists, replace its heading and body_html in place.
    Otherwise append it to the end.
    """
    result = list(sections)
    for i, section in enumerate(result):
        if section.get("role") == role:
            result[i] = {"role": role, "heading": heading, "body_html": body_html}
            return result

    # Not found, append
    result.append({"role": role, "heading": heading, "body_html": body_html})
    return result


def generate(repo_path: Path | str, content_path: Path | str, template_path: Path | str | None = None) -> dict:
    """Read evidence log from repo and generate updated content JSON.

    Reads docs/research/evidence-log.md from the repo, parses it, renders the research
    section, and inserts or updates the "research" role in the content's sections list.

    Atomically writes the result back to content_path.
    """
    repo_path = Path(repo_path)
    content_path = Path(content_path)

    # Read content file
    if not content_path.exists():
        return {}

    content = json.loads(content_path.read_text())

    # Read evidence log
    evidence_log_path = repo_path / "docs" / "research" / "evidence-log.md"
    if not evidence_log_path.exists():
        return content

    log_text = evidence_log_path.read_text()
    parsed = parse_evidence_log(log_text)

    if not parsed["entries"]:
        return content

    # Render research section
    rendered = render_research_section(parsed["entries"])

    if not rendered["html"]:
        return content

    # Insert or update in sections
    sections = content.get("sections", [])
    sections = insert_or_update_section(
        sections,
        "research",
        "Research behind it",
        rendered["html"]
    )
    content["sections"] = sections

    # Atomic write
    with tempfile.NamedTemporaryFile(mode="w", dir=content_path.parent, delete=False, suffix=".json") as f:
        json.dump(content, f, indent=2)
        temp_path = f.name

    os.replace(temp_path, content_path)

    return content


def check_research_section(content: dict) -> list[dict]:
    """Check whether a content object has a research section (for portfolio_content.py integration)."""
    sections = content.get("sections", [])
    has_research = any(s.get("role") == "research" for s in sections)

    if not has_research:
        return [{
            "rule": "research-section-missing",
            "severity": "info",
            "detail": "no 'research' section; run portfolio_research.py to auto-generate from the evidence log"
        }]

    return []


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Parse evidence logs and render portfolio research sections"
    )
    parser.add_argument("repo_path", help="Path to the project repository")
    parser.add_argument("content_path", help="Path to the content JSON file")

    args = parser.parse_args()

    result = generate(args.repo_path, args.content_path)

    # Output the updated content to stdout for inspection
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
