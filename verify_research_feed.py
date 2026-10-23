#!/usr/bin/env python3
"""Verify research-feed schema and item count via ChromaDB read-only."""

import json
import sys
from pathlib import Path

try:
    import chromadb
except ImportError:
    print("ChromaDB not installed; assuming schema from code inspection")
    sys.exit(0)

chroma_dir = Path.home() / ".claude" / "chroma"
if not chroma_dir.exists():
    print(f"ChromaDB directory not found: {chroma_dir}")
    sys.exit(0)

try:
    client = chromadb.PersistentClient(path=str(chroma_dir))
    collections = client.list_collections()

    print(f"ChromaDB collections found: {len(collections)}")
    for collection in collections:
        print(f"  - {collection.name}: {collection.count()} items")

    # Try to find research-feed collection
    research_feed = None
    for collection in collections:
        if "research" in collection.name.lower() or "feed" in collection.name.lower():
            research_feed = collection
            break

    if research_feed:
        print(f"\nResearch-feed collection: {research_feed.name}")
        print(f"Item count: {research_feed.count()}")

        # Sample a few items to see their structure
        results = research_feed.get(limit=3)
        if results and results.get('metadatas'):
            print(f"Sample metadata keys: {list(results['metadatas'][0].keys()) if results['metadatas'] else 'none'}")
    else:
        print("\nNo research-feed collection found")

except Exception as e:
    print(f"Error querying ChromaDB: {e}")
    sys.exit(1)
