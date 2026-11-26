#!/usr/bin/env python3
"""spec_search.py — bounded prompt/settings search for paper-dive inference.

Finds a spec (prompt/model/options) that maximizes performance on a fixed
benchmark. Uses Claude as the propose_fn to suggest edits; each edit is
gated by deterministic fixture-based scoring (never learned from Claude-
generated labels, keeping this a prompt search per ADR 0085 point 6).

Usage (after `bench/tasks/task-0XX-paperdive-*` fixtures are built):
    python3 bench/spec_search.py bench/tasks/task-020-paperdive-judge-strongreject
    python3 bench/spec_search.py bench/tasks/task-022-paperdive-inference-strongreject --max-iterations 5
"""
from __future__ import annotations
import copy
import json
import sys
import time
from pathlib import Path
from typing import Callable, TypedDict

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent / "lib"))
import model_registry  # noqa: E402


class SpecEditResult(TypedDict, total=False):
    """Result of an edit proposal."""
    temperature: float | None
    format: str | None
    num_predict: int | None
    prompt: str | None


class FixtureCase(TypedDict, total=False):
    """A single test case in a fixture."""
    id: str
    input_text: str
    ground_truth: str
    expected_output: str


def load_fixtures(task_dir: Path) -> list[FixtureCase]:
    """Load fixtures from a task directory. For now, fixtures are encoded
    in the task.json's prompt_file and expected answers.

    Raises:
        ValueError: If ground_truth is missing or contradictory.
    """
    task_json = task_dir / "task.json"
    if not task_json.exists():
        raise FileNotFoundError(f"No task.json in {task_dir}")

    task = json.loads(task_json.read_text())
    prompt_file = task_dir / task.get("prompt_file", "prompt.md")

    if not prompt_file.exists():
        raise FileNotFoundError(f"No prompt file at {prompt_file}")

    expect = task.get("expect", [])
    if not expect:
        raise ValueError(f"Task {task_dir} has no 'expect' field for ground truth")

    # Store expect as a JSON list (keeps multi-word expectations as single units)
    fixtures = [
        FixtureCase(
            id=task["id"],
            input_text=prompt_file.read_text(),
            ground_truth=json.dumps(expect),
            expected_output=json.dumps(expect),
        )
    ]

    return fixtures


def evaluate_spec(
    spec: dict,
    fixtures: list[FixtureCase],
    chat_fn: Callable[[str, dict, str], str],
) -> dict:
    """Evaluate a spec (prompt/model/options) against fixtures.

    Args:
        spec: Dict with 'prompt', 'model', 'options', etc.
        fixtures: List of FixtureCase to test against
        chat_fn: Function to call for inference (signature: (input_text, spec, model) -> response)

    Returns:
        {"score": 0.0-1.0, "passed": N, "failed": N, "errors": N, "cases": [...]}

    Raises:
        ValueError: If a fixture is malformed or missing ground truth.
    """
    if not fixtures:
        return {"score": 0.0, "passed": 0, "failed": 0, "errors": 0, "cases": []}

    for fixture in fixtures:
        if "ground_truth" not in fixture or not fixture["ground_truth"]:
            raise ValueError(f"Fixture {fixture.get('id', 'unknown')} missing ground_truth")

    passed = 0
    failed = 0
    errors = 0
    cases = []

    for fixture in fixtures:
        try:
            # Actually use the spec: prompt, model, options
            response = chat_fn(fixture["input_text"], spec, spec.get("model", "qwen2.5:7b"))
            # Parse expectation list from JSON; check each as case-sensitive substring
            expect_list = json.loads(fixture.get("ground_truth", "[]"))
            matched = all(exp in response for exp in expect_list)
            if matched:
                passed += 1
                status = "pass"
            else:
                failed += 1
                status = "fail"
            cases.append({
                "id": fixture["id"],
                "status": status,
                "response_len": len(response),
            })
        except Exception as e:
            errors += 1
            cases.append({
                "id": fixture["id"],
                "status": "error",
                "error": str(e),
            })

    score = passed / len(fixtures) if fixtures else 0.0
    return {
        "score": score,
        "passed": passed,
        "failed": failed,
        "errors": errors,
        "cases": cases,
    }


def propose_edit(
    current_spec: dict,
    failing_cases: list[FixtureCase],
    propose_fn: Callable[[dict], SpecEditResult],
    fixtures: list[FixtureCase],
) -> dict | None:
    """Propose and validate an edit to the spec.

    Builds a payload for propose_fn that explicitly does NOT include ground
    truth (per Decision training-signal), asks for an edit, parses and
    validates it, and returns the edited spec or None if invalid.

    Args:
        current_spec: Current prompt/model/options dict
        failing_cases: Cases where current_spec is failing
        propose_fn: Function to suggest an edit (receives prompt dict, returns SpecEditResult)
        fixtures: All fixtures (used for validation)

    Returns:
        Edited spec dict (merged with current_spec), or None if the edit is invalid/no-op

    Raises:
        On network/parsing errors, unless caught and reported as None.
    """
    if not failing_cases:
        return None

    # Build payload WITHOUT ground truth
    payload = {
        "current_spec": current_spec,
        "failing_case_count": len(failing_cases),
        "failing_cases": [
            {
                "id": case["id"],
                "input": case["input_text"][:500],  # Truncate to avoid token explosion
                # EXPLICITLY DO NOT INCLUDE: ground_truth or expected_output
            }
            for case in failing_cases[:3]  # Limit to 3 cases to stay tractable
        ],
        "instruction": (
            "The above cases are failing. Suggest ONE small edit to the prompt, "
            "model options (temperature, num_predict), or format constraint that "
            "might help. Return your suggestion as JSON with keys: prompt (new prompt "
            "string or null), temperature (float or null), format (string or null), "
            "num_predict (int or null). Keep changes minimal."
        ),
    }

    try:
        response = propose_fn(payload)
    except Exception:
        return None

    if not response or not isinstance(response, dict):
        return None  # No-op or malformed

    # Check for no-op: all proposed edits are None/unchanged
    has_change = False
    for key in ["prompt", "temperature", "format", "num_predict"]:
        proposed_val = response.get(key)
        if proposed_val is not None and proposed_val != current_spec.get(key):
            has_change = True
            break

    if not has_change:
        return None  # No-op

    # Merge proposal into current_spec (deep copy to avoid mutating best_spec)
    merged = copy.deepcopy(current_spec)

    # Handle top-level edits
    if response.get("prompt") is not None:
        merged["prompt"] = response["prompt"]

    # Handle options (nested dict)
    if "options" not in merged:
        merged["options"] = {}

    for opt_key in ["temperature", "format", "num_predict"]:
        if response.get(opt_key) is not None:
            merged["options"][opt_key] = response[opt_key]

    return merged


def search_loop(
    task_dir: Path,
    fixtures: list[FixtureCase],
    propose_fn: Callable[[dict], SpecEditResult],
    chat_fn: Callable[[str], str],
    max_iterations: int = 10,
    regression_reject: bool = True,
) -> dict:
    """Bounded spec search loop.

    Args:
        task_dir: Task directory for naming results
        fixtures: List of fixture cases
        propose_fn: Function to propose edits
        chat_fn: Function to evaluate specs
        max_iterations: Max search iterations (hard cap)
        regression_reject: If True, reject edits that break previously passing cases

    Returns:
        {"best_spec": {...}, "best_score": 0.0-1.0, "trace": [...], "iterations": N}
    """
    initial_spec = {
        "prompt": "default",
        "model": "qwen2.5:7b",
        "options": {},
    }

    best_spec = initial_spec
    best_result = evaluate_spec(initial_spec, fixtures, chat_fn)
    best_score = best_result["score"]
    best_passing = set(c["id"] for c in best_result["cases"] if c["status"] == "pass")

    trace = []

    for iteration in range(max_iterations):
        failing = [f for f in fixtures if f["id"] not in best_passing]
        if not failing:
            break  # Already perfect

        proposed = propose_edit(best_spec, failing, propose_fn, fixtures)
        if not proposed:
            break  # No more progress

        result = evaluate_spec(proposed, fixtures, chat_fn)
        new_passing = set(c["id"] for c in result["cases"] if c["status"] == "pass")

        # Regression check: reject if any previously passing case now fails
        if regression_reject and (best_passing - new_passing):
            # Regressed: reject
            trace.append({
                "iteration": iteration,
                "action": "rejected (regression)",
                "score": result["score"],
                "regressed_count": len(best_passing - new_passing),
            })
            continue

        # Improvement or no regression: accept if score improved
        if result["score"] > best_score:
            best_spec = proposed
            best_score = result["score"]
            best_passing = new_passing
            trace.append({
                "iteration": iteration,
                "action": "accepted",
                "score": best_score,
                "passed": result["passed"],
                "failed": result["failed"],
            })
        else:
            # No improvement, stop
            trace.append({
                "iteration": iteration,
                "action": "rejected (no improvement)",
                "score": result["score"],
            })
            break

    return {
        "best_spec": best_spec,
        "best_score": best_score,
        "trace": trace,
        "iterations": len(trace),
    }


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("task_dir", help="Bench task directory")
    ap.add_argument("--max-iterations", type=int, default=10)
    args = ap.parse_args()

    task_dir = Path(args.task_dir)
    fixtures = load_fixtures(task_dir)

    raise RuntimeError(
        "spec_search.py requires real chat_fn and propose_fn implementations. "
        "Cannot run with dummy functions. Use via spec_search module in tests or "
        "pass real Claude-based functions in a wrapper script."
    )
