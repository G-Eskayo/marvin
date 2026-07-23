#!/usr/bin/env python3
"""
fetch_jd.py — fetch a job description URL and return clean plain text.
Usage: python fetch_jd.py <url>
Exits non-zero on failure so the caller knows to request a paste instead.
"""
import sys
import re

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
        print(f"ERROR: fetched content too short ({len(text)} chars) — page may require login or JavaScript", file=sys.stderr)
        sys.exit(1)

    return text


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: fetch_jd.py <url>", file=sys.stderr)
        sys.exit(2)
    print(fetch(sys.argv[1]))
