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

# ── pattern type inference ────────────────────────────────────────────────────

_PATTERN_TYPE_KEYWORDS: dict[str, list[str]] = {
    "idempotent":        ["idempotent", "dedup", "deduplication", "hash", "already exists",
                          "skip if", "duplicate", "upsert"],
    "caching":           ["cache", "caching", "persistent", "module-level cache", "ephemeral",
                          "in-memory", "restart"],
    "context-injection": ["context injection", "rag", "retrieval", "semantic hit", "embedding",
                          "top-n", "n_results", "query_texts", "inject"],
    "cost-optimization": ["token", "cost", "cheaper", "savings", "zero-cost", "haiku",
                          "lean profile", "reduce", "overhead", "%"],
    "error-handling":    ["silent", "pitfall", "gotcha", "workaround", "fails", "broken",
                          "no error", "no warning", "symptom", "fix:"],
    "runtime-config":    ["venv", "interpreter", "env var", "environment", "claude_config_dir",
                          "config dir", "plist", "launchd", "shell",
                          "dyld", "library_path", "shared lib", "homebrew", "pango", "glib",
                          "ram", "feasible", "hardware", "quantization", "gb"],
    "schema":            ["schema", "metadata", "field", "collection", "document format",
                          "data model", "chroma", "category", "tags"],
    "pipeline":          ["pipeline", "orchestrat", "sequential", "batch", "multi-step",
                          "hook", "posttooluse", "cron"],
    "routing":           ["routing", "classifier", "profile", "intent", "dispatch",
                          "model selection", "alias", "route", "min_hits"],
    "api-integration":   ["api", "http", "endpoint", "request", "response", "client",
                          "url", "post", "get", "fetch"],
    "data-pattern":      ["sql", "join", "query", "aggregate", "correlation", "enrichment",
                          "attribution", "cross-domain", "lateral"],
    "code-quality":      ["nested loop", "o(n²)", "function", "lines long", "parameters",
                          "static method", "dead code", "generic parameter", "naming",
                          "verbosity", "filler word", "bare todo", "uninformative",
                          "complexity", "kiss", "oop", "refactor", "suggestion:",
                          "[bug]", "[fixme]", "[hack]", "[todo]", "mutates", "wrong for",
                          "grading", "specificity", "substring grading"],
    "dependency":        ["depends on library", "imports these third-party", "uses stack",
                          "requirements.txt", "package.json", "pyproject.toml",
                          "pip install", "npm install"],
    "security":          ["public repo", "pii", "leak", "personal data", "never commit",
                          "must not", "private", "secret", "credential",
                          "sensitive", "phone number", "email"],
}


def infer_pattern_type(document: str, tags: str = "", category: str = "") -> str:
    """Return best-guess pattern_type from document content and tags."""
    text = f"{document} {tags}".lower()
    scores = {pt: sum(1 for kw in kws if kw in text)
              for pt, kws in _PATTERN_TYPE_KEYWORDS.items()}
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else ""


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
    domain: str = "",
    outcome: str = "",
    pattern_type: str = "",
) -> dict:
    entry_id = "qa-" + hashlib.sha256(content.encode()).hexdigest()[:16]
    return {
        "id": entry_id,
        "document": content,
        "metadata": {
            "category":     category,
            "source":       source,
            "project":      project,
            "language":     language,
            "library":      library,
            "tags":         tags,
            "confidence":   confidence,
            "domain":       domain,
            "outcome":      outcome,
            "pattern_type": pattern_type or infer_pattern_type(content, tags, category),
            "created_at":   datetime.now(timezone.utc).isoformat(),
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
    ap.add_argument("--domain",        default="",
                    help="knowledge domain: python-agents|aws-cloud|bench-harness|data-pipeline|web-backend|devtools|ml-ops|all")
    ap.add_argument("--outcome",       default="",
                    help="what happened when this was applied (free text)")
    ap.add_argument("--pattern-type",  default="",
                    help="mechanism type: idempotent|caching|context-injection|cost-optimization|"
                         "error-handling|runtime-config|schema|pipeline|routing|api-integration|data-pattern")
    args = ap.parse_args()

    entry = build_entry(
        content=args.content,
        category=args.category,
        library=args.library,
        tags=args.tags,
        confidence=args.confidence,
        project=args.project,
        language=args.language,
        domain=args.domain,
        outcome=args.outcome,
        pattern_type=args.pattern_type,
    )

    is_new = store_entry(entry)
    status = "stored" if is_new else "already exists (skipped)"
    print(f"[{entry['metadata']['category']}] {entry['document'][:80]}")
    print(f"id: {entry['id']}  →  {status}")


if __name__ == "__main__":
    main()
