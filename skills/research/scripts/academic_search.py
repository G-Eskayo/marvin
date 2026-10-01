#!/usr/bin/env python3
"""
Academic paper search across Semantic Scholar and arXiv.

Provides a unified CLI and library interface for querying multiple academic sources
with consistent handling of network errors and rate-limiting. Reuses S2 rate-limit
backoff from s2_client.py.
"""
import argparse
import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Optional


def _get_s2_client():
    """Lazily import s2_client (allows test sys.path setup to work)."""
    sys.path.insert(0, str(Path.home() / ".agents" / "lib"))
    from s2_client import get_with_retry, S2_PAPER_BASE
    return get_with_retry, S2_PAPER_BASE


def search_semantic_scholar(query: str, limit: int = 10) -> list[dict]:
    """Search Semantic Scholar for papers matching a query.

    Args:
        query: Search query string
        limit: Maximum results to return (default 10)

    Returns:
        List of paper objects with title, authors, year, abstract, citationCount, etc.
        Returns empty list on network error (with warning to stderr).
    """
    try:
        get_with_retry, S2_PAPER_BASE = _get_s2_client()
        resp = get_with_retry(
            f"{S2_PAPER_BASE}/search",
            params={
                "query": query,
                "limit": limit,
                "fields": "title,authors,year,abstract,citationCount,externalIds,openAccessPdf,url",
            },
            timeout=15,
        )
        data = resp.json()
        return data.get("data", [])
    except Exception as e:
        print(f"[research] Semantic Scholar search failed: {e}", file=sys.stderr)
        return []


def search_arxiv(query: str, max_results: int = 10) -> list[dict]:
    """Search arXiv for papers matching a query.

    Args:
        query: Search query string
        max_results: Maximum results to return (default 10)

    Returns:
        List of paper objects with title, authors, year, summary, arxiv_id, etc.
        Returns empty list on network error (with warning to stderr).
    """
    try:
        get_with_retry, S2_PAPER_BASE = _get_s2_client()
        resp = get_with_retry(
            "https://export.arxiv.org/api/query",
            params={
                "search_query": f"all:{query}",
                "start": 0,
                "max_results": max_results,
                "sortBy": "relevance",
                "sortOrder": "descending",
            },
            timeout=15,
        )
        resp.encoding = "utf-8"
        root = ET.fromstring(resp.text)

        papers = []
        # arXiv Atom feed namespace
        ns = {"atom": "http://www.w3.org/2005/Atom"}

        for entry in root.findall("atom:entry", ns):
            arxiv_id = entry.findtext("atom:id", "", ns)
            if arxiv_id:
                arxiv_id = arxiv_id.split("/abs/")[-1]  # Extract just the ID

            authors = []
            for author in entry.findall("atom:author", ns):
                name = author.findtext("atom:name", "", ns)
                if name:
                    authors.append({"name": name})

            published = entry.findtext("atom:published", "", ns)
            year = None
            if published:
                year = int(published[:4])

            papers.append(
                {
                    "arxiv_id": arxiv_id,
                    "title": entry.findtext("atom:title", "", ns),
                    "authors": authors,
                    "year": year,
                    "summary": entry.findtext("atom:summary", "", ns),
                    "url": f"https://arxiv.org/abs/{arxiv_id}" if arxiv_id else None,
                }
            )

        return papers
    except Exception as e:
        print(f"[research] arXiv search failed: {e}", file=sys.stderr)
        return []


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Search academic papers across Semantic Scholar and arXiv."
    )
    ap.add_argument("--query", required=True, help="Search query")
    ap.add_argument(
        "--source",
        choices=["semantic-scholar", "arxiv", "both"],
        default="both",
        help="Search source (default: both)",
    )
    ap.add_argument("--limit", type=int, default=10, help="Max results per source (default: 10)")
    ap.add_argument(
        "--format",
        choices=["json", "markdown"],
        default="json",
        help="Output format (default: json)",
    )
    args = ap.parse_args()

    results = {}

    if args.source in ("semantic-scholar", "both"):
        results["semantic_scholar"] = search_semantic_scholar(args.query, args.limit)

    if args.source in ("arxiv", "both"):
        results["arxiv"] = search_arxiv(args.query, args.limit)

    if args.format == "json":
        print(json.dumps(results, indent=2))
    elif args.format == "markdown":
        _print_markdown(results, args.source)


def _print_markdown(results: dict, source: str) -> None:
    """Print search results in markdown format."""
    if source in ("semantic-scholar", "both") and results.get("semantic_scholar"):
        print("## Semantic Scholar Results\n")
        for paper in results["semantic_scholar"]:
            title = paper.get("title", "Unknown")
            url = paper.get("url", "")
            authors = paper.get("authors", [])
            author_names = ", ".join(a.get("name", "") for a in authors) if authors else "Unknown"
            year = paper.get("year", "")
            abstract = paper.get("abstract", "")

            print(f"### {title}")
            if url:
                print(f"[Link]({url})")
            print(f"- **Authors:** {author_names}")
            if year:
                print(f"- **Year:** {year}")
            if abstract:
                print(f"- **Abstract:** {abstract[:200]}...")
            print()

    if source in ("arxiv", "both") and results.get("arxiv"):
        print("## arXiv Results\n")
        for paper in results["arxiv"]:
            title = paper.get("title", "Unknown")
            url = paper.get("url", "")
            authors = paper.get("authors", [])
            author_names = ", ".join(a.get("name", "") for a in authors) if authors else "Unknown"
            year = paper.get("year", "")
            summary = paper.get("summary", "")

            print(f"### {title}")
            if url:
                print(f"[Link]({url})")
            print(f"- **Authors:** {author_names}")
            if year:
                print(f"- **Year:** {year}")
            if summary:
                print(f"- **Summary:** {summary[:200]}...")
            print()


if __name__ == "__main__":
    main()
