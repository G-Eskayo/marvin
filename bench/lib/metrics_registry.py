#!/usr/bin/env python3
"""metrics_registry.py — record and compare performance metrics.

Provides functions to record baseline measurements, compare against new measurements,
and persist metrics to disk for tracking performance improvements over time.

Usage:
    metrics_registry.record("my-run", {"accuracy": {"value": 0.95, "higher_is_better": True}})
    baseline = metrics_registry.latest("my-run")
    comparison = metrics_registry.compare("subsystem", baseline, current)
    if comparison["passing"]:
        # Accept the new measurement
"""
from __future__ import annotations
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Directory where metrics snapshots are stored (can be overridden in tests)
METRICS_DIR = Path.home() / ".agents" / "bench" / "metrics"


def _ensure_metrics_dir():
    """Create METRICS_DIR if it doesn't exist."""
    METRICS_DIR.mkdir(parents=True, exist_ok=True)


def _write_atomic(path: Path, content: str):
    """Write content to path atomically (write to temp file, then rename).

    Prevents partial writes if the process is interrupted.
    Uses fcntl locking on Unix to serialize concurrent writes.
    """
    import fcntl

    _ensure_metrics_dir()
    parent = path.parent
    parent.mkdir(parents=True, exist_ok=True)

    # Create a lock file to serialize writes
    lock_path = Path(path.parent) / f".{path.name}.lock"

    # Open lock file with exclusive lock
    with open(lock_path, "w") as lock_file:
        try:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)

            # Now do the atomic write
            with tempfile.NamedTemporaryFile(
                mode="w",
                dir=parent,
                delete=False,
                suffix=".tmp",
            ) as tmp:
                tmp.write(content)
                tmp_path = tmp.name

            # Atomic rename
            os.replace(tmp_path, path)
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def record(run_name: str, metrics: dict, machine: str = None):
    """Record a metrics measurement.

    run_name: identifier for this measurement (e.g., "spec-search-baseline")
    metrics: dict of metric_name -> {"value": float, "higher_is_better": bool}
    machine: optional machine name (for cross-machine tracking)

    Appends the measurement to the run's snapshot file, creating it if needed.
    Concurrency-safe: the lock is held for the entire read-append-write sequence.
    """
    import fcntl

    _ensure_metrics_dir()

    # Construct snapshot filename
    snapshot_file = METRICS_DIR / f"{run_name}.json"

    # Create a lock file to serialize record operations
    lock_path = Path(snapshot_file.parent) / f".{snapshot_file.name}.lock"

    # Open lock file with exclusive lock
    with open(lock_path, "w") as lock_file:
        try:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)

            # Load existing snapshots or create empty list (inside lock)
            if snapshot_file.exists():
                try:
                    snapshots = json.loads(snapshot_file.read_text())
                except (json.JSONDecodeError, IOError):
                    snapshots = []
            else:
                snapshots = []

            # Create new snapshot entry
            snapshot = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "machine": machine,
                "metrics": metrics,
            }

            # Append to list
            snapshots.append(snapshot)

            # Write atomically (still inside lock)
            _write_atomic(snapshot_file, json.dumps(snapshots, indent=2))
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def _load_snapshots(run_name: str) -> list[dict]:
    """Load all snapshots for a given run.

    Returns list of snapshot dicts, or empty list if no snapshots exist.
    """
    snapshot_file = METRICS_DIR / f"{run_name}.json"

    if not snapshot_file.exists():
        return []

    try:
        return json.loads(snapshot_file.read_text())
    except (json.JSONDecodeError, IOError):
        return []


def latest(run_name: str) -> dict | None:
    """Get the most recent metrics for a run.

    Returns the latest metrics dict, or None if no snapshots exist.
    """
    snapshots = _load_snapshots(run_name)
    if not snapshots:
        return None
    return snapshots[-1]["metrics"]


def compare(subsystem: str, baseline: dict | None, current: dict, tolerance: float = 0.001) -> dict:
    """Compare current metrics against baseline.

    baseline: dict of metric -> {"value": float, "higher_is_better": bool}, or None
    current: dict of metric -> {"value": float, "higher_is_better": bool}
    tolerance: relative tolerance for considering values "unchanged" (default 0.1%, or 0.001)

    Returns {
        "passing": bool,  # True if current should be accepted (improved or unchanged is treated as not passing)
        "verdict": str,   # "improved", "regressed", "mixed", "unchanged", "no_baseline"
        "details": dict,  # Details of the comparison
    }

    An edit only "passes" if it strictly improves at least one metric and doesn't regress others.
    Changes within tolerance are treated as "unchanged" (not passing).
    """
    if baseline is None:
        return {
            "passing": False,
            "verdict": "no_baseline",
            "details": "No baseline to compare against",
        }

    verdict_parts = []
    all_passed = True
    any_improved = False

    # Check each metric
    for metric_name in current:
        if metric_name not in baseline:
            continue

        baseline_val = baseline[metric_name]["value"]
        current_val = current[metric_name]["value"]
        higher_is_better = current[metric_name].get("higher_is_better", True)

        # Calculate relative change
        if baseline_val == 0:
            relative_change = abs(current_val - baseline_val)
        else:
            relative_change = abs(current_val - baseline_val) / abs(baseline_val)

        # Check if within tolerance (treat as unchanged)
        is_unchanged = relative_change <= tolerance

        if higher_is_better:
            if current_val > baseline_val and not is_unchanged:
                verdict_parts.append(f"{metric_name}: improved ({baseline_val:.4f} -> {current_val:.4f})")
                any_improved = True
            elif is_unchanged or current_val == baseline_val:
                verdict_parts.append(f"{metric_name}: unchanged ({current_val:.4f})")
            else:
                verdict_parts.append(f"{metric_name}: regressed ({baseline_val:.4f} -> {current_val:.4f})")
                all_passed = False
        else:
            if current_val < baseline_val and not is_unchanged:
                verdict_parts.append(f"{metric_name}: improved ({baseline_val:.4f} -> {current_val:.4f})")
                any_improved = True
            elif is_unchanged or current_val == baseline_val:
                verdict_parts.append(f"{metric_name}: unchanged ({current_val:.4f})")
            else:
                verdict_parts.append(f"{metric_name}: regressed ({baseline_val:.4f} -> {current_val:.4f})")
                all_passed = False

    # Determine overall verdict
    if any_improved and all_passed:
        overall_verdict = "improved"
        passing = True
    elif any_improved and not all_passed:
        overall_verdict = "mixed"
        passing = False
    elif not any_improved and all_passed:
        overall_verdict = "unchanged"
        passing = False
    else:
        overall_verdict = "regressed"
        passing = False

    return {
        "passing": passing,
        "verdict": overall_verdict,
        "details": "\n".join(verdict_parts),
    }
