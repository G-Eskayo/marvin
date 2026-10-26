#!/usr/bin/env python3
"""
paper_dive_benchmark.py — Benchmarking for paper-dive prompt optimization via spec-search.

Workflow:
1. Load papers from paper-knowledge ChromaDB collection (frozen benchmark)
2. Generate teacher (Claude) labels for judge_extraction + check_inference_validity
3. Score untuned student (qwen2.5:3b) against frozen labels
4. Run spec-search to optimize judge_extraction + check_inference_validity prompts
5. Record results in bench/RESULTS.md

This script handles steps 1-3 in sequence. Spec-search (step 4) is run separately
to allow Gil to review frozen labels before optimization begins.
"""
from __future__ import annotations
import argparse
import json
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "skills" / "paper-dive" / "scripts"))

from benchmark_loader import load_papers_from_chroma, save_benchmark_labels, load_benchmark_labels
from logic_auditor import (
    classify_all, extract_all, judge_all, check_inference_validity_all,
    compute_all_reliability_signals, build_audit_report, ollama_chat,
    EXTRACTION_MODEL, JUDGMENT_MODEL, INFERENCE_MODEL,
)

BENCHMARK_DIR = Path(__file__).resolve().parent / "benchmark_data"
FROZEN_LABELS = BENCHMARK_DIR / "frozen_labels.json"
STUDENT_SCORES = BENCHMARK_DIR / "student_scores.json"


@dataclass
class BenchmarkSample:
    """One frozen benchmark sample."""
    slug: str
    title: str
    abstract: str
    paper_type: str
    layer1_findings: list[str]
    layer2_result: dict


def load_frozen_benchmark() -> dict[str, BenchmarkSample]:
    """Loads the frozen benchmark. Returns {slug: BenchmarkSample}."""
    if not FROZEN_LABELS.exists():
        raise FileNotFoundError(f"Frozen labels not found: {FROZEN_LABELS}")

    with open(FROZEN_LABELS) as f:
        data = json.load(f)

    samples = {}
    for slug, item in data.items():
        samples[slug] = BenchmarkSample(
            slug=slug,
            title=item["title"],
            abstract=item["abstract"],
            paper_type=item["paper_type"],
            layer1_findings=item.get("layer1_findings", []),
            layer2_result=item.get("layer2_result", {}),
        )
    return samples


def format_messages_to_prompt(messages: list) -> str:
    """Formats a list of {role, content} messages into a single prompt string."""
    prompt_parts = []
    for msg in messages:
        role = msg.get("role", "user").upper()
        content = msg.get("content", "")
        prompt_parts.append(f"{role}:\n{content}")
    return "\n\n".join(prompt_parts)


def score_finding(teacher_count: int, student_findings: list | dict | None) -> float:
    """Scores student finding count against teacher count using recall/precision balance.

    Returns float in [0, 1] where 1.0 is perfect agreement.
    Handles non-iterable student_findings gracefully.
    """
    try:
        student_count = len(student_findings) if student_findings else 0
    except TypeError:
        # student_findings is not iterable
        student_count = 0

    if teacher_count == 0:
        # Teacher found nothing. Score 1.0 only if student also found nothing.
        return 1.0 if student_count == 0 else 0.0

    # Teacher found something. Measure recall and precision balance.
    # Recall: what fraction of teacher's findings did student recover?
    recall = min(student_count / teacher_count, 1.0)
    # Precision: did student avoid over-generating?
    # If student found more than teacher, penalize by reducing to teacher's baseline.
    precision = 1.0 if student_count <= teacher_count else teacher_count / student_count
    # Average recall and precision
    return (recall + precision) / 2.0


def generate_teacher_labels() -> dict:
    """Generates ground-truth labels from Claude. Saves and returns {slug: {type, findings, inference}}."""
    print("Step 1: Loading papers from ChromaDB...")
    papers = load_papers_from_chroma()
    print(f"  Loaded {len(papers)} papers")

    print("\nStep 2: Generating teacher labels from Claude...")
    print("  Classifying paper types...")

    def claude_call(prompt: str) -> str:
        """One headless Claude call via subprocess."""
        try:
            proc = subprocess.run(
                ["claude", "-p", prompt, "--output-format", "text", "--tools", ""],
                capture_output=True, text=True, timeout=90,
            )
            if proc.returncode != 0:
                raise RuntimeError(f"Claude exited {proc.returncode}: {proc.stderr[:200]}")
            return proc.stdout.strip()
        except subprocess.TimeoutExpired:
            raise RuntimeError("Claude call timed out")

    def claude_chat_fn(messages: list) -> str:
        full_prompt = format_messages_to_prompt(messages)
        return claude_call(full_prompt)

    # Classify
    paper_types = classify_all(papers, chat_fn=claude_chat_fn)

    # Extract
    papers_with_types = {slug: (title, abstract, paper_types[slug])
                         for slug, (title, abstract) in papers.items()}
    print("  Extracting structures...")
    extractions = extract_all(papers_with_types, chat_fn=claude_chat_fn)

    # Judge extraction
    papers_for_judgment = {slug: (extractions[slug], paper_types[slug])
                          for slug in papers}
    print("  Judging extractions...")
    layer1_findings = judge_all(papers_for_judgment, chat_fn=claude_chat_fn)

    # Check inference
    print("  Checking inference validity...")
    layer2_results = check_inference_validity_all(papers, chat_fn=claude_chat_fn)

    # Build labels
    labels = {}
    for slug, (title, abstract) in papers.items():
        labels[slug] = {
            "title": title,
            "abstract": abstract,
            "paper_type": paper_types.get(slug, "unknown"),
            "layer1_findings": layer1_findings.get(slug, []),
            "layer2_result": layer2_results.get(slug, {}),
        }
        print(f"    {slug}: {paper_types.get(slug, 'unknown')}")

    # Save frozen labels
    BENCHMARK_DIR.mkdir(parents=True, exist_ok=True)
    save_benchmark_labels(labels, FROZEN_LABELS)
    print(f"\nFrozen labels saved to {FROZEN_LABELS}")

    return labels


def score_student_model() -> dict[str, float]:
    """
    Scores untuned student (qwen2.5:3b) against frozen benchmark.
    Returns {slug: score} where score is in [0, 1].
    """
    print("\nStep 3: Scoring untuned student model...")

    samples = load_frozen_benchmark()
    scores = {}

    for slug, sample in sorted(samples.items()):
        try:
            # Judge extraction: does student find the same findings as teacher?
            extraction = extract_all(
                {slug: (sample.title, sample.abstract, sample.paper_type)},
                chat_fn=lambda msgs: ollama_chat(EXTRACTION_MODEL, msgs),
            )[slug]

            student_findings = judge_all(
                {slug: (extraction, sample.paper_type)},
                chat_fn=lambda msgs: ollama_chat(JUDGMENT_MODEL, msgs),
            )[slug]

            # Check inference: does student agree on reasoning type/validity?
            student_inference = check_inference_validity_all(
                {slug: (sample.title, sample.abstract)},
                chat_fn=lambda msgs: ollama_chat(INFERENCE_MODEL, msgs),
            )[slug]

            # Score: does student's finding count align with teacher's?
            # Exact string matching fails because teacher/student use different wording.
            # Instead: measure recall (did student find enough?) and precision (did they avoid inventing?).
            teacher_count = len(sample.layer1_findings) if sample.layer1_findings else 0
            finding_score = score_finding(teacher_count, student_findings)

            # Check inference: does reasoning_type and basic validity agree?
            teacher_reasoning = sample.layer2_result.get("reasoning_type", "unknown")
            student_reasoning = student_inference.get("reasoning_type", "unknown")
            reasoning_match = 1.0 if teacher_reasoning == student_reasoning else 0.0

            combined = (finding_score * 0.7) + (reasoning_match * 0.3)
            scores[slug] = combined

            print(f"  {slug}: findings={finding_score:.1%} reasoning={reasoning_match:.0%} → {combined:.1%}")

        except (subprocess.CalledProcessError, RuntimeError, ConnectionError, KeyError) as e:
            # These are unrecoverable failures: Ollama down, model missing, subprocess crash.
            # Abort loudly per design doc requirement (§4 Tests), not silently score 0.
            print(f"FATAL: {slug} — {e}", file=sys.stderr)
            raise

    # Save baseline scores
    with open(STUDENT_SCORES, "w") as f:
        json.dump(scores, f, indent=2)

    avg = sum(scores.values()) / len(scores) if scores else 0.0
    print(f"\nUntuned student average: {avg:.1%}")
    print(f"Scores saved to {STUDENT_SCORES}")

    return scores


def show_summary() -> None:
    """Prints a summary of the frozen benchmark."""
    if not FROZEN_LABELS.exists():
        print("No frozen benchmark yet. Run with --freeze first.")
        return

    with open(FROZEN_LABELS) as f:
        labels = json.load(f)

    print(f"\nFrozen Benchmark Summary ({len(labels)} papers)")
    print("=" * 60)

    by_type = {}
    for slug, item in labels.items():
        ptype = item.get("paper_type", "unknown")
        by_type.setdefault(ptype, []).append(slug)

    for ptype in sorted(by_type):
        slugs = by_type[ptype]
        print(f"  {ptype}: {len(slugs)} papers")
        for slug in sorted(slugs)[:3]:
            print(f"    - {slug}")
        if len(slugs) > 3:
            print(f"    ... and {len(slugs) - 3} more")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--freeze", action="store_true",
                   help="Generate teacher labels and freeze benchmark")
    ap.add_argument("--score", action="store_true",
                   help="Score untuned student against frozen benchmark")
    ap.add_argument("--all", action="store_true",
                   help="Run freeze + score")
    ap.add_argument("--summary", action="store_true",
                   help="Show benchmark summary")
    args = ap.parse_args()

    if not any([args.freeze, args.score, args.all, args.summary]):
        ap.print_help()
        return

    if args.summary:
        show_summary()
        return

    if args.all or args.freeze:
        try:
            generate_teacher_labels()
        except Exception as e:
            print(f"ERROR during label generation: {e}", file=sys.stderr)
            sys.exit(1)

    if args.all or args.score:
        try:
            score_student_model()
        except Exception as e:
            print(f"ERROR during scoring: {e}", file=sys.stderr)
            sys.exit(1)

    print("\n" + "=" * 60)
    print("Benchmark setup complete!")
    print(f"Frozen labels: {FROZEN_LABELS}")
    print(f"Student scores: {STUDENT_SCORES}")
    print("Next: Review frozen labels, then run spec-search")


if __name__ == "__main__":
    main()
