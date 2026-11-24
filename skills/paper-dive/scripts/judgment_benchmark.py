#!/usr/bin/env python3
"""judgment_benchmark.py — build gold-standard labels for judgment spec search.

Samples papers from the paper-knowledge Chroma collection, generates gold labels
using logic_auditor's functions with a zero-tool, clean-profile Claude teacher,
and saves atomically as JSON for reproducible benchmarking.

Usage:
    python3 judgment_benchmark.py --sample-size 10 --out benchmark.json
"""
from __future__ import annotations
import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lib"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import logic_auditor  # noqa: E402
import model_registry  # noqa: E402


def _judge_call(prompt: str, timeout: int = 90) -> str:
    """Call claude as an LLM judge with zero tools, clean profile, to generate
    gold labels. Mirrors bench.py::judge_run's design: isolated environment,
    no tools, no memory, only text reasoning."""
    bench_dir = Path(__file__).resolve().parents[2] / "bench"
    clean_profile = bench_dir / "profiles" / "clean"

    judge_env = dict(os.environ)
    if clean_profile.exists():
        judge_env["CLAUDE_CONFIG_DIR"] = str(clean_profile)
    for k in list(judge_env):
        if k.startswith("CLAUDE_CODE_") or k in ("CLAUDECODE", "CLAUDE_EFFORT"):
            judge_env.pop(k, None)

    try:
        proc = subprocess.run(
            ["claude", "-p", prompt, "--output-format", "text", "--tools", ""],
            capture_output=True, text=True, timeout=timeout, env=judge_env
        )
        if proc.returncode != 0:
            raise RuntimeError(f"claude judge failed with code {proc.returncode}: {proc.stderr}")
        return proc.stdout.strip()
    except Exception as exc:
        raise RuntimeError(f"gold-label judge call failed: {exc}") from exc


def _make_gold_labels(
    slug: str, title: str, abstract: str
) -> dict:
    """Generate gold labels for a single paper using claude teacher + logic_auditor functions."""
    def teacher_chat(messages):
        """Wrapper: convert logic_auditor's ollama_chat calls to claude judge calls."""
        # Extract the prompt from messages
        prompt = next((m["content"] for m in messages if m["role"] == "user"), "")
        return _judge_call(prompt)

    # Classify paper type using teacher
    paper_type = logic_auditor.classify_paper_type(title, abstract, chat_fn=teacher_chat)

    # Extract structure using teacher
    extraction = logic_auditor.extract_structure(
        title, abstract, paper_type, chat_fn=teacher_chat
    )

    # Judge the extraction using teacher
    findings = logic_auditor.judge_extraction(extraction, paper_type, chat_fn=teacher_chat)

    # Check inference validity using teacher
    inference = logic_auditor.check_inference_validity(title, abstract, chat_fn=teacher_chat)

    # Compute reliability signal
    signal = logic_auditor.compute_reliability_signal(findings, inference)

    return {
        "slug": slug,
        "title": title,
        "abstract": abstract,
        "paper_type": paper_type,
        "extraction": extraction,
        "findings": findings,
        "inference": inference,
        "reliability_level": signal["level"],
        "reliability_findings": signal["findings"],
    }


def build_benchmark(sample_size: int = 10) -> dict[str, dict]:
    """Sample `sample_size` random papers from paper-knowledge collection and
    generate gold labels for each. Returns {slug: gold_label_dict, ...}."""
    import chromadb

    chroma_path = Path.home() / ".claude" / "chroma"
    client = chromadb.PersistentClient(path=str(chroma_path))
    collection = client.get_or_create_collection("paper-knowledge")

    # Get all IDs in the collection
    all_data = collection.get(include=[])
    all_ids = all_data.get("ids", [])

    if not all_ids:
        raise ValueError("paper-knowledge collection is empty")

    if len(all_ids) < sample_size:
        print(f"Warning: requested {sample_size} but only {len(all_ids)} papers exist; using all", flush=True)
        sample_size = len(all_ids)

    # Sample random IDs
    import random
    sample_ids = random.sample(all_ids, sample_size)

    # Fetch the samples
    sample_data = collection.get(ids=sample_ids, include=["documents", "metadatas"])
    slugs = sample_data["ids"]
    abstracts = sample_data["documents"]
    metadatas = sample_data["metadatas"]

    # Build gold labels for each
    benchmark = {}
    succeeded = 0
    failed = 0
    for slug, abstract, metadata in zip(slugs, abstracts, metadatas):
        title = metadata.get("title", slug) if metadata else slug
        print(f"Generating gold labels for {slug}...", flush=True)
        try:
            benchmark[slug] = _make_gold_labels(slug, title, abstract)
            succeeded += 1
        except Exception as e:
            print(f"  Error generating labels: {e}", file=sys.stderr, flush=True)
            failed += 1
            # Skip this paper; don't poison the benchmark with placeholder entries

    print(f"Benchmark complete: {succeeded} succeeded, {failed} failed", flush=True)
    return benchmark


def save_benchmark(benchmark: dict[str, dict], output_path: Path) -> None:
    """Atomically save benchmark to JSON file."""
    tmp = output_path.with_name(f".{output_path.name}.tmp")
    try:
        tmp.write_text(json.dumps(benchmark, indent=2))
        import os
        os.replace(tmp, output_path)
    finally:
        tmp.unlink(missing_ok=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Build gold-label benchmark for judgment spec search.")
    ap.add_argument("--sample-size", type=int, default=10, help="Number of papers to sample (default 10)")
    ap.add_argument("--out", required=True, help="Output JSON file path")
    args = ap.parse_args()

    out_path = Path(args.out).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)

    print(f"Building benchmark with {args.sample_size} papers...", flush=True)
    benchmark = build_benchmark(args.sample_size)

    print(f"Saving {len(benchmark)} benchmarks to {out_path}...", flush=True)
    save_benchmark(benchmark, out_path)
    print(f"Done. {len(benchmark)} gold labels saved.", flush=True)
