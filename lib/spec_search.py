"""
spec_search.py — specification search and optimization loop.

Implements a teacher/student pattern for iteratively improving a specification
(e.g., prompt template, model parameters) based on evaluation against gold-standard
samples. The student applies the spec to samples; the teacher observes failures
and proposes edits; the loop continues until accuracy is perfect or max iterations
are reached.

Used by judgment_benchmark.py for optimizing judgment extraction specs.
"""
from __future__ import annotations
import json
from typing import Any, Callable


def evaluate(
    spec: dict[str, Any],
    samples: list[dict[str, Any]],
    student_fn: Callable[[Any, dict[str, Any]], Any],
    score_fn: Callable[[Any, dict[str, Any]], bool],
) -> float:
    """Evaluate a spec against a set of samples.

    Args:
        spec: the specification to evaluate (e.g., model params, prompt template)
        samples: list of test samples, each with gold-standard answer
        student_fn: function(extraction, spec) -> prediction
        score_fn: function(prediction, sample) -> bool (True if correct)

    Returns:
        accuracy as a float between 0 and 1.
    """
    correct = 0
    for sample in samples:
        prediction = student_fn(sample.get("extraction", sample), spec)
        if score_fn(prediction, sample):
            correct += 1
    return correct / len(samples) if samples else 1.0


def propose_edit(
    spec: dict[str, Any],
    failing_samples: list[dict[str, Any]],
    teacher_fn: Callable[[list[dict[str, Any]], dict[str, Any]], str],
) -> dict[str, Any] | None:
    """Ask the teacher to propose an edit to the spec based on failing samples.

    Args:
        spec: current specification
        failing_samples: samples where the student failed
        teacher_fn: function(failing_samples, spec) -> JSON string

    Returns:
        parsed JSON dict of the proposed spec, or None if teacher response
        was invalid/empty JSON.
    """
    response = teacher_fn(failing_samples, spec)

    if not response or not response.strip():
        return None

    try:
        return json.loads(response)
    except json.JSONDecodeError:
        return None


def search(
    initial_spec: dict[str, Any],
    samples: list[dict[str, Any]],
    student_fn: Callable[[Any, dict[str, Any]], Any],
    teacher_fn: Callable[[list[dict[str, Any]], dict[str, Any]], str],
    score_fn: Callable[[Any, dict[str, Any]], bool],
    max_iterations: int = 10,
) -> dict[str, Any]:
    """Search for a better spec by iteratively evaluating and improving.

    Implements the keep-only-non-regressing-edit loop: propose a change,
    re-evaluate, keep it only if accuracy doesn't drop, stop early on
    perfect score or max iterations.

    Args:
        initial_spec: starting specification
        samples: evaluation samples with gold standard
        student_fn: function(extraction, spec) -> prediction
        teacher_fn: function(failing_samples, spec) -> JSON spec edit
        score_fn: function(prediction, sample) -> bool
        max_iterations: maximum number of teacher proposals to try

    Returns:
        dict with:
            "spec": final specification
            "accuracy": final accuracy
            "iterations": number of edits applied
            "history": list of (spec, accuracy) tuples from each iteration
    """
    current_spec = dict(initial_spec)
    best_spec = dict(initial_spec)
    best_accuracy = evaluate(current_spec, samples, student_fn, score_fn)

    history = [(dict(best_spec), best_accuracy)]

    for iteration in range(max_iterations):
        # Check if we've reached perfect accuracy
        if best_accuracy >= 1.0:
            break

        # Find failing samples
        failing = []
        for sample in samples:
            prediction = student_fn(sample.get("extraction", sample), current_spec)
            if not score_fn(prediction, sample):
                failing.append(sample)

        if not failing:
            # All samples pass, stop early
            break

        # Ask teacher for an edit
        proposed_spec = propose_edit(current_spec, failing, teacher_fn)

        if proposed_spec is None:
            # Teacher gave invalid response, stop
            break

        # Evaluate the proposed spec
        new_accuracy = evaluate(proposed_spec, samples, student_fn, score_fn)

        # Keep the edit only if it doesn't regress
        if new_accuracy >= best_accuracy:
            best_spec = proposed_spec
            best_accuracy = new_accuracy
            current_spec = proposed_spec

        history.append((dict(best_spec), best_accuracy))

    return {
        "spec": best_spec,
        "accuracy": best_accuracy,
        "iterations": len(history) - 1,
        "history": history,
    }
