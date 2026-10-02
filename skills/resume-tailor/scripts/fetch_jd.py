#!/usr/bin/env python3
"""
fetch_jd.py — fetch a job description URL and return clean plain text.
Usage: python fetch_jd.py <url>
Exits non-zero on failure so the caller knows to request a paste instead.
"""
import sys
import re
import json
from html import unescape


def _strip_html(s: str) -> str:
    s = re.sub(r"<br\s*/?>", "\n", s)
    s = re.sub(r"</p>", "\n\n", s)
    s = re.sub(r"</li>", "\n", s)
    s = re.sub(r"<li[^>]*>", "- ", s)
    s = re.sub(r"<[^>]+>", "", s)
    s = unescape(s)
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


def _collect_html_strings(node, out, min_len=200):
    """Recursively walk a JSON blob, collecting string values that look like
    rich-text job description HTML (contain tags and are reasonably long)."""
    if isinstance(node, dict):
        for v in node.values():
            _collect_html_strings(v, out, min_len)
    elif isinstance(node, list):
        for v in node:
            _collect_html_strings(v, out, min_len)
    elif isinstance(node, str):
        if len(node) >= min_len and ("<p" in node or "<li" in node or "<div" in node):
            out.append(node)


def _try_next_data(html: str) -> str | None:
    """Server-rendered React/Next.js apps (Dayforce, some Workday-alikes) ship
    the real job data as a __NEXT_DATA__ JSON blob even when the visible DOM
    is a JS-rendered shell. Pull job-description-shaped HTML out of it."""
    m = re.search(
        r'__NEXT_DATA__["\']?\s*type=["\']application/json["\']>(.*?)</script>',
        html,
        re.S,
    )
    if not m:
        return None
    try:
        data = json.loads(m.group(1))
    except json.JSONDecodeError:
        return None

    chunks: list[str] = []
    _collect_html_strings(data, chunks)
    if not chunks:
        return None

    # Longest blobs first — these are almost always the actual description
    # body rather than boilerplate nav/footer HTML also embedded in props.
    chunks.sort(key=len, reverse=True)
    text = "\n\n".join(_strip_html(c) for c in chunks[:5])
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text if len(text) >= 100 else None


def fetch(url: str) -> str:
    try:
        import requests
        from bs4 import BeautifulSoup
    except ImportError:
        print("ERROR: missing dependencies. Run: ~/.agents/venv/bin/pip install requests beautifulsoup4", file=sys.stderr)
        sys.exit(2)

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }

    try:
        resp = requests.get(url, headers=headers, timeout=15, allow_redirects=True)
        resp.raise_for_status()
    except requests.exceptions.HTTPError as e:
        print(f"ERROR: HTTP {resp.status_code} fetching {url}: {e}", file=sys.stderr)
        sys.exit(1)
    except requests.exceptions.ConnectionError:
        print(f"ERROR: could not connect to {url}", file=sys.stderr)
        sys.exit(1)
    except requests.exceptions.Timeout:
        print(f"ERROR: timed out fetching {url}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)

    soup = BeautifulSoup(resp.text, "html.parser")

    # Remove nav, footer, script, style, header elements
    for tag in soup(["script", "style", "nav", "footer", "header", "aside", "iframe", "noscript"]):
        tag.decompose()

    text = soup.get_text(separator="\n")

    # Collapse runs of blank lines
    text = re.sub(r"\n{3,}", "\n\n", text)
    # Collapse runs of spaces/tabs
    text = re.sub(r"[ \t]{2,}", " ", text)

    text = text.strip()
    if len(text) < 100:
        fallback = _try_next_data(resp.text)
        if fallback:
            return fallback
        print(f"ERROR: fetched content too short ({len(text)} chars) — page may require login or JavaScript", file=sys.stderr)
        sys.exit(1)

    return text


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: fetch_jd.py <url>", file=sys.stderr)
        sys.exit(2)
    print(fetch(sys.argv[1]))
