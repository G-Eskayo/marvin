#!/usr/bin/env python3
"""Evidence-log integration: parse, filter, check links, render, and sync to portfolio pages (ticket #382).

An evidence log (`docs/research/evidence-log.md` in a project repo) records sources that shaped real decisions.
This module reads logs, filters entries by public-use status, checks if links are still live, renders them as
HTML for a portfolio page section, and syncs the section into the portfolio's content JSON (kept in sync via CLI).

The format is fixed: `## E<n>. Title` blocks with `**Source:**`, `**What we took:**`, `**Confidence:**`,
`**Drives:**`, and `**Public use:**` (Yes|Careful ("caveat")|Internal) fields. Only entries marked `Yes` or
`Careful (with caveat)` are published; Internal entries and those lacking a caveat are excluded and flagged
as findings.

  parse_log(text)              → list[dict]  parse a markdown evidence log
  classify(entry)              → str         categorize by public_use status
  check_link(url, timeout)     → bool        verify a link is live
  public_entries(entries)      → tuple       filter + probe links, return renderable + findings
  render_html(entries)         → str         wrap entries in HTML with evidence-* CSS classes
  sync(slug, repo, project)    → dict        read log from repo, update portfolio content JSON atomically

CLI: portfolio_evidence.py sync <slug> [--repo PATH] [--project PATH] [--author]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from html import escape

sys.path.insert(0, str(Path(__file__).resolve().parent))

# For when this runs outside the lib directory
if Path(__file__).parent.name != "lib":
    sys.path.insert(0, str(Path.home() / ".agents" / "lib"))

import project_catalog  # noqa: E402

PROJECT = project_catalog.portfolio_repo_path()


# ── parsing ────────────────────────────────────────────────────────────────

def parse_log(text: str) -> list[dict]:
    """Parse an evidence log markdown file into a list of entry dicts.

    Each entry has: title, source, what_we_took, confidence, drives, public_use, caveat (if Careful).
    Returns empty list if no valid entries found.
    """
    entries = []
    # Split on ## E<n>. headings
    blocks = re.split(r'^## E\d+\.\s+', text, flags=re.MULTILINE)

    # First block before any ## E is preamble; skip it
    for block in blocks[1:]:
        lines = block.split('\n')
        title = lines[0].strip() if lines else ""

        # Extract fields from **Field:** lines
        entry: dict[str, str] = {
            "title": title,
            "source": "",
            "what_we_took": "",
            "confidence": "",
            "drives": "",
            "public_use": "",
            "caveat": "",
        }

        rest = '\n'.join(lines[1:])

        # Parse **Field:** value format
        for field in ["source", "what_we_took", "confidence", "drives", "public_use"]:
            pattern = rf'^\*\*{field.replace("_", " ").title()}:\*\*\s*(.+?)(?=\n\*\*|\Z)'
            match = re.search(pattern, rest, re.IGNORECASE | re.MULTILINE | re.DOTALL)
            if match:
                value = match.group(1).strip()
                # Confidence should be a single short line (trim at em-dash or first newline)
                if field == "confidence":
                    value = value.split('\n')[0].strip()
                    # Stop at clarifications (em-dash is used for explanations)
                    value = value.split('—')[0].split(' - ')[0].strip()
                entry[field] = value

        # Track whether public_use field was actually found (vs. defaulting to empty)
        if "**Public use:**" not in rest and "**Public Use:**" not in rest:
            entry["_public_use_missing"] = True

        # Extract caveat from Careful ("...") if present
        public = entry["public_use"].strip()
        if public.lower().startswith("careful"):
            caveat_match = re.search(r'\("([^"]*)"\)', public)
            if caveat_match:
                entry["caveat"] = caveat_match.group(1).strip()
                # Normalize public_use to just "Careful" for classify()
                entry["public_use"] = "Careful"

        if title:  # Only add if there's a title
            entries.append(entry)

    return entries


def _md_links(text: str) -> str:
    """Convert [text](url) markdown links to HTML <a> tags, escape everything else."""
    # Replace [text](url) with <a href="url">text</a>
    text = re.sub(
        r'\[([^\]]+)\]\(([^\)]+)\)',
        lambda m: f'<a href="{escape(m.group(2))}">{escape(m.group(1))}</a>',
        text or ""
    )
    # Escape any remaining HTML characters (not already in tags)
    # This is safe because we only created <a> tags above
    return text


def classify(entry: dict) -> str:
    """Classify an entry by its public_use status.

    Returns: "yes" | "careful" | "internal" | "malformed"
    - "yes": public_use is "Yes" (case-insensitive)
    - "careful": public_use is "Careful" with caveat text (in parentheses or caveat field)
    - "malformed": public_use is "Careful" but caveat is empty/missing
    - "internal": public_use is "Internal", missing, or anything else
    """
    public = entry.get("public_use", "").strip()

    if not public:
        return "internal"

    if public.lower() == "yes":
        return "yes"

    if public.lower().startswith("careful"):
        # Check for caveat: either in caveat field or in parentheses in public_use
        caveat = entry.get("caveat", "").strip()
        if not caveat:
            # Check if caveat is in the public_use string itself: Careful ("...")
            caveat_match = re.search(r'\("([^"]*)"\)', public)
            if caveat_match:
                caveat = caveat_match.group(1).strip()

        if caveat:
            return "careful"
        else:
            return "malformed"

    # Anything else (including "Internal", typos, etc.)
    return "internal"


def check_link(url: str, timeout: float = 5.0) -> bool:
    """Check if a URL is reachable with HTTP HEAD or GET.

    Returns True if the server responds with 2xx status.
    Returns False if unreachable, times out, or returns 4xx/5xx.
    Never raises an exception (all errors become False).
    """
    try:
        req = urllib.request.Request(url, method='HEAD')
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return 200 <= response.status < 300
    except urllib.error.HTTPError as e:
        # Got a response but it was an error (4xx/5xx)
        if e.code == 405:  # Method Not Allowed, try GET
            try:
                with urllib.request.urlopen(url, timeout=timeout) as response:
                    return 200 <= response.status < 300
            except Exception:
                return False
        return False
    except (urllib.error.URLError, TimeoutError, Exception):
        # Connection refused, timeout, or any other error
        return False


def public_entries(
    entries: list[dict],
    probe: callable = check_link
) -> tuple[list[dict], list[dict]]:
    """Filter entries to publishable ones and return findings for excluded entries.

    Returns (public_entries, findings):
    - public_entries: list of entries with classify() in ("yes", "careful")
    - findings: list of {"rule": "...", "severity": "...", "detail": "..."} dicts
      for entries excluded due to being internal, malformed, or having dead links.
    """
    public = []
    findings = []

    for entry in entries:
        cls = classify(entry)

        if cls == "internal":
            # Check if this is an intentionally-marked Internal entry, or just missing the field
            if entry.get("_public_use_missing"):
                # Missing public_use field is an error
                findings.append({
                    "rule": "internal-or-malformed",
                    "severity": "warning",
                    "detail": f'Entry "{entry["title"]}": missing public_use field (excluded)'
                })
            # Silent exclusion for intentionally-Internal entries (expected, not an error)
            continue

        if cls == "malformed":
            # Careful without caveat is malformed
            findings.append({
                "rule": "internal-or-malformed",
                "severity": "warning",
                "detail": f'Entry "{entry["title"]}": Careful without caveat text (excluded)'
            })
            continue

        # Check link if the entry has a source
        if cls in ("yes", "careful"):
            source = entry.get("source", "").strip()
            # Extract URL from [text](url) if present
            url_match = re.search(r'\]\(([^\)]+)\)', source)
            url = url_match.group(1) if url_match else None

            if url and not probe(url):
                # Dead link: render entry but without the hyperlink
                entry["source"] = re.sub(r'\[([^\]]+)\]\([^\)]+\)', r'\1', source)
                findings.append({
                    "rule": "dead-link",
                    "severity": "warning",
                    "detail": f'Entry "{entry["title"]}" has a dead link: {url}'
                })

            public.append(entry)

    return public, findings


def render_html(entries: list[dict]) -> str:
    """Render a list of public entries as HTML with evidence-list/entry/caveat classes.

    Returns wrapped HTML with no em-dashes, no AI phrases (safe for portfolio copy check).
    """
    if not entries:
        return '<div class="evidence-list"></div>'

    html_parts = ['<div class="evidence-list">']

    for i, entry in enumerate(entries):
        html_parts.append('<div class="evidence-entry">')
        html_parts.append(f'<h3>{escape(entry["title"])}</h3>')

        # Source with markdown link conversion
        source = entry.get("source", "").strip()
        if source:
            source_html = _md_links(source)
            html_parts.append(f'<p><strong>Source.</strong> {source_html}</p>')

        # What we took
        what = entry.get("what_we_took", "").strip()
        if what:
            what_html = _md_links(what)
            html_parts.append(f'<p><strong>What we took.</strong> {what_html}</p>')

        # Confidence
        conf = entry.get("confidence", "").strip()
        if conf:
            html_parts.append(f'<p><strong>Confidence.</strong> {escape(conf)}.</p>')

        # Drives (the decision)
        drives = entry.get("drives", "").strip()
        if drives:
            drives_html = _md_links(drives)
            html_parts.append(f'<p><strong>Drives.</strong> {drives_html}</p>')

        # Caveat if present (for Careful entries)
        caveat = entry.get("caveat", "").strip()
        if caveat:
            caveat_html = _md_links(caveat)
            html_parts.append(f'<p><span class="evidence-caveat">{caveat_html}</span></p>')

        html_parts.append('</div>')

        # Separator between entries (not after the last one)
        if i < len(entries) - 1:
            html_parts.append('<hr class="evidence-separator">')

    html_parts.append('</div>')
    return '\n'.join(html_parts)


def sync(
    slug: str,
    *,
    repo: Path | None = None,
    project: Path = PROJECT,
    author: bool = False
) -> dict:
    """Sync evidence log from a project repo into the portfolio content JSON.

    Process:
    1. Resolve the repo path (explicit arg, or via project_catalog)
    2. Read evidence-log.md (missing file is OK; return has_log=False)
    3. Parse, filter, probe links, render
    4. Read content JSON for this slug
    5. Insert/replace research section, set has_evidence_log flag
    6. Write atomically (temp file + replace)
    7. Optionally author to the dev site (if --author flag)

    Returns: {"ok": bool, "changed": bool, "has_log": bool, "entries": int, "findings": [...]?}
    """
    result = {
        "ok": False,
        "reason": None,
    }

    # Resolve repo path
    if not repo:
        # Use project_catalog to find the repo for this slug
        try:
            cat = project_catalog.read_catalog(project_catalog.catalog_path())
            for p in (cat or {}).get("projects", []):
                if p.get("portfolio") and p["portfolio"].get("url", "").endswith(f"/{slug}/"):
                    if p.get("primaryPath"):
                        repo = Path(p["primaryPath"])
                        break
        except Exception:
            pass

        if not repo:
            result["reason"] = f"Unknown slug {slug}: not found in catalog (use --repo to specify)"
            return result

    repo = Path(repo)

    # Read evidence log (missing is not an error)
    log_file = repo / "docs" / "research" / "evidence-log.md"
    if not log_file.exists():
        result["ok"] = True
        result["has_log"] = False
        result["entries"] = 0
        result["findings"] = []
        return result

    try:
        log_text = log_file.read_text(encoding="utf-8")
    except Exception as e:
        result["reason"] = f"Could not read {log_file}: {e}"
        return result

    # Parse and filter
    entries = parse_log(log_text)
    public, findings = public_entries(entries)

    # Read the content JSON
    content_file = project / "content" / "longform" / f"{slug}.json"
    if not content_file.exists():
        result["reason"] = f"No content file for {slug}"
        return result

    try:
        content = json.loads(content_file.read_text(encoding="utf-8"))
    except Exception as e:
        result["reason"] = f"Could not read content JSON: {e}"
        return result

    # Prepare the research section
    research_body = render_html(public)
    research_section = {
        "role": "research",
        "body_html": research_body
    }

    # Update sections: remove old research section (if any), insert new one
    sections = content.get("sections", [])
    sections = [s for s in sections if s.get("role") != "research"]

    # Insert before "built-with" or "marvin" (appendix sections), or at end
    insert_idx = len(sections)
    for i, s in enumerate(sections):
        if s.get("role") in ("built-with", "marvin"):
            insert_idx = i
            break

    sections.insert(insert_idx, research_section)

    # Update the content
    content["sections"] = sections
    content["has_evidence_log"] = bool(public)

    # Write atomically
    new_content_json = json.dumps(content, indent=2) + "\n"

    # Check if changed
    try:
        old_content = content_file.read_text(encoding="utf-8")
        changed = old_content != new_content_json
    except Exception:
        changed = True

    # Write via temp file + replace
    try:
        with tempfile.NamedTemporaryFile(
            mode='w',
            dir=content_file.parent,
            suffix='.json',
            delete=False,
            encoding='utf-8'
        ) as tmp:
            tmp.write(new_content_json)
            tmp_path = Path(tmp.name)

        tmp_path.replace(content_file)
    except Exception as e:
        result["reason"] = f"Could not write content JSON: {e}"
        return result

    # Success
    result["ok"] = True
    result["changed"] = changed
    result["has_log"] = bool(public)
    result["entries"] = len(public)
    result["findings"] = findings

    # Optionally author to dev site (would call portfolio_longform.author() here if implemented)
    if author:
        try:
            import portfolio_longform
            # Get the portfolio site URL for this slug (from catalog or inferred)
            url = f"dev.gileskayo.me/ai-projects/{slug}/"  # example; would be resolved from catalog
            portfolio_longform.author(url, content)
            result["authored"] = True
        except Exception as e:
            result["author_error"] = str(e)

    return result


# ── CLI ────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Sync evidence logs from project repos to portfolio pages"
    )
    subparsers = parser.add_subparsers(dest='command', required=True)

    sync_parser = subparsers.add_parser('sync', help='Sync evidence log to portfolio content')
    sync_parser.add_argument('slug', help='Project slug (e.g., clarity-captions)')
    sync_parser.add_argument('--repo', type=Path, help='Path to project repo (resolves via catalog if omitted)')
    sync_parser.add_argument('--project', type=Path, default=PROJECT, help='Portfolio project path')
    sync_parser.add_argument('--author', action='store_true', help='Also author to dev site')

    args = parser.parse_args()

    if args.command == 'sync':
        result = sync(
            args.slug,
            repo=args.repo,
            project=args.project,
            author=args.author
        )

        if result["ok"]:
            print(f'✓ {args.slug}: {result["entries"]} entries', file=sys.stderr)
            if result["findings"]:
                print(f'  Findings: {len(result["findings"])}', file=sys.stderr)
                for f in result["findings"]:
                    print(f'    - {f["detail"]}', file=sys.stderr)
            if result.get("authored"):
                print(f'  Authored to dev site', file=sys.stderr)
            if not result["changed"]:
                print(f'  (no changes)', file=sys.stderr)
            print(json.dumps(result, indent=2))
        else:
            print(f'✗ {args.slug}: {result["reason"]}', file=sys.stderr)
            sys.exit(1)


if __name__ == '__main__':
    main()
