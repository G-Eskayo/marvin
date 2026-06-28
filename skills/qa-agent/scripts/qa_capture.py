#!/usr/bin/env python3
"""Manually capture a pattern or learning into the qa-knowledge ChromaDB collection.

Usage:
    ~/.agents/venv/bin/python qa_capture.py \
        --content "Always use PersistentClient for ChromaDB" \
        --category anti-pattern \
        --library chromadb \
        --tags "chromadb,persistence" \
        --confidence high
"""
from __future__ import annotations
import argparse
import hashlib
import sys
from datetime import datetime, timezone
from pathlib import Path

CHROMA_PATH = Path.home() / ".claude" / "chroma"
COLLECTION  = "qa-knowledge"
VALID_CATEGORIES = {"pattern", "anti-pattern", "library", "tool", "worked", "failed", "config"}


def build_entry(
    content: str,
    category: str,
    *,
    library: str = "",
    tags: str = "",
    confidence: str = "medium",
    project: str = "manual",
    language: str = "all",
    source: str = "manual",
) -> dict:
    entry_id = "qa-" + hashlib.sha256(content.encode()).hexdigest()[:16]
    return {
        "id": entry_id,
        "document": content,
        "metadata": {
            "category": category,
            "source": source,
            "project": project,
            "language": language,
            "library": library,
            "tags": tags,
            "confidence": confidence,
            "created_at": datetime.now(timezone.utc).isoformat(),
        },
    }


def store_entry(entry: dict) -> bool:
    """Return True if new, False if already existed (dedup by id)."""
    import chromadb
    client = chromadb.PersistentClient(path=str(CHROMA_PATH))
    col = client.get_or_create_collection(COLLECTION)
    existing = set(col.get()["ids"])
    if entry["id"] in existing:
        return False
    col.add(
        documents=[entry["document"]],
        metadatas=[entry["metadata"]],
        ids=[entry["id"]],
    )
    return True


def main() -> None:
    ap = argparse.ArgumentParser(description="Capture a pattern into qa-knowledge")
    ap.add_argument("--content",    required=True, help="description of the pattern/practice")
    ap.add_argument("--category",   required=True, choices=sorted(VALID_CATEGORIES))
    ap.add_argument("--library",    default="",    help="library name if applicable")
    ap.add_argument("--tags",       default="",    help="comma-separated tags")
    ap.add_argument("--confidence", default="medium", choices=["high", "medium", "low"])
    ap.add_argument("--project",    default="manual")
    ap.add_argument("--language",   default="all")
    args = ap.parse_args()

    entry = build_entry(
        content=args.content,
        category=args.category,
        library=args.library,
        tags=args.tags,
        confidence=args.confidence,
        project=args.project,
        language=args.language,
    )

    is_new = store_entry(entry)
    status = "stored" if is_new else "already exists (skipped)"
    print(f"[{entry['metadata']['category']}] {entry['document'][:80]}")
    print(f"id: {entry['id']}  →  {status}")


if __name__ == "__main__":
    main()
