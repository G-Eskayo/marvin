#!/usr/bin/env python3
"""
benchmark_loader.py — loads the frozen benchmark of seed papers from the
paper-knowledge ChromaDB collection for spec-search evaluation.

Each benchmark sample is: {slug, title, abstract, paper_type, layer1_findings, layer2_result}
The labels (findings, layer2) are generated once by the teacher (Claude) and frozen as ground truth.
"""
from __future__ import annotations
import json
from pathlib import Path
import sys

CHROMA_PATH = Path.home() / ".claude" / "chroma"


def load_papers_from_chroma(collection_name: str = "paper-knowledge") -> dict[str, tuple[str, str]]:
    """
    Loads all papers from a ChromaDB collection. Returns {slug: (title, abstract)}.
    Filters out any items with missing/empty abstracts.
    """
    try:
        import chromadb
    except ImportError:
        raise ImportError("chromadb not installed; install with `pip install chromadb`")

    if not CHROMA_PATH.exists():
        raise FileNotFoundError(f"ChromaDB path does not exist: {CHROMA_PATH}")

    client = chromadb.PersistentClient(path=str(CHROMA_PATH))
    try:
        collection = client.get_collection(collection_name)
    except ValueError:
        raise ValueError(f"Collection '{collection_name}' not found in {CHROMA_PATH}")

    # Get all items from the collection
    try:
        data = collection.get(include=["documents", "metadatas"])
    except Exception as e:
        raise RuntimeError(f"Failed to query collection: {e}")

    papers = {}
    for slug, abstract, metadata in zip(data.get("ids", []), data.get("documents", []), data.get("metadatas", []) or [{}] * len(data.get("ids", []))):
        if not abstract or not abstract.strip():
            continue

        # Try to get title from metadata, fallback to slug
        title = metadata.get("title") if metadata else None
        if not title:
            title = slug.replace("-", " ").title()

        papers[slug] = (title, abstract)

    if not papers:
        raise ValueError(f"No papers with abstracts found in collection '{collection_name}'")

    return papers


def load_benchmark_labels(benchmark_path: Path) -> dict:
    """Loads the frozen benchmark labels from a JSON file. Returns {slug: {labels_dict}}."""
    if not benchmark_path.exists():
        raise FileNotFoundError(f"Benchmark file not found: {benchmark_path}")

    with open(benchmark_path) as f:
        return json.load(f)


def save_benchmark_labels(labels: dict, benchmark_path: Path) -> None:
    """Saves benchmark labels atomically to a JSON file."""
    benchmark_path.parent.mkdir(parents=True, exist_ok=True)

    # Write to temp file first, then atomically rename
    temp_path = benchmark_path.with_suffix(".tmp")
    with open(temp_path, "w") as f:
        json.dump(labels, f, indent=2)
    temp_path.replace(benchmark_path)


if __name__ == "__main__":
    papers = load_papers_from_chroma()
    print(f"Loaded {len(papers)} papers from ChromaDB")
    for slug, (title, abstract) in sorted(papers.items()):
        print(f"  {slug}: {title}")
        print(f"    Abstract length: {len(abstract)} chars")
