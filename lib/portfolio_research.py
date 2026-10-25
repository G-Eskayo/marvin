#!/usr/bin/env python3
"""Parse, filter and render evidence logs for portfolio projects (ADR 0051).

An evidence log is a markdown file (`docs/research/evidence-log.md`) with entries like:

  ## E1: Description
  **Source:** [link](url)
  **What we took:** details
  **Drives:** decision details
  **Public use:** Yes

  ## E2: Description
  **Source:** [link](url)
  **What we took:** details
  **Drives:** decision details
  **Public use:** Careful (caveat about what to note)

Entries are parsed and returned with fields as None if missing. The publishable() function filters
by `Public use` flag: Yes/Careful entries are kept; Internal/missing are dropped. render_entry()
excludes entries missing any of source/what_we_took/drives. Rendered entries are HTML-escaped,
with inline `**bold**` → `<strong>` and `[text](url)` → `<a href>`.
The result becomes the `research` role's `body_html` in the project's content file.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
import project_catalog  # noqa: E402


def parse_log(markdown: str) -> list[dict]:
    """Parse an evidence log markdown file into structured entries.

    Returns list of dicts with keys:
      - number: e.g. 1 for E1
      - title: section heading text after "E#:" or "E#."
      - source: markdown link text (may contain multiple links), or None if missing
      - what_we_took: from "What we took:" bullet, or None if missing
      - drives: from "Drives:" bullet, or None if missing
      - public_use: "Yes", "Careful", or "Internal" (defaults to Internal if missing)
      - caveat: quoted text from "Careful (...)" if present, else None

    All entries found are returned, including those missing required fields (with None values).
    Incomplete entries are excluded at render time (by render_entry guard).
    Continuation lines are joined into the same field.
    """
    entries = []

    if not markdown or not markdown.strip():
        return entries

    # Split by ## E<n>: or ## E<n>. headers (period or colon)
    pattern = r'^##\s+E(\d+)[:.]\s*(.+)$'
    blocks = re.split(pattern, markdown, flags=re.MULTILINE)

    # blocks[0] is pre-header content (discard), then triplets (num, title, body)
    for i in range(1, len(blocks), 3):
        if i + 2 >= len(blocks):
            break

        try:
            num = int(blocks[i])
        except ValueError:
            continue

        title = blocks[i + 1].strip()
        body = blocks[i + 2]

        entry = {
            'number': num,
            'title': title,
            'source': None,
            'what_we_took': None,
            'drives': None,
            'public_use': 'Internal',  # Default to Internal
            'caveat': None,
        }

        # Parse bullets: **Key:** value, allowing continuation lines
        # Optional list marker: - **Key:**
        lines = body.split('\n')
        current_key = None
        current_value = []
        bullets = {}

        for line in lines:
            # Match a bullet: optional "- " then **Key:** value (colon is before closing **)
            # Pattern: optional "- " + ** + key + : + ** + space + value
            match = re.match(r'^\s*-?\s*\*\*([^*:]+):\*\*\s+(.*)', line)
            if match:
                # Save previous bullet if any
                if current_key:
                    bullets[current_key] = '\n'.join(current_value).strip()
                current_key = match.group(1).strip()
                current_value = [match.group(2)] if match.group(2) else []
            elif current_key and line.strip():
                # Continuation line (for wrapped bullets)
                current_value.append(line.strip())

        # Save last bullet
        if current_key:
            bullets[current_key] = '\n'.join(current_value).strip()

        # Extract fields
        entry['source'] = bullets.get('Source')
        entry['what_we_took'] = bullets.get('What we took')
        entry['drives'] = bullets.get('Drives')

        # Parse Public use flag and caveat
        public_use_text = bullets.get('Public use', '').strip()
        if public_use_text.startswith('Yes'):
            entry['public_use'] = 'Yes'
        elif public_use_text.startswith('Careful'):
            entry['public_use'] = 'Careful'
            # Extract caveat: text in parentheses after Careful
            caveat_match = re.search(r'Careful\s*\(([^)]+)\)', public_use_text)
            if caveat_match:
                entry['caveat'] = caveat_match.group(1)
        elif public_use_text.startswith('Internal'):
            entry['public_use'] = 'Internal'
        elif public_use_text:
            # Malformed value, treat as Internal
            entry['public_use'] = 'Internal'
        # else: missing flag, already defaulted to Internal above

        entries.append(entry)

    return entries


def publishable(entries: list[dict]) -> list[dict]:
    """Filter entries to keep only Yes/Careful (drop Internal and missing-flag).

    Caveats from Careful entries are preserved.
    """
    return [e for e in entries if e.get('public_use') in ('Yes', 'Careful')]


def _escape_html(text: str) -> str:
    """HTML-escape text."""
    if not text:
        return text
    return (text
            .replace('&', '&amp;')
            .replace('<', '&lt;')
            .replace('>', '&gt;')
            .replace('"', '&quot;')
            .replace("'", '&#39;'))


def _convert_markdown_inline(text: str) -> str:
    """Convert inline markdown to HTML: **bold** → <strong>, [text](url) → <a href>.

    Only http/https URLs are converted; other URLs are left as text.
    Text is HTML-escaped before conversion.
    """
    if not text:
        return text

    # Walk raw text with re.finditer to find all [text](url) patterns,
    # escaping literal segments and assembling links exactly once.
    result = []
    last_end = 0

    for match in re.finditer(r'\[([^\]]+)\]\(([^)]+)\)', text):
        # Escape the literal segment before this link
        literal = text[last_end:match.start()]
        result.append(_escape_html(literal))

        # Process the link
        link_text = match.group(1)
        url = match.group(2)
        if url.startswith(('http://', 'https://')):
            result.append(f'<a href="{_escape_html(url)}">{_escape_html(link_text)}</a>')
        else:
            # Invalid or unsafe URL, return escaped text only
            result.append(_escape_html(link_text))

        last_end = match.end()

    # Escape any remaining literal text after the last link
    result.append(_escape_html(text[last_end:]))
    text = ''.join(result)

    # Convert **bold** to <strong>, but only if it has matching pairs
    text = re.sub(r'\*\*([^*]+)\*\*', r'<strong>\1</strong>', text)

    return text


def render_entry(entry: dict) -> str:
    """Render a single entry to HTML.

    Entry dict should have source, what_we_took, drives, public_use, caveat keys.
    Returns HTML string wrapped in class="longform-callout", or "" if any required field is missing.
    """
    if not (entry.get('source') and entry.get('what_we_took') and entry.get('drives')):
        return ""

    parts = []

    # Source
    source_html = _convert_markdown_inline(entry['source'])
    parts.append(f"<p><strong>Source:</strong> {source_html}</p>")

    # What we took
    took_html = _convert_markdown_inline(entry['what_we_took'])
    parts.append(f"<p><strong>What we took:</strong> {took_html}</p>")

    # Drives
    drives_html = _convert_markdown_inline(entry['drives'])
    parts.append(f"<p><strong>Drives:</strong> {drives_html}</p>")

    # Caveat for Careful entries
    if entry.get('public_use') == 'Careful' and entry.get('caveat'):
        caveat_html = _convert_markdown_inline(entry['caveat'])
        parts.append(f"<p><em>Caveat: {caveat_html}</em></p>")

    html = '\n'.join(parts)
    return f'<div class="longform-callout">\n{html}\n</div>'


def render_section(entries: list[dict]) -> Optional[dict]:
    """Render publishable entries into a research section dict, or None if no entries.

    Returns a dict with role, body_html keys suitable for adding to a content file's sections.
    """
    if not entries:
        return None

    entry_htmls = []
    for e in entries:
        html = render_entry(e)
        if html:
            entry_htmls.append(html)

    if not entry_htmls:
        return None

    body_html = '\n\n'.join(entry_htmls)

    return {
        'role': 'research',
        'body_html': body_html,
    }


def section_for_project(source_repo: str) -> Optional[dict]:
    """Build a research section for a project, or None if no evidence log exists.

    Args:
        source_repo: path to the project repo (e.g. ~/Developer/clarity-captions)

    Returns:
        A section dict with role/body_html, or None.

    Raises:
        RuntimeError: if the log file is unreadable (permission, decode, etc.)
    """
    source_path = Path(source_repo).expanduser()
    log_path = source_path / 'docs' / 'research' / 'evidence-log.md'

    if not log_path.exists():
        return None

    try:
        markdown = log_path.read_text(encoding='utf-8')
    except FileNotFoundError:
        return None
    except (OSError, UnicodeDecodeError) as e:
        raise RuntimeError(f"Cannot read evidence log at {log_path}: {e}") from e

    entries = parse_log(markdown)
    published = publishable(entries)
    return render_section(published)


def insert_or_update_section(content: dict, template: dict, section: Optional[dict]) -> dict:
    """Insert, update or remove a research section in a content dict, respecting template order.

    Args:
        content: the project's content dict (has sections list)
        template: the content template dict (defines role order)
        section: the new section dict (with role/body_html), or None to remove

    Returns:
        Updated content dict (same object, mutated in-place).
    """
    sections = content.get('sections') or []

    # Find role order from template
    template_roles = [s.get('role') for s in template.get('sections', [])]

    # Remove existing research section if present
    content['sections'] = [s for s in sections if s.get('role') != 'research']

    # If no new section, we're done (removal case)
    if section is None:
        return content

    # Insert at the correct position based on template order
    if 'research' not in template_roles:
        # Template doesn't declare research, append at end
        content['sections'].append(section)
        return content

    target_index = template_roles.index('research')

    # Find insertion point: after the last section whose role appears before 'research' in template
    insert_pos = 0
    for i, s in enumerate(content['sections']):
        role = s.get('role')
        if role in template_roles and template_roles.index(role) < target_index:
            insert_pos = i + 1

    content['sections'].insert(insert_pos, section)
    return content


def update_project_content(content_path: Path, template_path: Path, source_repo: str) -> bool:
    """Atomically update a project's content file with its research section.

    Reads the evidence log from source_repo, builds the research section, and updates
    content_path to match. If the log has no publishable entries, removes the research section.

    Writes atomically: creates a temp file, validates it, then replaces the original.

    Args:
        content_path: path to content/longform/<slug>.json
        template_path: path to templates/content/<type>.json
        source_repo: path to the source project repo

    Returns:
        True if changed, False if no changes.

    Raises:
        RuntimeError: if the content/template files are unreadable or the write fails.
    """
    try:
        # Load content and template
        content = json.loads(content_path.read_text(encoding='utf-8'))
        template = json.loads(template_path.read_text(encoding='utf-8'))

        # Build new section
        section = section_for_project(source_repo)

        # Update content
        original_json = json.dumps(content, indent=2, ensure_ascii=False)
        insert_or_update_section(content, template, section)
        updated_json = json.dumps(content, indent=2, ensure_ascii=False)

        # Check if changed
        if original_json == updated_json:
            return False

        # Write atomically
        temp_path = content_path.with_suffix('.tmp')
        try:
            temp_path.write_text(updated_json + '\n', encoding='utf-8')
            temp_path.replace(content_path)
        finally:
            if temp_path.exists():
                temp_path.unlink()

        return True

    except Exception as e:
        raise RuntimeError(f"Failed to update {content_path}: {e}") from e


def main() -> None:
    """CLI: update a project's research section in its content file."""
    import argparse

    parser = argparse.ArgumentParser(description='Update portfolio research sections from evidence logs')
    parser.add_argument('--content', type=Path, help='Path to content/longform/<slug>.json')
    parser.add_argument('--source-repo', help='Path to the project repo')
    parser.add_argument('--project', help='Project slug (looks up content/source-repo paths)')
    parser.add_argument('--plan', action='store_true', help='Plan only, do not write')

    args = parser.parse_args()

    # Resolve paths
    if args.project:
        catalog_data = project_catalog.read_catalog(project_catalog.catalog_path()) or {}
        projects = catalog_data.get('projects', [])
        project_entry = next((p for p in projects if p.get('slug') == args.project), None)
        if not project_entry:
            print(f"Project '{args.project}' not found in catalog", file=sys.stderr)
            sys.exit(1)
        source_repo = project_entry.get('source_repo') or project_entry.get('repo')
        if not source_repo:
            print(f"Project '{args.project}' has no source_repo in catalog", file=sys.stderr)
            sys.exit(1)
    else:
        source_repo = args.source_repo

    if not args.content:
        print("--content path required", file=sys.stderr)
        sys.exit(1)

    if not source_repo:
        print("--source-repo required or --project must have catalog entry", file=sys.stderr)
        sys.exit(1)

    content_path = Path(args.content)
    portfolio = project_catalog.portfolio_repo_path()

    try:
        content_data = json.loads(content_path.read_text(encoding='utf-8'))
    except FileNotFoundError:
        print(f"Content file not found: {content_path}", file=sys.stderr)
        sys.exit(1)
    except (OSError, json.JSONDecodeError) as e:
        print(f"Cannot read or parse content file {content_path}: {e}", file=sys.stderr)
        sys.exit(1)

    template_type = content_data.get('content_type')
    if not template_type:
        print("Content file must have a 'content_type' field", file=sys.stderr)
        sys.exit(1)

    template_path = portfolio / 'templates' / 'content' / f'{template_type}.json'

    if not template_path.exists():
        print(f"Template not found: {template_path}", file=sys.stderr)
        sys.exit(1)

    if args.plan:
        section = section_for_project(source_repo)
        if section:
            print(json.dumps(section, indent=2))
        else:
            print("No publishable entries found")
    else:
        try:
            changed = update_project_content(content_path, template_path, source_repo)
            if changed:
                print(f"Updated {content_path}")
            else:
                print(f"No changes to {content_path}")
        except Exception as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)


if __name__ == "__main__":
    main()
