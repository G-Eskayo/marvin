#!/usr/bin/env python3
"""Query the research-feed ChromaDB collection for cached findings.

Usage:
    ~/.agents/venv/bin/python query_research_feed.py "llm optimization"
    ~/.agents/venv/bin/python query_research_feed.py "chromadb best practices" --n 10
    ~/.agents/venv/bin/python query_research_feed.py "agent frameworks" --json
"""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

CHROMA_PATH = Path.home() / ".claude" / "chroma"
COLLECTION = "research-feed"


def query_research_feed(query: str, n: int = 5, threshold: float = 1.1) -> list[dict]:
    """Query the research-feed collection for relevant cached findings.

    Args:
        query: natural language search query
        n: number of results to return
        threshold: cosine distance threshold; results with distance >= threshold are filtered out

    Returns:
        List of matching items with title, url, source, date, published, distance.
        Returns empty list on any error (missing collection, db locked, chromadb not installed).
    """
    try:
        import chromadb
    except ImportError:
        print("[research-feed] chromadb not installed — skipping research-feed check", file=sys.stderr)
        return []

    try:
        client = chromadb.PersistentClient(path=str(CHROMA_PATH))
    except Exception:
        print("[research-feed] failed to connect to chromadb — skipping research-feed check", file=sys.stderr)
        return []

    try:
        col = client.get_or_create_collection(COLLECTION)
    except Exception:
        print(f"[research-feed] failed to get_or_create_collection({COLLECTION})", file=sys.stderr)
        return []

    if col.count() == 0:
        return []

    try:
        res = col.query(
            query_texts=[query],
            n_results=min(n, max(col.count(), 1)),
            include=["distances", "documents", "metadatas"]
        )
    except Exception:
        print("[research-feed] query failed (db locked or corrupted?) — skipping research-feed check", file=sys.stderr)
        return []

    docs = res.get("documents", [[]])[0]
    metas = res.get("metadatas", [[]])[0]
    distances = res.get("distances", [[]])[0]

    entries = []
    for doc, meta, dist in zip(docs, metas, distances):
        if dist < threshold:
            entries.append({
                "title": meta.get("title", ""),
                "url": meta.get("url", ""),
                "source": meta.get("source", ""),
                "date": meta.get("date", ""),
                "published": meta.get("published", ""),
                "distance": dist,
            })

    return entries[:n]


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Query research-feed collection for cached findings"
    )
    ap.add_argument("query", help="natural language search query")
    ap.add_argument("--n", type=int, default=5, help="number of results (default: 5)")
    ap.add_argument("--json", action="store_true", dest="as_json",
                    help="output raw JSON for sub-agent consumption")
    args = ap.parse_args()

    results = query_research_feed(args.query, n=args.n)

    if args.as_json:
        print(json.dumps(results, indent=2))
        return

    if not results:
        print(f"No cached findings in {COLLECTION}.")
        return

    print(f"research-feed: top {len(results)} cached findings for '{args.query}'\n")
    for i, r in enumerate(results, 1):
        print(f"{i}. {r['title']}")
        print(f"   url={r['url']}")
        print(f"   source={r['source']}  date={r['date']}  distance={r['distance']:.3f}")
        print()


if __name__ == "__main__":
    main()
