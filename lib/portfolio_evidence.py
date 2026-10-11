#!/usr/bin/env python3
"""Research evidence logs fed to portfolio pages (ADR 0061)."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import portfolio_templates  # noqa: E402
import project_catalog  # noqa: E402


class EvidenceReadError(Exception):
    """Raised when evidence log cannot be read."""
    pass


def parse_log(text: str) -> list[dict]:
    """Parse evidence-log.md into list of entry dicts."""
    entries = []
    if not text:
        return entries

    lines = text.split('\n')
    i = 0

    while i < len(lines):
        line = lines[i]

        # Entry header: ## E<id>. <title>
        m = re.match(r'^##\s+(E\d+)\.\s+(.+?)$', line)
        if m:
            entry = {
                "id": m.group(1),
                "title": m.group(2).strip(),
                "source": "",
                "what_we_took": "",
                "drives": "",
                "public_use": "",
            }
            i += 1

            # Parse fields for this entry
            while i < len(lines):
                line = lines[i]

                # Stop at next entry
                if line.strip().startswith('##'):
                    break

                # Field line starts with - and contains colon
                if line.strip().startswith('-') and ':' in line:
                    colon_idx = line.find(':')
                    before = line[:colon_idx]
                    after = line[colon_idx + 1:].strip()

                    # Extract field name - look for words between markers
                    field_name = ""
                    for word in ["source", "what", "took", "drives", "decision", "public", "use"]:
                        if word in before.lower():
                            if word in ("source", "drives", "decision", "public"):
                                field_name = word
                                break
                            elif word == "what" or word == "took":
                                field_name = "what"
                                break

                    if field_name:
                        # Clean up after value (remove leading markdown markers)
                        after_clean = after.lstrip('*_ ')

                        # Collect continuation lines
                        value_parts = [after_clean] if after_clean else []
                        j = i + 1
                        while j < len(lines):
                            next_line = lines[j]
                            # Continuation: indented and not a new field
                            if next_line and next_line[0] in (' ', '\t') and not next_line.strip().startswith('-'):
                                value_parts.append(next_line.strip())
                                j += 1
                            else:
                                break

                        full_value = ' '.join(value_parts).strip()
                        full_value = re.sub(r'\s+', ' ', full_value)

                        # Store field
                        if field_name == "source":
                            entry["source"] = full_value
                        elif field_name == "what":
                            entry["what_we_took"] = full_value
                        elif field_name in ("drives", "decision"):
                            entry["drives"] = full_value
                        elif field_name == "public":
                            entry["public_use"] = full_value

                        i = j
                        continue

                i += 1

            entries.append(_finalize_entry(entry))
        else:
            i += 1

    return entries


def _finalize_entry(entry: dict) -> dict:
    """Normalize entry fields and extract caveat."""
    for key in ["source", "what_we_took", "drives"]:
        entry[key] = re.sub(r'\s+', ' ', (entry[key] or "").strip())

    pub = (entry.get("public_use") or "").lower().strip()
    # Remove trailing punctuation
    pub = pub.rstrip('.,:;!?')
    primary = re.split(r'\s*\(', pub)[0].strip() if pub else ""
    entry["public_use"] = primary if primary in ("yes", "careful") else "internal"

    # Extract caveat from public_use field (text in parentheses)
    caveat = ""
    if "(" in pub:
        m = re.search(r'\((.+?)\)\s*$', pub)
        if m:
            caveat = m.group(1).strip()
    entry["caveat"] = caveat

    return entry


def public_entries(entries: list[dict]) -> list[dict]:
    """Keep only yes/careful entries."""
    return [e for e in entries if e.get("public_use") in ("yes", "careful")]


def _links(text: str) -> str:
    """Convert markdown [text](url) to <a href> tags."""
    if not text:
        return text

    def replace_link(m):
        url = m.group(2)
        return f'<a href="{url}">{m.group(1)}</a>' if url.strip() else m.group(0)

    return re.sub(r'\[([^\[\]]+)\]\(([^)]*)\)', replace_link, text)


def _linked_issues(text: str, repo: str | None) -> str:
    """Convert #<number> to GitHub issue links."""
    if not text or not repo:
        return text

    def replace_issue(m):
        num = m.group(1)
        return f'<a href="https://github.com/{repo}/issues/{num}">#{num}</a>'

    return re.sub(r'(?<!\d)#(\d+)(?!\d)', replace_issue, text)


def render_entry_html(entry: dict, repo: str | None = None) -> str:
    """Render entry as HTML callout."""
    source_text = entry.get("source") or ""
    what_text = entry.get("what_we_took") or ""
    drives_text = entry.get("drives") or ""

    # Convert markdown and issue links
    source_html = _linked_issues(_links(source_text), repo)
    what_html = _linked_issues(_links(what_text), repo)
    drives_html = _linked_issues(_links(drives_text), repo)

    # Use caveat from entry (extracted during parsing) - only for careful entries
    caveat_text = ""
    if entry.get("public_use") == "careful":
        caveat_text = entry.get("caveat", "") or ""

    # Build the callout text
    parts = []
    if source_html:
        parts.append(f"<p><strong>Source:</strong> {source_html}</p>")
    if what_html:
        parts.append(f"<p><strong>What we took:</strong> {what_html}</p>")
    if drives_html:
        parts.append(f"<p><strong>Decision:</strong> {drives_html}</p>")
    if caveat_text:
        parts.append(f"<p><em>Caveat:</em> {caveat_text}</p>")

    text_html = "\n".join(parts)

    # Render through template
    result = portfolio_templates.render("longform-callout", {"TEXT_HTML": text_html})
    return result.get("html", text_html)


def research_section_html(entries: list[dict], repo: str | None = None) -> str | None:
    """Render all entries as HTML."""
    if not entries:
        return None

    rendered = [render_entry_html(e, repo) for e in entries]
    return "\n\n".join(rendered)


def research_section_for(slug: str, catalog: dict | None = None) -> dict | None:
    """Generate research section for a project."""
    if catalog is None:
        catalog = project_catalog.read_catalog(project_catalog.catalog_path())

    if not catalog or not isinstance(catalog, dict):
        return None

    # Find project
    project = next((p for p in catalog.get("projects", []) if p.get("id") == slug), None)
    if not project:
        return None

    # Resolve path - primaryPath first
    project_path = None
    if project.get("primaryPath"):
        project_path = Path(project["primaryPath"])
    elif project.get("localPaths"):
        project_path = Path(project["localPaths"][0])

    if not project_path:
        return None

    # Read and parse log
    log_path = project_path / "docs" / "research" / "evidence-log.md"
    if not log_path.exists():
        return None

    try:
        entries = parse_log(log_path.read_text())
    except OSError as e:
        raise EvidenceReadError(f"Cannot read evidence log at {log_path}: {e}")

    # Filter and render
    public = public_entries(entries)
    if not public:
        return None

    body_html = research_section_html(public, project.get("repo"))
    if not body_html:
        return None

    return {
        "heading": "Research behind it",
        "role": "research",
        "body_html": body_html,
    }


def apply(slug: str, content_path: Path | None = None, *, catalog: dict | None = None,
          author_fn=None) -> dict:
    """Upsert research section into content file."""
    # Resolve content path
    if content_path is None:
        if catalog is None:
            catalog = project_catalog.read_catalog(project_catalog.catalog_path())
        if not catalog:
            return {"updated": False, "error": "No catalog"}
        project = next((p for p in catalog.get("projects", []) if p.get("id") == slug), None)
        if not project or not project.get("primaryPath"):
            return {"updated": False, "error": "Project not found"}
        content_path = Path(project["primaryPath"]) / "content" / "longform" / f"{slug}.json"

    content_path = Path(content_path)

    # Read current content
    try:
        content = json.loads(content_path.read_text())
    except (OSError, json.JSONDecodeError) as e:
        return {"updated": False, "error": str(e)}

    # Generate new section
    try:
        section = research_section_for(slug, catalog)
    except EvidenceReadError as e:
        return {"updated": False, "error": str(e)}

    # Upsert
    sections = content.get("sections", [])
    idx = next((i for i, s in enumerate(sections) if s.get("role") == "research"), None)

    if section:
        if idx is not None:
            sections[idx] = section
        else:
            m_idx = next((i for i, s in enumerate(sections) if s.get("role") in ("built-with", "marvin")), None)
            if m_idx is not None:
                sections.insert(m_idx, section)
            else:
                sections.append(section)
    else:
        if idx is not None:
            sections.pop(idx)

    # Check if changed
    old_sections = json.loads(content_path.read_text()).get("sections", [])
    changed = len(sections) != len(old_sections) or sections != old_sections

    if changed:
        content["sections"] = sections
        content_path.write_text(json.dumps(content, indent=2, ensure_ascii=False) + "\n")
        if author_fn:
            try:
                author_fn(content_path)
            except Exception as e:
                return {"updated": True, "error": str(e)}

    return {"updated": changed}


def sync_content_file(slug: str, *, catalog: dict | None = None) -> dict:
    """Sync research section into content file without rendering author_fn."""
    if catalog is None:
        catalog = project_catalog.read_catalog(project_catalog.catalog_path())

    if not catalog:
        return {"updated": False, "error": "No catalog"}

    # Resolve content path from portfolio repo
    portfolio_path = project_catalog.portfolio_repo_path()
    content_path = portfolio_path / "content" / "longform" / f"{slug}.json"

    if not content_path.exists():
        return {"updated": False, "error": f"Content file not found: {content_path}"}

    # Use apply without author function, catch EvidenceReadError
    try:
        return apply(slug, content_path, catalog=catalog, author_fn=None)
    except EvidenceReadError as e:
        return {"updated": False, "error": str(e)}


if __name__ == "__main__":
    if len(sys.argv) >= 3:
        cmd = sys.argv[1]
        slug = sys.argv[2]
        if cmd == "apply":
            print(json.dumps(apply(slug)))
        elif cmd == "sync":
            print(json.dumps(sync_content_file(slug)))
        else:
            sys.exit(f"Unknown command: {cmd}")
    else:
        sys.exit("usage: portfolio_evidence.py [apply|sync] <slug>")
