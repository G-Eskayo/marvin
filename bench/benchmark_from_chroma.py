#!/usr/bin/env python3
"""benchmark_from_chroma.py — build a frozen benchmark from paper-knowledge.

Pulls abstracts from ChromaDB, runs extract_structure (qwen2.5:3b), and calls
Claude once per sample to get ground-truth judgment labels. Writes a dated/
versioned frozen benchmark JSON that never overwrites existing files.

Usage:
    python3 benchmark_from_chroma.py [--sample-count 50] [--out /path/to/file.json]

Reuses bench.py's judge_run pattern for Claude calls (--tools "" sandboxing).
Marks frozen benchmark as "spent" after tuning uses it, per holdout_fixture discipline.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SKILLS = ROOT.parent / "skills"
sys.path.insert(0, str(ROOT.parent / "lib"))
sys.path.insert(0, str(ROOT / "lib"))

import model_registry  # noqa: E402

# Import from paper-dive skill
sys.path.insert(0, str(SKILLS / "paper-dive" / "scripts"))
from logic_auditor import classify_all, extract_all, PAPER_TYPES  # noqa: E402
from ollama_chat import ollama_chat  # noqa: E402

CHROMA_PATH = str(Path.home() / ".claude" / "chroma")
OLLAMA_BASE = os.environ.get("OLLAMA_BASE", "http://localhost:11434")

INFRA_ERROR_MARKERS = [
    "session limit", "not logged in", "rate limit", "quota exceeded",
]


def _is_infra_error(text: str) -> bool:
    """Check if error message indicates an infrastructure problem (not sample-specific)."""
    if not text:
        return False
    text_lower = text.lower()
    return any(marker.lower() in text_lower for marker in INFRA_ERROR_MARKERS)


def _ollama_available(model: str) -> tuple[bool, str]:
    """Return (ok, error_message). Checks server is up and model is pulled."""
    try:
        with urllib.request.urlopen(f"{OLLAMA_BASE}/api/tags", timeout=5) as resp:
            data = json.loads(resp.read())
    except Exception as exc:
        return False, f"Ollama server not responding ({exc}). Start with: ollama serve"
    available = [m["name"] for m in data.get("models", [])]
    if not model_registry.model_present(available, "qwen2.5:3b"):
        return False, (f"Model 'qwen2.5:3b' not found. Available: {available}\n"
                       f"Pull with: ollama pull qwen2.5:3b")
    return True, ""


def get_paper_knowledge_collection():
    """Return a ready-to-query ChromaDB collection (paper-knowledge)."""
    try:
        import chromadb
        from chromadb.utils.embedding_functions import OllamaEmbeddingFunction
    except ImportError as exc:
        raise ImportError(f"chromadb required: {exc}") from exc

    client = chromadb.PersistentClient(path=CHROMA_PATH)
    return client.get_or_create_collection("paper-knowledge")


def call_teacher(title: str, abstract: str, extraction: dict, paper_type: str, chat_fn=None) -> dict:
    """Call Claude as a teacher to generate ground-truth judgment label.

    Uses judge_run pattern from bench.py: sandboxed with --tools "", no session context.
    Returns {"finding": ..., "valid": bool} or {"error": str} on failure.
    Raises RuntimeError on infra errors to abort the benchmark build.
    """
    if chat_fn is None:
        chat_fn = _call_claude_teacher

    fields_str = "\n".join(f"{k}: {v}" for k, v in extraction.items())
    prompt = (
        f"Paper type: {paper_type}\n"
        f"Title: {title}\n"
        f"Abstract: {abstract}\n\n"
        f"Extracted structure:\n{fields_str}\n\n"
        "Judge whether this extraction is internally consistent and well-supported. "
        "Respond with ONLY a JSON object: "
        '{"finding": "description of issues", "valid": true/false}'
    )

    try:
        response = chat_fn([{"role": "user", "content": prompt}])
        # Parse JSON response
        result = json.loads(response)
        return result
    except (json.JSONDecodeError, ValueError) as exc:
        return {"error": f"unparseable teacher response: {exc}"}
    except Exception as exc:
        # Check if this is an infra error; if so, re-raise to stop the benchmark build
        exc_str = str(exc)
        if _is_infra_error(exc_str):
            raise RuntimeError(f"Infra error during teacher call: {exc_str}") from exc
        return {"error": exc_str}


def _call_claude_teacher(messages: list[dict]) -> str:
    """Call claude -p ... --tools "" (the bench.py pattern). Returns the model's JSON text."""
    prompt = messages[0]["content"] if messages else ""
    env = {**os.environ, "CLAUDE_CONFIG_DIR": str(ROOT / "profiles" / "clean")}
    for k in list(env):
        if k.startswith("CLAUDE_CODE_") or k in ("CLAUDECODE", "CLAUDE_EFFORT"):
            env.pop(k, None)

    try:
        proc = subprocess.run(
            ["claude", "-p", prompt, "--output-format", "json", "--tools", ""],
            capture_output=True, text=True, timeout=90, env=env
        )
        if proc.returncode != 0:
            if proc.stderr:
                raise RuntimeError(f"claude exit {proc.returncode}: {proc.stderr[:300]}")
            if proc.stdout:
                raise RuntimeError(f"claude returned empty (exit {proc.returncode})")

        # Unwrap CLI envelope: {"type":"result","result":"..."}
        envelope = json.loads(proc.stdout.strip())
        if envelope.get("type") != "result":
            raise RuntimeError(f"Unexpected envelope type: {envelope.get('type')}")
        model_text = envelope.get("result", "")

        # Remove code fences if present (model may output ```json...```)
        if model_text.startswith("```"):
            lines = model_text.split("\n")
            # Find first and last non-fence lines
            start = next((i for i, l in enumerate(lines) if not l.startswith("```")), 0)
            end = next((len(lines) - 1 - i for i, l in enumerate(reversed(lines)) if not l.startswith("```")), len(lines))
            model_text = "\n".join(lines[start:end+1])

        return model_text
    except subprocess.TimeoutExpired:
        raise RuntimeError("teacher call timed out after 90s")


def build_benchmark(sample_count: int = 50, out_path: Path | None = None, chat_fn=None) -> dict:
    """Build a frozen benchmark from paper-knowledge, label with Claude teacher.

    Returns the benchmark dict and writes it to out_path if provided.
    Format: {"created_epoch": ..., "sample_count": N, "samples": [...], "accuracy_baseline": null}
    """
    if out_path is None:
        out_path = ROOT / "benchmarks" / f"paper-dive-judgment-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # Verify Ollama is available
    ok, err = _ollama_available("qwen2.5:3b")
    if not ok:
        raise RuntimeError(err)

    # Pull papers from ChromaDB
    try:
        col = get_paper_knowledge_collection()
        result = col.get(include=["documents", "metadatas"], limit=sample_count)
    except Exception as exc:
        raise RuntimeError(f"Failed to query paper-knowledge collection: {exc}") from exc

    ids = result.get("ids", [])
    documents = result.get("documents", [])
    metadatas = result.get("metadatas", [])

    if not ids:
        print("WARNING: paper-knowledge collection is empty", file=sys.stderr)
        return {
            "created_epoch": time.time(),
            "sample_count": 0,
            "samples": [],
            "accuracy_baseline": None,
            "cost_estimate": "0.00 USD",
            "spent": False,
        }

    # Prepare papers dict for classify_all + extract_all
    papers_for_extract = {}
    paper_map = {}  # Track metadata
    seen_slugs = set()  # Track duplicates

    for i, (uid, doc, meta) in enumerate(zip(ids, documents, metadatas)):
        # Handle None or missing metadata
        if meta is None:
            meta = {}

        slug = meta.get("slug", f"p{i}")
        title = meta.get("title", "Unknown")
        abstract = doc or ""

        # Skip duplicate slugs (Chroma may return multiple chunks from same paper)
        if slug in seen_slugs:
            print(f"  Skipping duplicate chunk with slug {slug}", file=sys.stderr)
            continue
        seen_slugs.add(slug)

        papers_for_extract[slug] = (title, abstract)
        paper_map[slug] = {"uid": uid, "title": title, "meta": meta}

    print(f"Building benchmark from {len(papers_for_extract)} papers...", file=sys.stderr)

    # Classify papers
    try:
        types_dict = classify_all(papers_for_extract, chat_fn=None)  # Use Ollama for classification
    except Exception as exc:
        print(f"WARNING: classification failed, skipping: {exc}", file=sys.stderr)
        # Use a default valid type instead of "unknown" to avoid KeyError in judgment
        default_type = "empirical" if "empirical" in PAPER_TYPES else next(iter(PAPER_TYPES), "empirical")
        types_dict = {slug: default_type for slug in papers_for_extract}

    # Normalize any "unknown" types to a valid default
    default_type = "empirical" if "empirical" in PAPER_TYPES else next(iter(PAPER_TYPES), "empirical")
    types_dict = {slug: (types_dict.get(slug) if types_dict.get(slug) in PAPER_TYPES else default_type)
                  for slug in papers_for_extract}

    # Extract structures
    papers_for_extract_full = {
        slug: (*vals, types_dict.get(slug, "unknown"))
        for slug, vals in papers_for_extract.items()
    }

    try:
        extractions_dict = extract_all(papers_for_extract_full, chat_fn=None)  # Use Ollama for extraction
    except Exception as exc:
        print(f"WARNING: extraction failed, skipping: {exc}", file=sys.stderr)
        extractions_dict = {slug: {} for slug in papers_for_extract}

    # Get teacher labels (Claude calls)
    samples = []
    cost_estimate_total = 0.0

    for slug, (title, abstract) in papers_for_extract.items():
        paper_type = types_dict.get(slug, "unknown")
        extraction = extractions_dict.get(slug, {})

        print(f"  Getting teacher label for {slug}...", file=sys.stderr)

        teacher_label = call_teacher(title, abstract, extraction, paper_type, chat_fn=chat_fn)

        # Rough cost estimate: Claude call per sample
        # Approx 300 input tokens (prompt + paper) + 100 output tokens (response)
        # At ~$0.00030/input, $0.0015/output: ~$0.00039 per call
        cost_estimate_total += 0.0005

        sample = {
            "slug": slug,
            "title": title,
            "abstract": abstract[:500],  # Truncate for storage
            "extraction": extraction,
            "paper_type": paper_type,
            "claude_label": teacher_label if "error" not in teacher_label else None,
            "status": "ERROR" if "error" in teacher_label else "ok",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        samples.append(sample)

    benchmark = {
        "created_epoch": time.time(),
        "sample_count": len(samples),
        "samples": samples,
        "accuracy_baseline": None,  # Will be filled in by spec_search
        "cost_estimate": f"{cost_estimate_total:.2f} USD",
        "spent": False,
    }

    # Write to file (never overwrite existing)
    if out_path.exists():
        # Versioned filename
        stem = out_path.stem
        suffix = out_path.suffix
        i = 1
        while out_path.exists():
            out_path = out_path.parent / f"{stem}-v{i}{suffix}"
            i += 1

    out_path.write_text(json.dumps(benchmark, indent=2))
    print(f"Benchmark written to {out_path}", file=sys.stderr)

    return benchmark


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Build a frozen benchmark from paper-knowledge, labeled by Claude teacher"
    )
    ap.add_argument("--sample-count", type=int, default=50, help="Number of papers to sample")
    ap.add_argument("--out", type=Path, help="Output JSON file (default: benchmarks/paper-dive-judgment-*.json)")
    args = ap.parse_args()

    try:
        benchmark = build_benchmark(sample_count=args.sample_count, out_path=args.out)
        print(f"\n✓ Benchmark built: {benchmark['sample_count']} samples", file=sys.stderr)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
