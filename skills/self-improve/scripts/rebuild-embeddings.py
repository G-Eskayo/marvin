#!/usr/bin/env python3
"""
rebuild-embeddings.py
Syncs ChromaDB with current manifest entries.
Only re-embeds files whose content hash changed.
Falls back gracefully if Ollama is unavailable.
"""

import hashlib
import json
import sys
from pathlib import Path

HOME = Path.home()
MANIFEST_PATH = HOME / ".claude" / "manifest.json"
CHROMA_PATH = HOME / ".claude" / "chroma"
OLLAMA_URL = "http://localhost:11434/api/embed"
EMBED_MODEL = "nomic-embed-text"


def resolve_path(p):
    return Path(p.replace("~/", str(HOME) + "/"))


def strip_frontmatter(text):
    if not text.startswith("---"):
        return text
    end = text.find("\n---", 3)
    if end == -1:
        return text
    return text[end + 4:].strip()


MAX_EMBED_CHARS = 4000  # nomic-embed-text default ctx ~2048 tokens ≈ 4000 chars


def build_doc_text(path, tags):
    try:
        content = path.read_text(encoding="utf-8")
    except Exception:
        return " ".join(tags)
    body = strip_frontmatter(content)
    tag_str = " ".join(tags)
    text = f"{tag_str}\n\n{body}"
    return text[:MAX_EMBED_CHARS]


def content_hash(text):
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def embed(text):
    try:
        import requests
        resp = requests.post(
            OLLAMA_URL,
            json={"model": EMBED_MODEL, "input": f"search_document: {text}"},
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()["embeddings"][0]
    except Exception as e:
        print(f"  WARN: embed failed: {e}", file=sys.stderr)
        return None


def collection_for(tags):
    for t in tags:
        if t == "type:skill":
            return "skills"
        if t == "type:knowledge":
            return "knowledge"
    return "general"


def sync_collection(client, cname, coll_entries) -> tuple[int, int, int]:
    """Upsert changed entries and prune deleted ones. Returns (embedded, skipped, removed)."""
    collection = client.get_or_create_collection(
        name=cname,
        metadata={"hnsw:space": "cosine"},
    )
    existing = collection.get(include=["metadatas"])
    existing_by_id = {
        eid: existing["metadatas"][i]
        for i, eid in enumerate(existing["ids"])
    }
    current_ids: set[str] = set()
    embedded = skipped = 0

    for entry in coll_entries:
        path = resolve_path(entry["path"])
        doc_id = entry["path"]
        current_ids.add(doc_id)

        if not path.exists():
            print(f"  WARN: file not found: {path}", file=sys.stderr)
            continue

        doc_text = build_doc_text(path, entry.get("tags", []))
        h = content_hash(doc_text)

        if doc_id in existing_by_id and existing_by_id[doc_id].get("content_hash") == h:
            skipped += 1
            continue

        vector = embed(doc_text)
        if vector is None:
            continue

        metadata: dict = {
            "path": entry["path"],
            "name": entry.get("name", ""),
            "tags": " ".join(entry.get("tags", [])),
            "content_hash": h,
        }
        if entry.get("calls"):
            metadata["calls"] = " ".join(entry["calls"])

        collection.upsert(ids=[doc_id], embeddings=[vector], documents=[doc_text], metadatas=[metadata])
        embedded += 1

    stale = set(existing_by_id) - current_ids
    if stale:
        collection.delete(ids=list(stale))

    return embedded, skipped, len(stale)


def main():
    if not MANIFEST_PATH.exists():
        print("  WARN: manifest.json not found — skipping embeddings", file=sys.stderr)
        return

    manifest = json.loads(MANIFEST_PATH.read_text())
    entries = manifest.get("index", [])
    if not entries:
        print("  INFO: manifest index is empty — nothing to embed", file=sys.stderr)
        return

    try:
        import requests
        requests.get("http://localhost:11434/", timeout=3)
    except Exception:
        print(
            "  WARN: Ollama not reachable — embedding rebuild skipped. "
            "Tag-only retrieval will be used.",
            file=sys.stderr,
        )
        return

    import chromadb
    client = chromadb.PersistentClient(path=str(CHROMA_PATH))

    by_collection: dict[str, list] = {}
    for entry in entries:
        cname = collection_for(entry.get("tags", []))
        by_collection.setdefault(cname, []).append(entry)

    total_embedded = total_skipped = total_removed = 0
    for cname, coll_entries in by_collection.items():
        e, s, r = sync_collection(client, cname, coll_entries)
        total_embedded += e
        total_skipped += s
        total_removed += r

    print(
        f"  Embeddings: {total_embedded} updated, {total_skipped} unchanged, "
        f"{total_removed} removed → {CHROMA_PATH}",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
