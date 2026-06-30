#!/usr/bin/env python3
"""Cross-reference today's research-feed against qa-knowledge and roadmap keywords."""
import sys
from datetime import date
from pathlib import Path

CHROMA_PATH = Path.home() / ".claude" / "chroma"
ROADMAP_PATH = Path.home() / ".claude" / "marvin-roadmap.md"

# Keyword → roadmap section label
ROADMAP_KEYWORDS: dict[str, str] = {
    "quantization": "A.quantization",
    "vllm": "A.vllm",
    "rag": "A.rag",
    "retrieval augmented": "A.rag",
    "kv cache": "A.kv-cache",
    "chromadb": "C.vector-db",
    "vector db": "C.vector-db",
    "hnsw": "C.hnsw",
    "weaviate": "C.vector-db",
    "qdrant": "C.vector-db",
    "code review": "B.code-review",
    "llm judge": "H.llm-judge",
    "llm-as-judge": "H.llm-judge",
    "benchmark": "H.bench",
    "evaluation": "H.bench",
    "routing": "G.routing",
    "fine-tun": "G.fine-tuning",
    "distillation": "G.distillation",
    "daily digest": "I.digest",
    "research monitor": "J.monitor",
    "multi-agent": "J.colony",
    "agent framework": "B.agent",
    "tool use": "B.agent",
    "function call": "B.agent",
    "context window": "A.context",
    "prompt caching": "A.cache",
    "token efficiency": "A.tokens",
    "model context protocol": "B.mcp",
    " mcp ": "B.mcp",
    "memory": "C.memory",
    "embedding": "C.embedding",
    "sentence transformer": "C.embedding",
    "nomic": "C.embedding",
}


def roadmap_match(text: str) -> str:
    low = text.lower()
    found = sorted({section for kw, section in ROADMAP_KEYWORDS.items() if kw in low})
    return ", ".join(found)


def correlate(threshold: float = 1.1) -> list[dict]:
    try:
        import chromadb
    except ImportError:
        print("[colony] chromadb not installed — skipping correlate", file=sys.stderr)
        return []

    client = chromadb.PersistentClient(path=str(CHROMA_PATH))

    try:
        qa_col = client.get_collection("qa-knowledge")
    except Exception:
        print("[colony] qa-knowledge collection not found — keyword-only correlation", file=sys.stderr)
        qa_col = None

    research_col = client.get_or_create_collection("research-feed")

    today = date.today().isoformat()
    try:
        raw = research_col.get(
            where={"date": today},
            include=["documents", "metadatas"],  # ids always returned, not a valid include value
        )
    except Exception:
        raw = {"documents": [], "metadatas": [], "ids": []}

    docs = raw.get("documents") or []
    metas = raw.get("metadatas") or []
    ids = raw.get("ids") or []

    correlated_items = []

    for doc, meta, uid in zip(docs, metas, ids):
        rm = roadmap_match(doc)

        # Semantic similarity against qa-knowledge
        sem_match = ""
        if qa_col is not None:
            try:
                sim = qa_col.query(query_texts=[doc], n_results=3, include=["distances", "documents"])
                distances = sim["distances"][0]
                matched_docs = sim["documents"][0]
                if distances and min(distances) < threshold:
                    sem_match = (matched_docs[0] or "")[:100]
            except Exception:
                pass

        is_correlated = bool(rm) or bool(sem_match)

        if is_correlated:
            matched = rm or sem_match
            new_meta = {**meta, "correlated": "true", "matched_topics": matched[:300]}
            try:
                research_col.update(ids=[uid], metadatas=[new_meta])
            except Exception:
                pass
            correlated_items.append({
                "title": meta.get("title", ""),
                "url": meta.get("url", ""),
                "source": meta.get("source", ""),
                "matched": matched,
                "document": doc,
            })

    print(
        f"[colony] {len(correlated_items)} of {len(docs)} today's items correlated",
        file=sys.stderr,
    )
    return correlated_items


if __name__ == "__main__":
    results = correlate()
    for item in results:
        print(f"  [{item['source']}] {item['title'][:60]} → {item['matched']}")
