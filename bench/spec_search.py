#!/usr/bin/env python3
"""spec_search.py — generic spec parameter search for judgment tasks.

Proposes edits to specs (prompt, model, settings) one at a time using a
zero-tool Claude teacher, scores them against a benchmark, and iterates until
hitting a threshold or running out of budget.

Implements the core search mechanics independent of bench.py, following the
accept/reject/stop shape from select_model.py for cost control.
"""
from __future__ import annotations
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))


BENCH_DIR = Path(__file__).resolve().parent


def _check_quota() -> dict | None:
    """Check the API account's rate limit info. Returns None if unable to determine."""
    env = dict(os.environ)
    clean_profile = BENCH_DIR / "profiles" / "clean"
    if clean_profile.exists():
        env["CLAUDE_CONFIG_DIR"] = str(clean_profile)
        for k in list(env):
            if k.startswith("CLAUDE_CODE_") or k in ("CLAUDECODE", "CLAUDE_EFFORT"):
                env.pop(k, None)
    try:
        proc = subprocess.run(
            ["claude", "-p", "ok", "--output-format", "stream-json", "--verbose",
             "--permission-mode", "bypassPermissions"],
            capture_output=True, text=True, timeout=60, env=env,
        )
    except Exception:
        return None
    for line in proc.stdout.splitlines():
        line = line.strip()
        if not line.startswith('{"type":"rate_limit_event"'):
            continue
        try:
            return json.loads(line).get("rate_limit_info")
        except Exception:
            continue
    return None


def _make_edit_proposal(
    current_spec: dict,
    benchmark_summary: str,
    budget_tokens: int | None = None,
) -> dict:
    """Use zero-tool Claude to propose a one-edit change to the spec.

    Returns {"field": str, "new_value": str, "rationale": str} or
    {"stop": True, "rationale": str} if no more promising edits exist."""

    clean_profile = BENCH_DIR / "profiles" / "clean"
    judge_env = dict(os.environ)
    if clean_profile.exists():
        judge_env["CLAUDE_CONFIG_DIR"] = str(clean_profile)
    for k in list(judge_env):
        if k.startswith("CLAUDE_CODE_") or k in ("CLAUDECODE", "CLAUDE_EFFORT"):
            judge_env.pop(k, None)

    budget_note = f"\n\nREMAINING BUDGET: {budget_tokens} tokens" if budget_tokens else ""

    prompt = f"""You are optimizing a paper-dive logic auditor specification for accuracy against a benchmark.

CURRENT SPEC:
{json.dumps(current_spec, indent=2)}

BENCHMARK SUMMARY:
{benchmark_summary}

Propose a single small edit to the spec that might improve accuracy. Consider:
- Swapping models (classify, extraction, judgment, inference)
- Tweaking prompts (making them more explicit, adding examples, clarifying criteria)
- Changing engine settings (temperature, top_k, etc.)

Each change should be defensible and minimal -- one field at a time.{budget_note}

If no promising edits remain, respond with STOP instead.

Respond in exactly one of these formats:

EDIT:
FIELD: <json path like "classify_model" or "classify_prompt">
NEW_VALUE: <new value as a string>
RATIONALE: <one sentence why this might help>

or

STOP
REASON: <why further optimization is unlikely to help>"""

    try:
        proc = subprocess.run(
            ["claude", "-p", prompt, "--output-format", "text", "--tools", ""],
            capture_output=True, text=True, timeout=90, env=judge_env
        )
        text = proc.stdout.strip()
    except Exception as exc:
        raise RuntimeError(f"edit proposal failed: {exc}") from exc

    if "EDIT" in text.upper():
        # Parse the response (check EDIT before STOP to avoid "stop" in rationale breaking it)
        field_m = __import__("re").search(r"FIELD\s*:\s*(.+?)(?=\n|$)", text, __import__("re").IGNORECASE)
        # Capture multi-line value: from NEW_VALUE: to next keyword or end
        value_m = __import__("re").search(
            r"NEW_VALUE\s*:\s*(.+?)(?=\nRATIONALE|$)",
            text, __import__("re").IGNORECASE | __import__("re").DOTALL
        )
        rationale_m = __import__("re").search(r"RATIONALE\s*:\s*(.+)", text, __import__("re").IGNORECASE)

        field = field_m.group(1).strip() if field_m else None
        new_value = value_m.group(1).strip() if value_m else None
        rationale = rationale_m.group(1).strip() if rationale_m else ""

        if field and new_value:
            # Try to parse value as JSON if it looks like one
            if new_value.startswith(('{', '[', 'true', 'false', 'null')) or new_value.lstrip('-').replace('.', '', 1).isdigit():
                try:
                    new_value = __import__("json").loads(new_value)
                except (ValueError, __import__("json").JSONDecodeError):
                    pass  # Keep as string if JSON parsing fails
            return {
                "field": field,
                "new_value": new_value,
                "rationale": rationale,
            }

    if "STOP" in text.upper():
        reason_m = __import__("re").search(r"REASON\s*:\s*(.+)", text, __import__("re").IGNORECASE)
        reason = reason_m.group(1).strip() if reason_m else text[:300]
        return {"stop": True, "rationale": reason}

    # Couldn't parse response; treat as stop
    return {"stop": True, "rationale": f"Could not parse proposal: {text[:200]}"}


def _apply_edit(spec: dict, field: str, new_value: str) -> dict:
    """Apply a single edit to the spec. field is a simple key (not a deep path for now)."""
    spec_copy = spec.copy()
    spec_copy[field] = new_value
    return spec_copy


def run_search(
    baseline_spec: dict,
    score_fn,
    benchmark: dict,
    max_iterations: int = 10,
    accuracy_threshold: float = 0.95,
    budget_tokens: int | None = None,
) -> dict:
    """Generic spec search loop.

    Args:
        baseline_spec: Starting spec
        score_fn: Function(spec, benchmark) -> {"accuracy": float, ...}
        benchmark: Benchmark data
        max_iterations: Max edits to try
        accuracy_threshold: Stop when reaching this accuracy
        budget_tokens: Token budget; None = unlimited

    Returns:
        {
            "baseline": {"spec": ..., "accuracy": ...},
            "best": {"spec": ..., "accuracy": ...},
            "trace": [{iteration, edit, accuracy, decision}, ...],
            "total_iterations": int,
            "stopped_reason": str,
        }
    """
    # Preflight: check quota
    quota = _check_quota()
    if quota:
        print(f"Rate limit info: {json.dumps(quota, indent=2)}", flush=True)

    # Baseline
    print("Scoring baseline spec...", flush=True)
    baseline_score = score_fn(baseline_spec, benchmark)
    baseline_accuracy = baseline_score.get("accuracy", 0.0)

    best_spec = baseline_spec
    best_accuracy = baseline_accuracy
    trace = []
    tokens_used = 0
    consecutive_no_change = 0

    # Build benchmark summary for the proposal function
    benchmark_summary = json.dumps(
        {
            "total_papers": len(benchmark),
            "baseline_accuracy": baseline_accuracy,
        }
    )

    print(f"Baseline accuracy: {baseline_accuracy:.2%}", flush=True)

    for iteration in range(max_iterations):
        print(f"\nIteration {iteration + 1}/{max_iterations}...", flush=True)

        # Check if we've hit the threshold
        if best_accuracy >= accuracy_threshold:
            print(f"Accuracy threshold {accuracy_threshold:.2%} reached; stopping.", flush=True)
            return {
                "baseline": {"spec": baseline_spec, "accuracy": baseline_accuracy},
                "best": {"spec": best_spec, "accuracy": best_accuracy},
                "trace": trace,
                "total_iterations": iteration,
                "stopped_reason": "threshold_reached",
            }

        # Check budget
        if budget_tokens is not None and tokens_used >= budget_tokens:
            print(f"Budget exhausted ({tokens_used} >= {budget_tokens} tokens); stopping.", flush=True)
            return {
                "baseline": {"spec": baseline_spec, "accuracy": baseline_accuracy},
                "best": {"spec": best_spec, "accuracy": best_accuracy},
                "trace": trace,
                "total_iterations": iteration,
                "stopped_reason": "budget_exhausted",
            }

        # Propose an edit
        try:
            remaining_budget = budget_tokens - tokens_used if budget_tokens else None
            proposal = _make_edit_proposal(best_spec, benchmark_summary, remaining_budget)
        except Exception as e:
            print(f"Error proposing edit: {e}", flush=True)
            return {
                "baseline": {"spec": baseline_spec, "accuracy": baseline_accuracy},
                "best": {"spec": best_spec, "accuracy": best_accuracy},
                "trace": trace,
                "total_iterations": iteration,
                "stopped_reason": f"proposal_error: {e}",
            }

        if proposal.get("stop"):
            print(f"Stopped: {proposal['rationale']}", flush=True)
            return {
                "baseline": {"spec": baseline_spec, "accuracy": baseline_accuracy},
                "best": {"spec": best_spec, "accuracy": best_accuracy},
                "trace": trace,
                "total_iterations": iteration,
                "stopped_reason": f"model_stop: {proposal['rationale']}",
            }

        field = proposal.get("field")
        new_value = proposal.get("new_value")
        rationale = proposal.get("rationale", "")

        # Validate field exists in spec
        if field not in baseline_spec:
            print(f"  Skipping: field '{field}' not in spec", flush=True)
            decision = "rejected (invalid field)"
            trace.append({
                "iteration": iteration + 1,
                "field": field,
                "new_value": new_value,
                "accuracy": best_accuracy,
                "decision": decision,
            })
            continue

        value_str = str(new_value)[:50] if isinstance(new_value, str) else str(new_value)[:50]
        print(f"  Proposed: {field} = {value_str}")
        print(f"  Rationale: {rationale}", flush=True)

        # Apply the edit
        edited_spec = _apply_edit(best_spec, field, new_value)

        # Score the edit
        print(f"  Scoring edited spec...", flush=True)
        try:
            edited_score = score_fn(edited_spec, benchmark)
            edited_accuracy = edited_score.get("accuracy", 0.0)
        except Exception as e:
            print(f"  Error scoring: {e}; skipping this edit", flush=True)
            edited_accuracy = best_accuracy - 0.01  # Reject on error
            decision = "rejected (error)"
        else:
            # Accept/reject decision with tolerance
            # Use small tolerance to handle floating point
            tolerance = 1e-6
            if edited_accuracy > best_accuracy + tolerance:
                decision = "accepted (improvement)"
                best_spec = edited_spec
                best_accuracy = edited_accuracy
                consecutive_no_change = 0
            elif abs(edited_accuracy - best_accuracy) <= tolerance:
                decision = "neutral"
                consecutive_no_change += 1
                # Keep the new spec if it doesn't regress, for diversity
                # For now, skip to avoid bloat
            else:
                decision = f"rejected (regressed to {edited_accuracy:.2%})"
                consecutive_no_change += 1

        print(f"  Accuracy: {edited_accuracy:.2%} → {decision}", flush=True)

        # Estimate tokens used (rough heuristic: 500 tokens per proposal + score)
        tokens_used += 1000

        # Append to trace before checking stop condition, so this iteration is recorded
        trace.append({
            "iteration": iteration + 1,
            "field": field,
            "new_value": new_value,
            "accuracy": edited_accuracy,
            "decision": decision,
        })

        # Stop if no improvement for several iterations
        if consecutive_no_change >= 3:
            print(f"No improvement for 3 iterations; stopping.", flush=True)
            return {
                "baseline": {"spec": baseline_spec, "accuracy": baseline_accuracy},
                "best": {"spec": best_spec, "accuracy": best_accuracy},
                "trace": trace,
                "total_iterations": iteration + 1,
                "stopped_reason": "consecutive_no_change",
            }

    # Hit max iterations
    print(f"\nMax iterations ({max_iterations}) reached.", flush=True)
    return {
        "baseline": {"spec": baseline_spec, "accuracy": baseline_accuracy},
        "best": {"spec": best_spec, "accuracy": best_accuracy},
        "trace": trace,
        "total_iterations": max_iterations,
        "stopped_reason": "max_iterations",
    }


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Generic spec parameter search.")
    ap.add_argument("--help-only", action="store_true")
    args = ap.parse_args()

    if args.help_only:
        print("This module provides run_search() and _make_edit_proposal() for spec optimization.")
        print("See run_judgment_spec_search.py for the CLI driver.")
        sys.exit(0)
