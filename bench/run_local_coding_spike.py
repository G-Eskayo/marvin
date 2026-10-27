#!/usr/bin/env python3
"""Local coding assistant spike: run small real tickets against local Ollama.

Measures whether a local open-source model (via Ollama) can handle small code fixes
efficiently compared to cloud Claude. Runs 5 real merged PRs from the repo at their
base commits, measures energy, build metrics, and wall time.

Usage:
    python3 run_local_coding_spike.py
    python3 run_local_coding_spike.py --model qwen2.5:7b
    python3 run_local_coding_spike.py --skip-energy
"""
from __future__ import annotations
import argparse
import json
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict, dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "lib"))

from bench import load_task  # noqa: E402
from build_type_measure import measure as measure_build, BuildMeasure  # noqa: E402
from energy_apple import measure_subprocess, EnergyMeasure  # noqa: E402
from evidence_capture import capture_snapshot, CodeSnapshot  # noqa: E402
from metrics_registry import compare as compare_metrics  # noqa: E402


@dataclass
class TicketRunResult:
    """Result of running one real-ticket task."""
    task_id: str
    pr_number: int
    passed: bool
    gate_verdict: str
    wall_s: float
    energy: EnergyMeasure | None = None
    baseline_measure: BuildMeasure | None = None
    after_measure: BuildMeasure | None = None
    evidence: CodeSnapshot | None = None
    error: str = ""

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "pr_number": self.pr_number,
            "passed": self.passed,
            "gate_verdict": self.gate_verdict,
            "wall_s": self.wall_s,
            "energy": asdict(self.energy) if self.energy else None,
            "baseline": asdict(self.baseline_measure) if self.baseline_measure else None,
            "after_task": asdict(self.after_measure) if self.after_measure else None,
            "evidence": asdict(self.evidence) if self.evidence else None,
            "error": self.error,
        }


def run_ticket(
    task_dir: Path,
    task: dict,
    ollama_model: str,
    measure_energy: bool = True,
) -> TicketRunResult:
    """Run a single real-ticket task.

    Checks out the base_sha, measures baseline, runs opencode, measures after-task,
    compares metrics, and returns results.
    """
    task_id = task.get("id", "unknown")
    pr_number = task.get("pr_number", 0)
    repo = task.get("repo", "")
    base_sha = task.get("base_sha", "")
    prompt_file = task.get("prompt_file", "prompt.md")
    timeout = task.get("timeout", 600)

    # Load prompt
    prompt_path = task_dir / prompt_file
    if not prompt_path.exists():
        return TicketRunResult(
            task_id=task_id,
            pr_number=pr_number,
            passed=False,
            gate_verdict="prompt file not found",
            wall_s=0,
            error=f"Missing {prompt_file}",
        )

    prompt = prompt_path.read_text()

    # Create temporary worktree at base_sha
    worktree_dir = Path(tempfile.mkdtemp(prefix=f"bench-{task_id}-"))
    try:
        # Clone/checkout at base_sha
        result = subprocess.run(
            ["git", "worktree", "add", str(worktree_dir), base_sha],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            return TicketRunResult(
                task_id=task_id,
                pr_number=pr_number,
                passed=False,
                gate_verdict="worktree creation failed",
                wall_s=0,
                error=result.stderr[:200],
            )

        # Measure baseline
        baseline = measure_build(worktree_dir, timeout=120)

        # Run opencode headlessly against Ollama
        start = time.time()
        opencode_cmd = [
            "claude",
            "-p",
            prompt,
            "--permission-mode",
            "bypassPermissions",
            "--model",
            ollama_model,
        ]

        if measure_energy:
            exit_code, energy, energy_error = measure_subprocess(
                opencode_cmd,
                cwd=worktree_dir,
                timeout=timeout,
            )
        else:
            energy = None
            try:
                result = subprocess.run(
                    opencode_cmd,
                    cwd=worktree_dir,
                    timeout=timeout,
                    capture_output=True,
                )
                exit_code = result.returncode
            except subprocess.TimeoutExpired:
                exit_code = -1

        wall_s = time.time() - start

        # Capture evidence
        evidence = capture_snapshot(worktree_dir)

        # Measure after-task
        after = measure_build(worktree_dir, timeout=120)

        # Compare metrics
        verdict = compare_metrics(baseline, after)

        return TicketRunResult(
            task_id=task_id,
            pr_number=pr_number,
            passed=verdict.passed,
            gate_verdict=verdict.reason,
            wall_s=wall_s,
            energy=energy,
            baseline_measure=baseline,
            after_measure=after,
            evidence=evidence,
            error="" if exit_code == 0 else f"opencode exit code: {exit_code}",
        )

    finally:
        # Clean up worktree
        try:
            subprocess.run(
                ["git", "worktree", "remove", str(worktree_dir)],
                capture_output=True,
                timeout=10,
            )
        except Exception:
            pass
        try:
            import shutil
            shutil.rmtree(worktree_dir, ignore_errors=True)
        except Exception:
            pass


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Run local coding spike: test small tickets with local Ollama model"
    )
    ap.add_argument(
        "--model",
        default="qwen2.5:7b",
        help="Ollama model to use (default: qwen2.5:7b)",
    )
    ap.add_argument(
        "--skip-energy",
        action="store_true",
        help="Skip energy measurement (requires sudo)",
    )
    ap.add_argument(
        "--tasks",
        default="task-018,task-019,task-020,task-021,task-022",
        help="Comma-separated task IDs to run",
    )
    args = ap.parse_args()

    # Load tasks
    task_ids = args.tasks.split(",")
    results: list[TicketRunResult] = []

    for task_id in task_ids:
        task_dir = ROOT / "tasks" / task_id.strip()
        if not (task_dir / "task.json").exists():
            print(f"Skipping {task_id}: task.json not found", file=sys.stderr)
            continue

        try:
            task = load_task(task_dir)
            if task.get("type") != "real-ticket":
                print(f"Skipping {task_id}: not a real-ticket task", file=sys.stderr)
                continue

            print(f"Running {task_id}...", flush=True)
            result = run_ticket(task_dir, task, args.model, measure_energy=not args.skip_energy)
            results.append(result)

            status = "✓" if result.passed else "✗"
            print(f"  {status} {result.gate_verdict} ({result.wall_s:.1f}s)", flush=True)

        except Exception as e:
            print(f"Error running {task_id}: {e}", file=sys.stderr)

    # Save results
    results_dir = ROOT / "results"
    results_dir.mkdir(exist_ok=True)
    timestamp = time.strftime("%Y%m%d-%H%M%S")
    results_file = results_dir / f"local-spike-{timestamp}.json"

    results_data = {
        "timestamp": timestamp,
        "model": args.model,
        "measure_energy": not args.skip_energy,
        "results": [r.to_dict() for r in results],
    }

    results_file.write_text(json.dumps(results_data, indent=2))
    print(f"Results saved to {results_file}", flush=True)

    # Print summary table
    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)
    print(f"{'Task':<25} {'PR':<6} {'Pass':<6} {'Wall':<8} {'Energy':<10}")
    print("-" * 80)
    for r in results:
        energy_str = f"{r.energy.wh:.3f}Wh" if r.energy else "—"
        print(f"{r.task_id:<25} {r.pr_number:<6} {str(r.passed):<6} {r.wall_s:>7.1f}s {energy_str:<10}")

    passed_count = sum(1 for r in results if r.passed)
    print(f"\nPassed: {passed_count}/{len(results)}")


if __name__ == "__main__":
    main()
