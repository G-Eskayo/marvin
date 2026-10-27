"""Compare baseline vs after-task build metrics to determine if a solution is correct.

Used to gate whether an offline code task was completed successfully by comparing
type checking, linting, and test results before and after.
"""
from __future__ import annotations
from dataclasses import dataclass
from build_type_measure import BuildMeasure


@dataclass
class GateVerdict:
    """Result of comparing baseline vs after-task metrics."""
    passed: bool
    reason: str
    baseline: BuildMeasure
    after_task: BuildMeasure


def compare(baseline: BuildMeasure, after_task: BuildMeasure) -> GateVerdict:
    """Compare baseline and after-task measurements to determine if the task passed.

    Verdict is: did the after-task run maintain or improve the baseline?
    - Type check errors must not increase
    - Lint warnings must not increase significantly
    - Tests must pass (if baseline passed)
    - No new build failures
    """
    reasons: list[str] = []

    # Type check: errors shouldn't increase
    if after_task.type_check_errors > baseline.type_check_errors:
        reasons.append(
            f"Type check errors increased: "
            f"{baseline.type_check_errors} → {after_task.type_check_errors}"
        )

    # Linting: warnings shouldn't increase significantly (allow +5%)
    lint_threshold = int(baseline.lint_warnings * 1.05) + 2
    if after_task.lint_warnings > lint_threshold:
        reasons.append(
            f"Lint warnings increased: "
            f"{baseline.lint_warnings} → {after_task.lint_warnings}"
        )

    # Tests: if baseline passed, after-task must pass
    if baseline.tests_pass and not after_task.tests_pass:
        reasons.append(
            f"Tests regressed: "
            f"{baseline.tests_failed} failed → {after_task.tests_failed} failed"
        )

    # Build must not be broken
    if not after_task.type_check_pass and baseline.type_check_pass:
        reasons.append("Build type check failed")

    passed = len(reasons) == 0
    reason = "; ".join(reasons) if reasons else "All checks passed"

    return GateVerdict(
        passed=passed,
        reason=reason,
        baseline=baseline,
        after_task=after_task,
    )
