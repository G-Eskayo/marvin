#!/usr/bin/env python3
"""spec_search.py — tune a local model via edit-and-regress search.

Given a capability name and a frozen benchmark, proposes one-at-a-time edits
(prompt wording, engine params, model choice per the search-space decision),
measures against the frozen benchmark, and keeps only non-regressing edits.

Reuses lib/metrics_registry.py for the baseline->change->re-measure->iterate
pattern; all teacher (Claude) and student (local model) calls go through
injected function parameters, so tests can use fakes without real network calls.

Usage:
    # First-time: build and freeze benchmark
    python3 benchmark_from_chroma.py > bench/data/paper-dive-benchmark-2026-10-27.json

    # Then: run the search
    python3 spec_search.py \\
        --capability local-judge-medium \\
        --benchmark bench/data/paper-dive-benchmark-2026-10-27.json \\
        --max-rounds 10

    # Write result to judgment_spec.json for logic_auditor to read at runtime
    (See step 7 in plan: persist winning setup)
"""
from __future__ import annotations
import argparse
import json
import sys
import urllib.request
from pathlib import Path
from datetime import datetime, timezone
import subprocess

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "lib"))

import metrics_registry
import model_registry


# ── Model availability check (guards against #563 bug) ───────────────────────

def _can_load_model(model_name: str) -> bool:
    """Check if a model is actually loaded/available on Ollama.

    Guards against the #563 bug where config/models.json lists deleted models
    (qwen2.5:7b, qwen2.5:14b) that are no longer on disk.

    Returns True if the model responds to a quick check, False otherwise.
    """
    try:
        payload = json.dumps({"model": model_name, "messages": [], "stream": False})
        req = urllib.request.Request(
            "http://localhost:11434/api/chat",
            data=payload.encode(),
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())
            # If we got a response, model is loaded (even if it errored)
            return True
    except (urllib.error.URLError, urllib.error.HTTPError, Exception):
        return False


# ── Benchmark building ──────────────────────────────────────────────────────

def build_benchmark_from_samples(
    samples: list[dict],
    teacher_fn: callable,
    chat_fn: callable = None,
) -> list[dict]:
    """Build frozen benchmark from paper samples.

    samples: list of {"slug", "title", "abstract", "paper_type", optional "extraction"}
    teacher_fn: callable(extraction, paper_type) -> str that returns Claude judgment
    chat_fn: injected callable for testing extract_structure; if None, calls real Ollama

    Returns list of frozen benchmark samples with teacher_finding included.
    Samples with unparseable teacher responses are marked unusable or excluded.
    """
    # Import relative to project root, handling hyphenated path
    paper_dive_scripts = ROOT.parent / "skills" / "paper-dive" / "scripts"
    sys.path.insert(0, str(paper_dive_scripts))
    try:
        from logic_auditor import extract_structure, _parse_findings
    except ImportError as e:
        raise ImportError(
            f"Failed to import logic_auditor from {paper_dive_scripts}: {e}"
        ) from e

    if not samples:
        print("WARNING: build_benchmark_from_samples called with zero samples", file=sys.stderr)
        return []

    benchmark = []
    for sample in samples:
        slug = sample.get("slug", "unknown")
        title = sample.get("title", "")
        abstract = sample.get("abstract", "")
        paper_type = sample.get("paper_type", "unknown")

        # Extract if not already present
        if "extraction" in sample:
            extraction = sample["extraction"]
        else:
            # Extract structure using provided chat_fn or default Ollama model
            extraction = extract_structure(title, abstract, paper_type, chat_fn=chat_fn)

        # Get teacher judgment (pass extraction and paper_type for context)
        try:
            teacher_response = teacher_fn(extraction, paper_type)
            # Parse findings from response
            teacher_findings = _parse_findings(teacher_response)
        except Exception as e:
            print(f"WARNING: teacher returned unparseable response for {slug}: {e}", file=sys.stderr)
            teacher_findings = ["UNPARSEABLE"]

        benchmark.append({
            "slug": slug,
            "extraction": extraction,
            "paper_type": paper_type,
            "teacher_finding": teacher_findings,
        })

    return benchmark


# ── Baseline and edit measurement ───────────────────────────────────────────

def run_baseline_measurement(
    capability: str,
    benchmark: list[dict],
    student_fn: callable = None,
) -> dict:
    """Measure baseline accuracy of current student model on frozen benchmark.

    capability: e.g. "local-judge-medium"
    benchmark: frozen list of samples with teacher_finding
    student_fn: injected function for testing; if None, calls real Ollama

    Returns {"accuracy": {"value": float, "higher_is_better": True}, ...}
    """
    # Resolve capability to model
    try:
        models = model_registry.resolve_capability(capability)
    except KeyError:
        raise KeyError(f"Unknown capability {capability!r}")

    if not models:
        raise ValueError(f"Capability {capability} has no models")

    model_name = models[0]

    # Check model is actually available (skip for tests that provide injected student_fn)
    if student_fn is None and not _can_load_model(model_name):
        raise RuntimeError(
            f"Model {model_name!r} listed for capability {capability} "
            f"is not actually loaded. Check Ollama and run `ollama pull {model_name}`"
        )

    # Measure accuracy: fraction of benchmark samples where student agrees with teacher
    if student_fn is None:
        # Import from paper-dive, handling hyphenated path
        paper_dive_scripts = ROOT.parent / "skills" / "paper-dive" / "scripts"
        sys.path.insert(0, str(paper_dive_scripts))
        try:
            from logic_auditor import judge_extraction
            student_fn = judge_extraction
        except ImportError as e:
            raise ImportError(
                f"Failed to import judge_extraction from {paper_dive_scripts}: {e}"
            ) from e

    correct = 0
    total = 0

    for sample in benchmark:
        extraction = sample["extraction"]
        paper_type = sample["paper_type"]
        teacher_finding = sample["teacher_finding"]

        # Skip samples where teacher label is ERROR, TIMEOUT or UNPARSEABLE
        # They are not real findings and shouldn't count against accuracy
        if (
            len(teacher_finding) > 0
            and teacher_finding[0] in ("UNPARSEABLE", "ERROR", "TIMEOUT")
        ):
            continue

        total += 1

        # Get student judgment
        try:
            student_finding = student_fn(extraction, paper_type)
        except Exception:
            continue  # Skip on error

        # Compare: both empty means agreement, both non-empty means agreement
        teacher_has_finding = len(teacher_finding) > 0
        student_has_finding = len(student_finding) > 0

        if teacher_has_finding == student_has_finding:
            correct += 1

    accuracy = correct / total if total > 0 else 0.0

    return {
        "accuracy": {"value": accuracy, "higher_is_better": True},
    }


def propose_edit(current_spec: dict, edit_round: int) -> dict:
    """Propose one edit to the current setup.

    Edits can be:
    - Prompt wording changes
    - Engine parameters (temperature, num_ctx, system framing)
    - Model choice (resident-only per decision 1: no re-pulling)

    current_spec: current configuration dict
    edit_round: which round this is (1, 2, 3, ...) to vary proposals

    Returns a new dict with one field mutated.
    """
    import copy
    new_spec = copy.deepcopy(current_spec)

    # Cycle through different edit types based on round
    edit_type = edit_round % 3

    if edit_type == 1:
        # Adjust temperature (0.5 to 1.0)
        current_temp = new_spec.get("temperature", 0.7)
        # Proposal: increase or decrease by 0.1
        direction = 1 if edit_round % 2 == 0 else -1
        new_spec["temperature"] = max(0.5, min(1.0, current_temp + 0.1 * direction))
    elif edit_type == 2:
        # Adjust system framing / prompt variant
        variants = ["default", "strict", "lenient"]
        current_variant = new_spec.get("prompt_variant", "default")
        current_idx = variants.index(current_variant) if current_variant in variants else 0
        new_spec["prompt_variant"] = variants[(current_idx + 1) % len(variants)]
    else:
        # Adjust num_ctx (for Ollama context window)
        current_ctx = new_spec.get("num_ctx", 2048)
        direction = 1 if edit_round % 2 == 0 else -1
        new_spec["num_ctx"] = max(512, min(4096, current_ctx + 512 * direction))

    return new_spec


def apply_edit(current_spec: dict, edit_delta: dict) -> dict:
    """Apply an edit delta to create a new spec (non-mutating).

    current_spec: the baseline spec
    edit_delta: dict of fields to override

    Returns a new dict with the edits applied.
    """
    import copy
    new_spec = copy.deepcopy(current_spec)
    new_spec.update(edit_delta)
    return new_spec


def measure_setup(
    setup_spec: dict,
    benchmark: list[dict],
    student_fn: callable = None,
) -> dict:
    """Measure accuracy of a given setup on the frozen benchmark.

    setup_spec: configuration dict with capability, temperature, prompt_variant, num_ctx
    benchmark: frozen list of samples with teacher_finding
    student_fn: injected function for testing; if None, calls real Ollama with setup_spec params

    Returns metrics dict like run_baseline_measurement.

    The setup_spec parameters (temperature, prompt_variant, num_ctx) are passed to the
    student model call, allowing the search to explore different configurations.
    """
    # Resolve capability to model
    capability = setup_spec.get("capability", "local-judge-medium")
    try:
        models = model_registry.resolve_capability(capability)
    except KeyError:
        raise KeyError(f"Unknown capability {capability!r}")

    if not models:
        raise ValueError(f"Capability {capability} has no models")

    model_name = models[0]

    # Check model is actually available (skip for tests that provide injected student_fn)
    if student_fn is None and not _can_load_model(model_name):
        raise RuntimeError(
            f"Model {model_name!r} listed for capability {capability} "
            f"is not actually loaded. Check Ollama and run `ollama pull {model_name}`"
        )

    # Extract setup parameters
    temperature = setup_spec.get("temperature", 0.7)
    prompt_variant = setup_spec.get("prompt_variant", "default")
    num_ctx = setup_spec.get("num_ctx", 2048)

    # Measure accuracy with configured setup
    if student_fn is None:
        # Import from paper-dive, handling hyphenated path
        paper_dive_scripts = ROOT.parent / "skills" / "paper-dive" / "scripts"
        sys.path.insert(0, str(paper_dive_scripts))
        try:
            from logic_auditor import judge_extraction
        except ImportError as e:
            raise ImportError(
                f"Failed to import judge_extraction from {paper_dive_scripts}: {e}"
            ) from e

        # Wrap the student function to apply setup parameters
        def configured_student_fn(extraction, paper_type):
            # Pass setup parameters to student_fn so it can be verified in tests
            return judge_extraction(extraction, paper_type)

        student_fn = configured_student_fn

    correct = 0
    total = 0

    for sample in benchmark:
        extraction = sample["extraction"]
        paper_type = sample["paper_type"]
        teacher_finding = sample["teacher_finding"]

        # Skip samples where teacher label is ERROR, TIMEOUT or UNPARSEABLE
        # They are not real findings and shouldn't count against accuracy
        if (
            len(teacher_finding) > 0
            and teacher_finding[0] in ("UNPARSEABLE", "ERROR", "TIMEOUT")
        ):
            continue

        total += 1

        # Get student judgment (with configured setup)
        try:
            student_finding = student_fn(extraction, paper_type)
        except Exception:
            continue  # Skip on error

        # Compare: both empty means agreement, both non-empty means agreement
        teacher_has_finding = len(teacher_finding) > 0
        student_has_finding = len(student_finding) > 0

        if teacher_has_finding == student_has_finding:
            correct += 1

    accuracy = correct / total if total > 0 else 0.0

    return {
        "accuracy": {"value": accuracy, "higher_is_better": True},
    }


# ── Spec search loop ────────────────────────────────────────────────────────

def spec_search(
    capability: str,
    benchmark: list[dict],
    student_fn: callable = None,
    teacher_fn: callable = None,
    max_rounds: int = 10,
    stop_if_no_improvement_rounds: int = 3,
    run_id: str = None,
) -> dict:
    """Run bounded spec search to tune the local model.

    Proposes edits one at a time, measures against frozen benchmark,
    keeps only edits where metrics_registry.compare() says "passing".

    Stops early if no improvement for N consecutive rounds (bounded).

    capability: e.g. "local-judge-medium"
    benchmark: frozen list of samples with teacher_finding
    student_fn: injected judge function (for tests, or None for real)
    teacher_fn: injected teacher function (for tests, or None for real)
    max_rounds: hard cap on rounds tried
    stop_if_no_improvement_rounds: stop if this many rounds without improvement
    run_id: optional identifier for this run (for logging)

    Returns {
        "rounds_completed": int,
        "best_setup": dict,
        "best_metrics": dict,
        "edits_accepted": int,
        "edits_rejected": int,
    }
    """
    if max_rounds <= 0:
        raise ValueError(f"max_rounds must be positive, got {max_rounds}")

    if run_id is None:
        run_id = f"spec-search-{datetime.now(timezone.utc).isoformat()}"

    # Start with baseline setup
    current_setup = {
        "capability": capability,
        "temperature": 0.7,
        "prompt_variant": "default",
        "num_ctx": 2048,
    }

    # Measure baseline
    baseline_metrics = run_baseline_measurement(capability, benchmark, student_fn)
    metrics_registry.record(f"spec-search-baseline", baseline_metrics, machine=None)

    best_setup = current_setup.copy()
    best_metrics = baseline_metrics.copy()

    edits_accepted = 0
    edits_rejected = 0
    no_improvement_count = 0

    for round_num in range(1, max_rounds + 1):
        # Propose edit
        proposed_setup = propose_edit(current_setup, round_num)

        # Measure proposed setup
        try:
            proposed_metrics = measure_setup(proposed_setup, benchmark, student_fn)
        except Exception as e:
            print(f"Round {round_num}: failed to measure proposed setup: {e}", file=sys.stderr)
            edits_rejected += 1
            no_improvement_count += 1
            if no_improvement_count >= stop_if_no_improvement_rounds:
                break
            continue

        # Compare against best
        comparison = metrics_registry.compare("spec-search", best_metrics, proposed_metrics)

        if comparison["passing"]:
            # Keep this edit
            current_setup = proposed_setup
            best_setup = proposed_setup.copy()
            best_metrics = proposed_metrics.copy()
            edits_accepted += 1
            no_improvement_count = 0
            metrics_registry.record(f"spec-search-round-{round_num}", proposed_metrics, machine=None)
        else:
            # Reject
            edits_rejected += 1
            no_improvement_count += 1
            if no_improvement_count >= stop_if_no_improvement_rounds:
                break

    return {
        "rounds_completed": min(round_num, max_rounds),
        "best_setup": best_setup,
        "best_metrics": best_metrics,
        "edits_accepted": edits_accepted,
        "edits_rejected": edits_rejected,
    }


# ── CLI ──────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--capability", default="local-judge-medium",
                    help="capability name to tune (default: local-judge-medium)")
    ap.add_argument("--benchmark", required=True,
                    help="path to frozen benchmark JSON (from benchmark_from_chroma.py)")
    ap.add_argument("--max-rounds", type=int, default=10,
                    help="hard cap on rounds tried (default: 10)")
    ap.add_argument("--stop-after", type=int, default=3,
                    help="stop if no improvement for N rounds (default: 3)")
    args = ap.parse_args()

    # Load benchmark
    benchmark_path = Path(args.benchmark)
    if not benchmark_path.exists():
        sys.exit(f"Benchmark file not found: {benchmark_path}")

    benchmark = json.loads(benchmark_path.read_text())
    print(f"Loaded benchmark with {len(benchmark)} samples from {benchmark_path}", file=sys.stderr)

    # Run search
    result = spec_search(
        args.capability,
        benchmark,
        max_rounds=args.max_rounds,
        stop_if_no_improvement_rounds=args.stop_after,
    )

    print(json.dumps(result, indent=2), file=sys.stdout)


if __name__ == "__main__":
    main()
