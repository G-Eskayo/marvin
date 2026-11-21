"""RAG-based memory retrieval for the Ollama bench runner.

Instead of injecting the full MEMORY.md + all 15 files as a single
context dump (which causes smaller models to ignore project-specific
terminology in favour of their training priors), this module:

  1. Embeds each memory file once, persisting to a 'marvin-memory'
     ChromaDB collection (reuses existing ~/.claude/chroma store).
  2. At query time, embeds the task prompt and retrieves the top-N
     most semantically similar passages.
  3. Returns a compact, focused system message containing only what
     is relevant — typically 200-400 tokens vs 4000+ for full injection.

Why this helps:
  Full injection: model sees 15 files, applies training knowledge for
  plausible questions, ignores project-specific terms that compete.
  RAG injection: model sees 2-3 targeted passages; the specific passage
  lands with no noise, no competing context.
"""
from __future__ import annotations

import json
import re
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lib"))
import model_calls  # noqa: E402

CHROMA_PATH = str(Path.home() / ".claude" / "chroma")
COLLECTION  = "marvin-memory"
EMBED_MODEL = "nomic-embed-text"
OLLAMA_CALLER = "memory_rag"
OLLAMA_NUM_CTX = 2048

# module-level cache so bench doesn't re-open collection on every run
_col_cache: object | None = None


class _CustomEmbeddingFunction:
    """Custom ChromaDB embedding function using model_calls.embed()."""

    def __call__(self, input: list[str]) -> list[list[float]]:
        """Embed a batch of texts. Parameter name 'input' required by ChromaDB protocol."""
        embeddings = []
        for text in input:
            try:
                result = model_calls.embed(EMBED_MODEL, text, caller=OLLAMA_CALLER, num_ctx=OLLAMA_NUM_CTX, timeout=30)
                embeddings.append(result["embedding"])
            except model_calls.PromptTooLargeError:
                # Text is too large to embed; return a zero vector as placeholder
                # This allows collection build to continue instead of aborting
                print(f"  [memory_rag] warning: memory file too large to embed (skipping)", flush=True)
                embeddings.append([0.0] * 768)  # nomic-embed-text produces 768-dim vectors
            except (model_calls.OllamaUnavailableError, Exception) as e:
                # Ollama is unavailable or unexpected error; fail fast
                raise RuntimeError(f"Cannot embed text: {e}")
        return embeddings


def _memory_dir() -> Path | None:
    """Return the first memory/ directory found under ~/.claude/projects/."""
    projects = Path.home() / ".claude" / "projects"
    if not projects.exists():
        return None
    for candidate in sorted(projects.rglob("MEMORY.md")):
        return candidate.parent
    return None


def _all_memory_docs() -> list[tuple[str, str, dict]]:
    """Return (doc_id, text, metadata) for every .md file in the memory dir."""
    mem_dir = _memory_dir()
    if not mem_dir:
        return []
    docs = []
    for md in sorted(mem_dir.glob("*.md")):
        try:
            text = md.read_text(errors="ignore").strip()
        except OSError:
            continue
        if not text:
            continue
        docs.append((md.name, text, {"filename": md.name, "path": str(md)}))
    return docs


def _get_collection(force_rebuild: bool = False):
    """Return a ready-to-query ChromaDB collection, building it if needed."""
    global _col_cache
    if _col_cache is not None and not force_rebuild:
        return _col_cache

    import chromadb

    ef = _CustomEmbeddingFunction()
    client = chromadb.PersistentClient(path=CHROMA_PATH)

    if force_rebuild:
        try:
            client.delete_collection(COLLECTION)
        except Exception:
            pass

    try:
        col = client.get_collection(COLLECTION, embedding_function=ef)
        if col.count() > 0 and not force_rebuild:
            _col_cache = col
            return col
        client.delete_collection(COLLECTION)
    except Exception:
        pass

    col = client.create_collection(COLLECTION, embedding_function=ef)
    docs = _all_memory_docs()
    if docs:
        ids, texts, metas = zip(*docs)
        col.add(ids=list(ids), documents=list(texts), metadatas=list(metas))
        print(f"  [memory_rag] indexed {len(docs)} memory files → '{COLLECTION}'",
              flush=True)
    _col_cache = col
    return col


def query_memory(task_prompt: str, n_results: int = 3) -> str:
    """Return top-N memory passages as a focused system-message string.

    Falls back to empty string if ChromaDB or Ollama is unavailable.
    """
    try:
        col = _get_collection()
        count = col.count()
        if count == 0:
            return ""
        results = col.query(
            query_texts=[task_prompt],
            n_results=min(n_results, count),
            include=["documents", "metadatas", "distances"],
        )
    except Exception as exc:
        print(f"  [memory_rag] query failed: {exc}", flush=True)
        return ""

    docs  = results["documents"][0]
    metas = results["metadatas"][0]
    dists = results["distances"][0]
    if not docs:
        return ""

    # cosine distance: 0=identical, 2=opposite → similarity = 1 − d/2
    parts = ["# MARVIN Memory — targeted context (RAG, top-%d passages)\n" % len(docs)]
    for doc, meta, dist in zip(docs, metas, dists):
        sim = 1.0 - dist / 2.0
        fname = meta.get("filename", "?")
        parts.append(f"## {fname}  (similarity {sim:.2f})\n\n{doc}")

    return "\n\n---\n\n".join(parts)


def rebuild() -> int:
    """Force-rebuild the collection. Returns the number of documents indexed."""
    col = _get_collection(force_rebuild=True)
    return col.count()
