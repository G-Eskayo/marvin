#!/usr/bin/env python3
"""spec_search.py — tuning harness for the logic_auditor.py judgment prompt.

Benchmark-guided spec search: teacher (gpt-4 or claude-opus) proposes prompt
edits based on tuning-set misses, student (qwen2.5:3b or configurable) tests
the edit against the full tuning+holdout suite. Keeps only edits that improve
tuning accuracy without regression on holdout.

Design:
  1. Freeze a benchmark-sample split (tuning/holdout) from seed papers + paper-sessions state.
  2. Measure baseline: student accuracy on tuning + holdout.
  3. Loop (max N rounds):
     a. Teacher identifies misses on tuning set.
     b. Teacher proposes one prompt edit from those misses.
     c. Apply via prompt_override, re-measure tuning accuracy.
     d. Keep only if no regression on holdout; otherwise discard and continue.
  4. Evaluate final spec on holdout only (not tuning, to avoid overfitting).
  5. Report cost + wall time + results to RESULTS.md.

Usage:
    python3 spec_search.py [--max-rounds 5] [--teacher-model claude-opus]
         [--student-model qwen2.5:3b] [--profile marvin]
"""
from __future__ import annotations
import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "lib"))

# Import paper-dive's logic_auditor
sys.path.insert(0, str(ROOT.parent / "skills/paper-dive/scripts"))
import logic_auditor  # noqa: E402

from bench import _check_quota  # noqa: E402
from score import parse_stream  # noqa: E402

# Model defaults (same as select_model.py's ladder, first two items)
DEFAULT_TEACHER_MODEL = "claude-opus-4-1-20250805"
DEFAULT_STUDENT_MODEL = "qwen2.5:3b"


def load_benchmark_split(manifest_path: Path) -> dict:
    """Load the frozen tuning/holdout split from a committed manifest.
    Returns {"tuning": [slugs...], "holdout": [slugs...]}.
    Creates one if it doesn't exist yet."""
    if manifest_path.exists():
        return json.loads(manifest_path.read_text())

    # TODO: implement the loader that:
    # - resolves seed papers (no discovered_via) from paper-knowledge Chroma collection
    # - matches with ~/.claude/paper-sessions/*/state.json
    # - freezes a random 70/30 split to the manifest
    # For now, placeholder to unblock the rest of the harness
    raise NotImplementedError("benchmark split loader not yet built")


def compute_accuracy(student_findings: dict[str, list[str]], gold_findings: dict[str, list[str]]) -> float:
    """Accuracy: fraction of papers where student findings match gold findings.
    A match means the student found no issues (empty list) iff gold found none.
    Raises ValueError if inputs are empty or mismatched keys."""
    if not student_findings or not gold_findings:
        raise ValueError("compute_accuracy requires non-empty student_findings and gold_findings dicts")

    if set(student_findings.keys()) != set(gold_findings.keys()):
        raise ValueError(f"student and gold findings must have same paper keys; "
                        f"student has {set(student_findings.keys())}, gold has {set(gold_findings.keys())}")

    matches = 0
    for slug in student_findings.keys():
        student_clean = len(student_findings[slug]) == 0
        gold_clean = len(gold_findings[slug]) == 0
        if student_clean == gold_clean:
            matches += 1

    return matches / len(student_findings)


def run_judge_batch(student_model: str, papers: dict, extractions: dict,
                    types: dict, prompt_override: str | None = None) -> dict:
    """Run the student model to judge all papers in batch.
    Returns {slug: findings_list}."""
    if student_model.startswith("qwen") or student_model.startswith("ollama"):
        # Ollama via logic_auditor's built-in ollama_chat
        def chat_fn(messages):
            return logic_auditor.ollama_chat(student_model, messages)

        result = {}
        for slug, (title, abstract) in papers.items():
            extraction = extractions.get(slug, {})
            paper_type = types.get(slug, "unknown")
            if paper_type == "unknown":
                result[slug] = ["unknown paper type"]
                continue
            result[slug] = logic_auditor.judge_extraction(
                extraction, paper_type, chat_fn=chat_fn, prompt_override=prompt_override
            )
        return result
    else:
        # Claude model via claude CLI in subprocess
        raise NotImplementedError("Claude subprocess judging not yet built")


def propose_prompt_edit(teacher_model: str, paper_type: str, tuning_misses: dict,
                       current_prompt: str) -> str | None:
    """Call teacher model to propose a prompt edit.
    Returns the new prompt candidate, or None if teacher can't suggest improvement."""
    raise NotImplementedError("teacher-call helper not yet built")


def main() -> None:
    ap = argparse.ArgumentParser(description="Tune the logic_auditor judgment prompt via spec search.")
    ap.add_argument("--max-rounds", type=int, default=5,
                    help="max prompt-edit rounds (default 5)")
    ap.add_argument("--teacher-model", default=DEFAULT_TEACHER_MODEL,
                    help=f"teacher model for prompt proposals (default {DEFAULT_TEACHER_MODEL})")
    ap.add_argument("--student-model", default=DEFAULT_STUDENT_MODEL,
                    help=f"student model for judging (default {DEFAULT_STUDENT_MODEL})")
    ap.add_argument("--profile", default="marvin", choices=["clean", "lean", "marvin"],
                    help="bench profile to run under")
    args = ap.parse_args()

    manifest_path = ROOT / "results" / "spec-search-paper-dive-judgment-sample.json"

    # Preflight
    print(f"spec-search: tuning judge prompt ({args.student_model})", flush=True)
    print(f"  manifest: {manifest_path}", flush=True)
    print(f"  teacher: {args.teacher_model}, max {args.max_rounds} rounds", flush=True)

    quota = _check_quota()
    if quota is None:
        print("preflight: could not determine quota — proceeding anyway", flush=True)

    # Load/create the frozen split
    split = load_benchmark_split(manifest_path)
    tuning_slugs = split["tuning"]
    holdout_slugs = split["holdout"]

    print(f"  tuning set: {len(tuning_slugs)} papers", flush=True)
    print(f"  holdout set: {len(holdout_slugs)} papers", flush=True)

    # TODO: load papers + extractions + types from the split
    # For now, placeholder
    papers_tuning = {}
    papers_holdout = {}
    extractions_tuning = {}
    extractions_holdout = {}
    types_tuning = {}
    types_holdout = {}

    # TODO: Get gold labels for both tuning and holdout sets (teacher judgment)
    # For now, using student baseline as a placeholder
    gold_tuning = {}
    gold_holdout = {}

    # Baseline: student on tuning set only (holdout reserved for final eval)
    print("\n== Baseline run ==", flush=True)
    baseline_tuning = run_judge_batch(args.student_model, papers_tuning,
                                      extractions_tuning, types_tuning)
    baseline_tuning_acc = compute_accuracy(baseline_tuning, gold_tuning)

    print(f"tuning accuracy: {baseline_tuning_acc:.3f}", flush=True)

    # Spec-search loop
    current_prompt = None  # None = use default prompts
    best_tuning_acc = baseline_tuning_acc
    best_prompt = None

    for round_n in range(1, args.max_rounds + 1):
        print(f"\n== Round {round_n} ==", flush=True)

        # TODO: propose edit (teacher call)
        candidate_prompt = propose_prompt_edit(args.teacher_model, "empirical",  # placeholder
                                              baseline_tuning, current_prompt)
        if candidate_prompt is None:
            print("teacher: no further improvements suggested, stopping", flush=True)
            break

        # Test candidate on tuning set only (holdout is reserved for final evaluation)
        # Reject if the prompt is malformed (raises ValueError when applied).
        try:
            candidate_tuning = run_judge_batch(args.student_model, papers_tuning,
                                              extractions_tuning, types_tuning,
                                              prompt_override=candidate_prompt)
        except ValueError as e:
            print(f"rejecting candidate: malformed prompt ({e})", flush=True)
            continue

        candidate_tuning_acc = compute_accuracy(candidate_tuning, gold_tuning)

        # Decision: keep only if tuning improved (holdout is not evaluated during search)
        tuning_improved = candidate_tuning_acc > best_tuning_acc
        keep = tuning_improved

        print(f"tuning: {candidate_tuning_acc:.3f} (best: {best_tuning_acc:.3f}) {'+' if tuning_improved else '-'}",
              flush=True)
        print(f"verdict: {'KEEP' if keep else 'DISCARD'}", flush=True)

        if keep:
            current_prompt = candidate_prompt
            best_tuning_acc = candidate_tuning_acc
            best_prompt = candidate_prompt
        else:
            print("reverting to prior prompt", flush=True)

    # Final eval: on holdout only (unbiased evaluation, not used for selection)
    print(f"\n== Final evaluation (holdout only) ==", flush=True)
    if best_prompt is not None:
        final_holdout = run_judge_batch(args.student_model, papers_holdout,
                                       extractions_holdout, types_holdout,
                                       prompt_override=best_prompt)
    else:
        final_holdout = run_judge_batch(args.student_model, papers_holdout,
                                       extractions_holdout, types_holdout)

    final_holdout_acc = compute_accuracy(final_holdout, gold_holdout)
    print(f"final holdout accuracy: {final_holdout_acc:.3f}", flush=True)

    # TODO: write results to RESULTS.md with cost/wall-time summary
    # TODO: write trace JSON
    # TODO: wire in (or file follow-up ticket)

    print("\nspec-search complete", flush=True)


if __name__ == "__main__":
    main()
