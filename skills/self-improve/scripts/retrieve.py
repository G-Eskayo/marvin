#!/usr/bin/env python3
"""
retrieve.py
Hybrid retrieval: semantic (ChromaDB + nomic-embed-text) + BM25, with RRF merge.
Falls back to manifest tag matching if Ollama or ChromaDB unavailable.

CLI usage:
  python3 retrieve.py "how do I build an MCP server"
  python3 retrieve.py "debug auth middleware" --intent debug
  python3 retrieve.py "brainstorm new features" --intent create --json
"""

import argparse
import json
import sys
from pathlib import Path

HOME = Path.home()
MANIFEST_PATH = HOME / ".claude" / "manifest.json"
CHROMA_PATH = HOME / ".claude" / "chroma"
OLLAMA_URL = "http://localhost:11434/api/embed"
EMBED_MODEL = "nomic-embed-text"
ALL_COLLECTIONS = ["skills", "knowledge", "general"]
TOP_K = 5

# Higher threshold = precision (analytical). Lower = recall (creative).
INTENT_THRESHOLD_MAP = {
    "debug":      0.55,
    "fix":        0.55,
    "diagnose":   0.55,
    "create":     0.25,
    "ideate":     0.25,
    "brainstorm": 0.25,
    "plan":       0.40,
    "research":   0.40,
    "tdd":        0.50,
}
DEFAULT_THRESHOLD = 0.35


def get_threshold(intent):
    if intent and intent in INTENT_THRESHOLD_MAP:
        return INTENT_THRESHOLD_MAP[intent]
    return DEFAULT_THRESHOLD


def embed_query(query):
    try:
        import requests
        resp = requests.post(
            OLLAMA_URL,
            json={"model": EMBED_MODEL, "input": f"search_query: {query}"},
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json()["embeddings"][0]
    except Exception:
        return None


def semantic_search(query_vector, threshold):
    try:
        import chromadb
        client = chromadb.PersistentClient(path=str(CHROMA_PATH))
        results = []

        for cname in ALL_COLLECTIONS:
            try:
                collection = client.get_collection(cname)
            except Exception:
                continue
            count = collection.count()
            if count == 0:
                continue
            res = collection.query(
                query_embeddings=[query_vector],
                n_results=min(TOP_K * 2, count),
                include=["metadatas", "distances", "documents"],
            )
            for i, _ in enumerate(res["ids"][0]):
                # cosine distance → similarity
                score = 1.0 - res["distances"][0][i]
                if score >= threshold:
                    meta = res["metadatas"][0][i]
                    results.append({
                        "path": meta["path"],
                        "name": meta.get("name", ""),
                        "tags": meta.get("tags", "").split(),
                        "score": round(score, 4),
                        "source": "semantic",
                    })

        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:TOP_K]

    except Exception as e:
        print(f"  WARN: semantic search error: {e}", file=sys.stderr)
        return []


def bm25_rerank(query, candidates):
    if not candidates:
        return candidates
    try:
        from rank_bm25 import BM25Okapi
        docs = [
            c["path"] + " " + " ".join(c.get("tags", []))
            for c in candidates
        ]
        tokenized = [d.lower().split() for d in docs]
        bm25 = BM25Okapi(tokenized)
        scores = bm25.get_scores(query.lower().split())
        for i, c in enumerate(candidates):
            c["bm25_score"] = float(scores[i])
    except Exception:
        pass
    return candidates


def rrf_merge(semantic, bm25_enhanced, k=60):
    seen = {}

    for rank, doc in enumerate(semantic):
        p = doc["path"]
        seen.setdefault(p, {"doc": doc, "rrf": 0.0})
        seen[p]["rrf"] += 1 / (k + rank + 1)

    bm25_ranked = sorted(
        bm25_enhanced, key=lambda x: x.get("bm25_score", 0), reverse=True
    )
    for rank, doc in enumerate(bm25_ranked):
        p = doc["path"]
        seen.setdefault(p, {"doc": doc, "rrf": 0.0})
        seen[p]["rrf"] += 1 / (k + rank + 1)

    merged = sorted(seen.values(), key=lambda x: x["rrf"], reverse=True)
    return [m["doc"] for m in merged[:TOP_K]]


def tag_fallback(query):
    if not MANIFEST_PATH.exists():
        return []
    manifest = json.loads(MANIFEST_PATH.read_text())
    query_words = set(query.lower().split())
    results = []
    for entry in manifest.get("index", []):
        tag_words = set()
        for t in entry.get("tags", []):
            tag_words.update(t.replace(":", " ").replace("-", " ").split())
        overlap = len(query_words & tag_words)
        if overlap > 0:
            results.append({
                "path": entry["path"],
                "name": entry.get("name", ""),
                "tags": entry.get("tags", []),
                "score": round(overlap / max(len(query_words), 1), 4),
                "source": "tags",
            })
    results.sort(key=lambda x: x["score"], reverse=True)
    return results[:TOP_K]


def retrieve(query, intent=None):
    threshold = get_threshold(intent)

    query_vector = embed_query(query)
    if query_vector is None:
        print("  INFO: Ollama unavailable — using tag fallback", file=sys.stderr)
        return tag_fallback(query)

    semantic = semantic_search(query_vector, threshold)

    if not semantic:
        return tag_fallback(query)

    enhanced = bm25_rerank(query, semantic)
    return rrf_merge(semantic, enhanced)


def main():
    parser = argparse.ArgumentParser(
        description="Hybrid retrieval over skills + knowledge"
    )
    parser.add_argument("query", help="Natural language query")
    parser.add_argument(
        "--intent",
        help="Intent hint: debug, fix, diagnose, create, ideate, brainstorm, plan, research, tdd",
    )
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    results = retrieve(args.query, args.intent)

    if args.json:
        print(json.dumps(results, indent=2))
        return

    if not results:
        print("No relevant files found.")
        return

    for r in results:
        score = f"{r.get('score', 0):.3f}"
        source = r.get("source", "?")
        print(f"  [{score}] ({source}) {r['path']}")
        if r.get("name"):
            print(f"           {r['name']}")


if __name__ == "__main__":
    main()
