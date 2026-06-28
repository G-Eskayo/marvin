#!/usr/bin/env python3
"""Query the qa-knowledge ChromaDB collection.

Usage:
    ~/.agents/venv/bin/python qa_query.py "chromadb best practices"
    ~/.agents/venv/bin/python qa_query.py "python async" --n 10
    ~/.agents/venv/bin/python qa_query.py "what failed" --category failed
    ~/.agents/venv/bin/python qa_query.py "react hooks" --json
"""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

CHROMA_PATH = Path.home() / ".claude" / "chroma"
COLLECTION  = "qa-knowledge"


def filter_results(results: list[dict], category: str | None) -> list[dict]:
    if not category:
        return results
    return [r for r in results if r.get("metadata", {}).get("category") == category]


def query_kb(query: str, n: int = 5, category: str | None = None) -> list[dict]:
    import chromadb
    client = chromadb.PersistentClient(path=str(CHROMA_PATH))
    try:
        col = client.get_collection(COLLECTION)
    except Exception:
        return []

    # fetch more than needed to allow post-filter
    fetch_n = n * 4 if category else n
    res = col.query(query_texts=[query], n_results=min(fetch_n, max(col.count(), 1)))

    docs      = res["documents"][0]
    metas     = res["metadatas"][0]
    distances = res["distances"][0]

    entries = [
        {"document": d, "metadata": m, "distance": dist}
        for d, m, dist in zip(docs, metas, distances)
    ]
    entries = filter_results(entries, category)
    return entries[:n]


def main() -> None:
    ap = argparse.ArgumentParser(description="Query qa-knowledge")
    ap.add_argument("query",      help="natural language search query")
    ap.add_argument("--n",        type=int, default=5, help="number of results")
    ap.add_argument("--category", default=None,
                    help="filter by category (pattern|anti-pattern|library|tool|worked|failed|config)")
    ap.add_argument("--json",     action="store_true", dest="as_json",
                    help="output raw JSON for sub-agent consumption")
    args = ap.parse_args()

    results = query_kb(args.query, n=args.n, category=args.category)

    if args.as_json:
        print(json.dumps(results, indent=2))
        return

    if not results:
        print(f"No results found in {COLLECTION}. Run qa_scan.py on a project first.")
        return

    print(f"qa-knowledge: top {len(results)} results for '{args.query}'\n")
    for i, r in enumerate(results, 1):
        m = r["metadata"]
        tags = f"  [{m.get('tags','').replace(',', ', ')}]" if m.get("tags") else ""
        print(f"{i}. [{m.get('category','?')}] {r['document']}")
        relevance = 1 / (1 + r["distance"])  # L2→0-1, higher=better
        print(f"   project={m.get('project','?')}  confidence={m.get('confidence','?')}"
              f"  relevance={relevance:.2f}{tags}")
        print()


if __name__ == "__main__":
    main()
