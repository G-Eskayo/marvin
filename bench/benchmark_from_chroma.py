#!/usr/bin/env python3
"""benchmark_from_chroma.py — build frozen benchmark from paper-knowledge ChromaDB.

Pulls real paper abstracts from ~/.claude/chroma (paper-knowledge collection),
runs extraction (qwen2.5:3b, unaffected by #563), and gets ground-truth judgment
labels from Claude (teacher) to freeze as the benchmark.

The frozen benchmark is versioned/dated so re-running doesn't silently overwrite
prior sets. Used by spec_search.py to tune the local model.

Output is written to bench/data/paper-dive-benchmark-<YYYYMMDD-HHMMSS>.json

Usage:
    mkdir -p bench/data
    python3 benchmark_from_chroma.py > bench/data/paper-dive-benchmark-$(date +%Y%m%d-%H%M%S).json

Note: This pulls from ChromaDB and calls claude -p once per sample, so it requires:
- ChromaDB with paper-knowledge collection loaded
- Claude CLI with valid auth (claude -p must work)
- Network access (no --offline-only mode)
"""
from __future__ import annotations
import json
import sys
import subprocess
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "lib"))

import metrics_registry


def get_papers_from_chroma(max_papers: int = None) -> list[dict]:
    """Load paper abstracts from paper-knowledge ChromaDB collection.

    Returns list of {"slug", "title", "abstract"} dicts.
    Raises if ChromaDB is not available or collection not found.
    """
    try:
        import chromadb
    except ImportError:
        sys.exit("chromadb not installed — install with: pip install chromadb")

    # Connect to the existing Chroma instance (user's local ~/.claude/chroma)
    chroma_dir = Path.home() / ".claude" / "chroma"
    if not chroma_dir.exists():
        sys.exit(f"Chroma directory not found: {chroma_dir}")

    client = chromadb.PersistentClient(path=str(chroma_dir))

    # Load paper-knowledge collection
    try:
        collection = client.get_collection(name="paper-knowledge")
    except Exception as e:
        sys.exit(f"Failed to load paper-knowledge collection: {e}")

    # Fetch all documents
    all_docs = collection.get()

    papers = []
    count = 0
    for i, doc_id in enumerate(all_docs.get("ids", [])):
        if max_papers and count >= max_papers:
            break

        # Extract metadata (handle None from Chroma)
        metadatas = all_docs.get("metadatas", [])
        metadata = metadatas[i] if i < len(metadatas) else {}
        if metadata is None:
            metadata = {}

        # Get abstract from document
        documents = all_docs.get("documents", [])
        abstract = documents[i] if i < len(documents) else ""

        # Construct slug from doc_id (usually something like "arxiv-2605.17172")
        slug = doc_id

        # Extract title from metadata or doc_id
        title = metadata.get("title", "") or slug

        if abstract:
            papers.append({
                "slug": slug,
                "title": title,
                "abstract": abstract,
            })
            count += 1

    if not papers:
        print("WARNING: No papers found in paper-knowledge collection", file=sys.stderr)
    else:
        print(f"Loaded {len(papers)} papers from paper-knowledge ChromaDB", file=sys.stderr)

    return papers


def _can_load_model(model_name: str) -> bool:
    """Check if a model is actually loaded/available on Ollama.

    Guards against #563 bug where config/models.json lists deleted models.
    Returns True if model responds, False otherwise.
    """
    try:
        import urllib.request
        payload = json.dumps({"model": model_name, "messages": [], "stream": False})
        req = urllib.request.Request(
            "http://localhost:11434/api/chat",
            data=payload.encode(),
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            json.loads(resp.read())
            return True
    except Exception:
        return False


def classify_and_extract(papers: list[dict], max_samples: int = None) -> list[dict]:
    """For each paper, classify type and extract structure.

    Uses:
    - resident model for classification (logic_auditor.classify_paper_type)
    - qwen2.5:3b for extraction (logic_auditor.extract_structure)

    Returns list of {"slug", "title", "abstract", "paper_type", "extraction"}

    Note: Classification uses the resident model configured in logic_auditor.
    If qwen2.5:14b is not available (per #563), logic_auditor will resolve
    the capability to an available model, or raise an error.
    """
    # Import paper-dive logic_auditor, handling hyphenated path
    paper_dive_scripts = ROOT.parent / "skills" / "paper-dive" / "scripts"
    sys.path.insert(0, str(paper_dive_scripts))

    try:
        from logic_auditor import classify_paper_type, extract_structure, PAPER_TYPES
    except ImportError as e:
        sys.exit(f"Failed to import logic_auditor: {e}")

    enriched = []
    for i, paper in enumerate(papers):
        if max_samples and i >= max_samples:
            break

        slug = paper["slug"]
        title = paper["title"]
        abstract = paper["abstract"]

        print(f"  [{i+1}/{len(papers)}] {slug}: classifying...", file=sys.stderr, flush=True)

        # Classify paper type
        try:
            paper_type = classify_paper_type(title, abstract)
            if paper_type == "unknown":
                print(f"    WARNING: could not classify {slug} — skipping", file=sys.stderr)
                continue
        except Exception as e:
            print(f"    ERROR classifying {slug}: {e} — skipping", file=sys.stderr)
            continue

        # Extract structure
        try:
            extraction = extract_structure(title, abstract, paper_type)
        except Exception as e:
            print(f"    WARNING: extraction failed for {slug}: {e}", file=sys.stderr)
            extraction = {}

        enriched.append({
            "slug": slug,
            "title": title,
            "abstract": abstract,
            "paper_type": paper_type,
            "extraction": extraction,
        })

    print(f"Classified and extracted {len(enriched)} papers", file=sys.stderr)
    return enriched


def get_teacher_judgments(enriched_papers: list[dict]) -> list[dict]:
    """For each enriched paper, get Claude's ground-truth judgment.

    Uses: claude -p subprocess call (reuses bench.py's pattern)

    Adds teacher_finding to each sample.
    Returns list of fully prepared benchmark samples.
    """
    # Import from paper-dive, handling hyphenated path
    paper_dive_scripts = ROOT.parent / "skills" / "paper-dive" / "scripts"
    sys.path.insert(0, str(paper_dive_scripts))

    try:
        from logic_auditor import (
            judge_extraction, _JUDGMENT_PROMPTS, _GENERAL_FALLACY_CHECKLIST,
            EXTRACTION_FIELDS, _parse_findings
        )
    except ImportError as e:
        sys.exit(f"Failed to import from logic_auditor: {e}")

    benchmark = []
    for i, sample in enumerate(enriched_papers):
        slug = sample["slug"]
        extraction = sample["extraction"]
        paper_type = sample["paper_type"]

        print(f"  [{i+1}/{len(enriched_papers)}] {slug}: getting teacher judgment...",
              file=sys.stderr, flush=True)

        # Build the judgment prompt (same as logic_auditor would use)
        if paper_type not in _JUDGMENT_PROMPTS:
            print(f"    WARNING: unknown paper_type {paper_type!r} — skipping", file=sys.stderr)
            continue

        # Fill in missing extraction fields
        fields = {
            name.lower(): extraction.get(name.lower(), "(not extracted)")
            for name in EXTRACTION_FIELDS.get(paper_type, [])
        }

        prompt = _JUDGMENT_PROMPTS[paper_type].format(
            fallacies=_GENERAL_FALLACY_CHECKLIST,
            **fields
        )

        # Call Claude teacher
        # SECURITY: Do NOT use --permission-mode bypassPermissions
        # This would give the untrusted paper abstract access to tools/shell
        try:
            # Use claude -p subprocess pattern (reuse from bench.py)
            # Run without tools to prevent injection through adversarial abstracts
            teacher_response = subprocess.run(
                ["claude", "-p", "--output-format", "text", "--tools", ""],
                input=prompt,
                capture_output=True,
                text=True,
                timeout=60,
            )
            if teacher_response.returncode != 0:
                print(f"    ERROR: claude -p failed: {teacher_response.stderr}", file=sys.stderr)
                teacher_findings = ["ERROR"]
            else:
                # Parse findings from response
                teacher_findings = _parse_findings(teacher_response.stdout)
        except subprocess.TimeoutExpired:
            print(f"    ERROR: claude -p timed out for {slug}", file=sys.stderr)
            teacher_findings = ["TIMEOUT"]
        except Exception as e:
            print(f"    ERROR: failed to get teacher judgment: {e}", file=sys.stderr)
            teacher_findings = ["ERROR"]

        benchmark.append({
            "slug": slug,
            "title": sample["title"],
            "abstract": sample["abstract"],
            "paper_type": paper_type,
            "extraction": extraction,
            "teacher_finding": teacher_findings,
        })

    print(f"Got teacher judgments for {len(benchmark)} samples", file=sys.stderr)
    return benchmark


def main():
    print("Building frozen benchmark from paper-knowledge ChromaDB...", file=sys.stderr, flush=True)

    # Step 1: Load papers from ChromaDB
    papers = get_papers_from_chroma(max_papers=None)  # All papers, but could limit
    if not papers:
        sys.exit("No papers found in ChromaDB")

    # Step 2: Classify and extract
    enriched = classify_and_extract(papers, max_samples=None)
    if not enriched:
        sys.exit("No papers successfully classified and extracted")

    # Step 3: Get teacher judgments
    benchmark = get_teacher_judgments(enriched)
    if not benchmark:
        sys.exit("No benchmark samples created")

    # Write benchmark to stdout as JSON
    print(json.dumps(benchmark, indent=2), file=sys.stdout)

    # Log metadata
    timestamp = datetime.now(timezone.utc).isoformat()
    print(f"Benchmark created: {timestamp}", file=sys.stderr)
    print(f"Total samples: {len(benchmark)}", file=sys.stderr)


if __name__ == "__main__":
    main()
