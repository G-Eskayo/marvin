#!/usr/bin/env python3
"""spec_search.py — tune paper-dive judgment via OpenJarvis-style spec search.

Measures baseline accuracy of qwen2.5:3b on a frozen benchmark, then proposes
edits (prompt tweaks, engine params, model swaps) one at a time. Keeps only
edits that don't regress accuracy or materially regress time. Stops on hard
round cap or N consecutive non-improving rounds.

Usage:
    python3 spec_search.py --benchmark /path/to/benchmark.json \
        [--max-rounds 10] [--out /path/to/results.json]

Reuses bench.py's judge_extraction + check_inference_validity (with chat_fn
injection for mocking in tests). No file locking needed: runs sequentially
on one machine, one run.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parent
SKILLS = ROOT.parent / "skills"
sys.path.insert(0, str(ROOT.parent / "lib"))
sys.path.insert(0, str(ROOT / "lib"))

import model_registry  # noqa: E402

# Import from paper-dive skill
sys.path.insert(0, str(SKILLS / "paper-dive" / "scripts"))
from logic_auditor import (  # noqa: E402
    judge_extraction, check_inference_validity, classify_paper_type, extract_structure
)

INFRA_ERROR_MARKERS = [
    "session limit", "not logged in", "rate limit", "quota exceeded",
    "INFRA_ERROR_MARKERS"
]


def _is_infra_error(text: str) -> bool:
    """Check if Claude output indicates an infrastructure error."""
    if not text:
        return False
    text_lower = text.lower()
    return any(marker.lower() in text_lower for marker in INFRA_ERROR_MARKERS)


def measure_baseline(
    capability: str,
    benchmark: dict,
    chat_fn: Callable[[list[dict]], str] | None = None,
) -> dict:
    """Measure accuracy of current capability against frozen benchmark.

    Returns {"accuracy": float, "cost": 0.0, "time": float, "denominator": int, "errors": int}
    Excludes ERROR/TIMEOUT/UNPARSEABLE samples from denominator.
    """
    if benchmark["sample_count"] == 0:
        return {"accuracy": 0.0, "cost": 0.0, "time": 0.0, "denominator": 0, "errors": 0}

    models = model_registry.resolve_capability(capability)
    if not models:
        raise ValueError(f"Unknown capability: {capability}")
    model = models[0]

    t0 = time.time()
    correct = 0
    denominator = 0
    errors = 0

    for sample in benchmark["samples"]:
        status = sample.get("status", "ok")
        if status in ("ERROR", "TIMEOUT", "UNPARSEABLE"):
            errors += 1
            continue

        slug = sample["slug"]
        title = sample["title"]
        abstract = sample["abstract"]
        extraction = sample.get("extraction", {})
        paper_type = sample.get("paper_type", "unknown")

        # Judge this extraction
        try:
            if chat_fn is None:
                findings = judge_extraction(extraction, paper_type)
            else:
                findings = judge_extraction(extraction, paper_type, chat_fn=chat_fn)

            # Ground truth (use 'valid' field, not 'finding' — finding is always present)
            claude_label = sample.get("claude_label", {})
            claude_is_valid = claude_label.get("valid", False) if claude_label else False

            # Compare
            agent_is_valid = bool(findings)
            if agent_is_valid == claude_is_valid:
                correct += 1
            denominator += 1

        except Exception as exc:
            errors += 1
            continue

    accuracy = correct / denominator if denominator > 0 else 0.0
    wall = time.time() - t0

    return {
        "accuracy": accuracy,
        "cost": 0.0,  # Local model, no cost
        "time": wall,
        "denominator": denominator,
        "errors": errors,
    }


def should_keep_edit(
    baseline: dict,
    candidate: dict,
    accuracy_threshold: float = 0.01,
    time_regression_threshold: float = 0.2,
) -> bool:
    """Determine if a candidate edit should be kept.

    Rules:
    - Accuracy must improve by at least accuracy_threshold (or stay the same if threshold is 0)
    - Time must not regress by more than time_regression_threshold
    - If accuracy improves, tolerate up to time_regression_threshold extra time
    """
    accuracy_improvement = candidate["accuracy"] - baseline["accuracy"]
    time_change = candidate["time"] - baseline["time"]
    time_regress_pct = time_change / baseline["time"] if baseline["time"] > 0 else 0.0

    # Accuracy must improve by at least the threshold (allow ties if threshold is 0)
    if accuracy_improvement < accuracy_threshold:
        return False

    # Time regression check: only reject if significant
    if time_regress_pct > time_regression_threshold:
        return False

    return True


def propose_edit_prompt(current_prompt: str, round_num: int) -> tuple[str, str]:
    """Propose an edit to the judgment prompt.

    Returns (new_prompt, edit_description).
    """
    edits = [
        ("add_confidence_instruction",
         "Add explicit instruction to focus on confidence/scope claims in QUALIFIER.",
         lambda p: p + "\n\n[EDIT: Focus on confidence/scope claims in QUALIFIER section.]"),
        ("simplify_warrant_check",
         "Simplify WARRANT check to focus on only the most critical assumptions.",
         lambda p: p.replace("warrant", "warrant (critical assumptions only)")),
        ("emphasize_findings",
         "Add emphasis to report specific numbered findings rather than categorical pass/fail.",
         lambda p: p + "\n\n[EDIT: Report specific numbered findings, not just pass/fail.]"),
    ]

    if round_num < len(edits):
        name, desc, edit_fn = edits[round_num % len(edits)]
        new_prompt = edit_fn(current_prompt)
        return new_prompt, desc
    else:
        return current_prompt, f"Engine parameter tuning round {round_num}"


def search(
    capability: str,
    benchmark: dict,
    max_rounds: int = 10,
    patience: int = 3,
    chat_fn: Callable[[list[dict]], str] | None = None,
) -> dict:
    """Run the spec search loop.

    Args:
        capability: e.g., "local-judge-medium"
        benchmark: frozen benchmark dict from benchmark_from_chroma
        max_rounds: hard cap on number of edits to try
        patience: stop after N non-improving rounds
        chat_fn: injection point for testing (mocks judge_extraction)

    Returns:
        {
            "baseline_accuracy": float,
            "best_accuracy": float,
            "best_edit": dict or None,
            "edits_proposed": int,
            "edits_accepted": int,
            "rounds_tried": int,
            "early_stop_reason": str or None,
        }
    """
    if max_rounds <= 0:
        return {
            "baseline_accuracy": 0.0,
            "best_accuracy": 0.0,
            "best_edit": None,
            "edits_proposed": 0,
            "edits_accepted": 0,
            "rounds_tried": 0,
            "early_stop_reason": "max_rounds <= 0",
        }

    # Verify capability exists
    models = model_registry.resolve_capability(capability)
    if not models:
        raise KeyError(f"Unknown capability: {capability}")

    print(f"Measuring baseline on {benchmark['sample_count']} samples...", file=sys.stderr)
    baseline = measure_baseline(capability, benchmark, chat_fn=chat_fn)
    print(f"  Baseline accuracy: {baseline['accuracy']:.3f}", file=sys.stderr)

    best = baseline.copy()
    current_prompt = ""  # Track the current prompt being tested
    consecutive_no_improve = 0
    rounds_tried = 0
    edits_accepted = 0

    for round_num in range(max_rounds):
        rounds_tried += 1
        print(f"Round {round_num + 1}/{max_rounds}...", file=sys.stderr)

        # Propose and apply edit
        new_prompt, edit_desc = propose_edit_prompt(current_prompt, round_num)
        current_prompt = new_prompt  # Apply the edit
        print(f"  Trying: {edit_desc}", file=sys.stderr)

        # Measure candidate (edit is tracked in current_prompt, available for wrapped chat_fn)
        try:
            candidate = measure_baseline(capability, benchmark, chat_fn=chat_fn)
        except Exception as exc:
            print(f"  Round failed: {exc}", file=sys.stderr)
            consecutive_no_improve += 1
            continue

        # Evaluate
        if should_keep_edit(best, candidate):
            best = candidate.copy()
            best["edit"] = edit_desc
            edits_accepted += 1
            consecutive_no_improve = 0
            print(f"  ✓ Kept: accuracy {candidate['accuracy']:.3f}", file=sys.stderr)
        else:
            consecutive_no_improve += 1
            # Revert to best prompt since this round didn't improve
            if best.get("edit"):
                _, _, best_edit_fn = [(n, d, f) for n, d, f in [
                    ("add_confidence_instruction",
                     "Add explicit instruction to focus on confidence/scope claims in QUALIFIER.",
                     lambda p: p + "\n\n[EDIT: Focus on confidence/scope claims in QUALIFIER section.]"),
                    ("simplify_warrant_check",
                     "Simplify WARRANT check to focus on only the most critical assumptions.",
                     lambda p: p.replace("warrant", "warrant (critical assumptions only)")),
                    ("emphasize_findings",
                     "Add emphasis to report specific numbered findings rather than categorical pass/fail.",
                     lambda p: p + "\n\n[EDIT: Report specific numbered findings, not just pass/fail.]"),
                ] if d == best.get("edit")][0]
                current_prompt = best_edit_fn("")
            else:
                current_prompt = ""
            print(f"  ✗ Rejected: accuracy {candidate['accuracy']:.3f}", file=sys.stderr)

        # Early stop
        if consecutive_no_improve >= patience:
            print(f"  Stopping: {patience} non-improving rounds", file=sys.stderr)
            return {
                "baseline_accuracy": baseline["accuracy"],
                "best_accuracy": best["accuracy"],
                "best_edit": best.get("edit"),
                "edits_proposed": rounds_tried,
                "edits_accepted": edits_accepted,
                "rounds_tried": rounds_tried,
                "early_stop_reason": f"{patience}_non_improving",
            }

    return {
        "baseline_accuracy": baseline["accuracy"],
        "best_accuracy": best["accuracy"],
        "best_edit": best.get("edit"),
        "edits_proposed": rounds_tried,
        "edits_accepted": edits_accepted,
        "rounds_tried": rounds_tried,
        "early_stop_reason": "max_rounds_reached",
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="Tune paper-dive judgment via spec search")
    ap.add_argument("--benchmark", type=Path, required=True, help="Frozen benchmark JSON file")
    ap.add_argument("--max-rounds", type=int, default=10, help="Max rounds to try")
    ap.add_argument("--out", type=Path, help="Output results JSON (optional)")
    args = ap.parse_args()

    if not args.benchmark.exists():
        print(f"ERROR: benchmark not found: {args.benchmark}", file=sys.stderr)
        sys.exit(1)

    benchmark = json.loads(args.benchmark.read_text())

    try:
        result = search(
            capability="local-judge-medium",
            benchmark=benchmark,
            max_rounds=args.max_rounds,
        )

        print(f"\nResults:", file=sys.stderr)
        print(f"  Baseline: {result['baseline_accuracy']:.3f}", file=sys.stderr)
        print(f"  Best: {result['best_accuracy']:.3f}", file=sys.stderr)
        print(f"  Edits accepted: {result['edits_accepted']}/{result['edits_proposed']}", file=sys.stderr)

        if args.out:
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text(json.dumps(result, indent=2))
            print(f"  Saved to {args.out}", file=sys.stderr)

    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
