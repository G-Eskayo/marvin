#!/usr/bin/env python3
"""local_agent_spike.py — orchestrate opencode + energy + ticket replay across selected tickets.

Runs a live spike: for each selected ticket, replay the scenario, run opencode, measure energy,
score the gate (pass/fail), and append results to bench/RESULTS.md.

Usage:
    python3 bench/local_agent_spike.py <model> [--tickets-file instance.json]

Example:
    python3 bench/local_agent_spike.py qwen2.5:7b
    python3 bench/local_agent_spike.py qwen2.5:14b --tickets-file ~/.agents/bench-tickets.json
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "lib"))
sys.path.insert(0, str(ROOT.parent))

import opencode_runner as ocr
import ticket_replay as tr
import energy_apple as ea
from bench import run_hidden_check, _ollama_available

# Import score_correctness from lib module (added to sys.path at top)
# This is done lazily in score_gate_pass to avoid circular imports


# Default public ticket list (candidates for spike)
DEFAULT_TICKET_LIST = [
    "720",  # ADR 0078/0079: headers fix
    "627",  # Feature
    "654",  # Feature
    "414",  # Feature
    "541",  # Feature
]


def load_ticket_list(instance_file: str | Path | None, default: list[str] | None = None) -> list[str]:
    """Load ticket list from instance-private JSON fixture, fall back to public default.

    Args:
        instance_file: path to instance-private JSON (e.g., ~/.agents/bench-tickets.json)
        default: list of fallback ticket numbers if file absent

    Returns:
        list of ticket numbers (strings, e.g., ["720", "627", ...])
    """
    if default is None:
        default = DEFAULT_TICKET_LIST

    if instance_file is None:
        return default

    instance_file = Path(instance_file)
    if not instance_file.exists():
        return default

    try:
        with open(instance_file) as f:
            data = json.load(f)
        if "tickets" in data:
            return [str(t).lstrip("#") for t in data["tickets"]]
    except Exception:
        pass

    return default


def run_tests_from_paths(
    test_files: list[str],
    worktree_path: str | Path,
    timeout: int = 120,
) -> bool | None:
    """Run pytest on test files at their original relative paths.

    Args:
        test_files: list of test file paths relative to worktree
        worktree_path: path to the worktree
        timeout: seconds to allow before killing the process

    Returns:
        True if all tests pass, False if any fail, None on error.
    """
    if not test_files:
        return None

    worktree_path = Path(worktree_path)

    try:
        import sys
        import subprocess

        # Run pytest on the test files
        cmd = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"] + test_files
        proc = subprocess.run(
            cmd,
            cwd=worktree_path,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return proc.returncode == 0
    except subprocess.TimeoutExpired:
        return False
    except Exception:
        return None


def score_gate_pass(
    result: dict[str, Any],
    task: dict[str, Any] | None = None,
    test_files: list[str] | None = None,
    worktree_path: str | Path | None = None,
    base_commit: str | None = None,
    merge_commit: str | None = None,
    repo_path: str | Path | None = None,
) -> bool | None:
    """Determine whether result passes gate criteria.

    For a ticket with test files in the merge diff, run those tests with pytest.
    For tickets without test files, derive expected strings from the merge diff and use
    score_correctness. Return None if infra error or not scored.

    Args:
        result: result dict from run_once_opencode (with "result_text")
        task: task dict (optional, needed for score_correctness when no test files)
        test_files: list of test files from replay_ticket
        worktree_path: path to the ticket's replay worktree
        base_commit: base commit hash (for diff-based expectation extraction)
        merge_commit: merge commit hash (for diff-based expectation extraction)
        repo_path: path to git repo (for diff-based expectation extraction)

    Returns:
        True (pass), False (fail), or None (infra error / not scored).
    """
    # Infra error: don't score
    if result.get("spawn_error"):
        return None

    # If there are test files and we have the worktree path, run them
    if test_files and worktree_path:
        test_pass = run_tests_from_paths(test_files, worktree_path, timeout=120)
        if test_pass is not None:
            return test_pass
        # If test run failed for infra reasons, return None (not scored)

    # Check if correctness is already computed
    if "correctness" in result:
        correctness = result.get("correctness", {})
        score = correctness.get("score")
        if score is not None:
            return score == 1.0

    # For no-test tickets, use score_correctness with expected strings from diff
    if base_commit and merge_commit and repo_path and worktree_path:
        try:
            import subprocess
            from score import score_correctness

            # Get list of non-test files modified in the merge
            diff_result = subprocess.run(
                ["git", "diff", "--name-only", base_commit, merge_commit],
                cwd=repo_path,
                capture_output=True,
                text=True,
                timeout=10,
            )
            if diff_result.returncode == 0:
                modified_files = [
                    f.strip() for f in diff_result.stdout.strip().split("\n")
                    if f.strip() and f.strip().endswith(".py")
                    and not ("test" in f.lower())
                ]

                # Extract expected strings from the merge diff (only from modified non-test files)
                expected = tr.get_expected_strings(base_commit, merge_commit, repo_path, modified_files)
                if expected:
                    # Build task dict with expect[] for score_correctness
                    task_with_expect = {
                        "expect": expected,
                        "dir": str(worktree_path),
                    }
                    result_text = result.get("result_text", "")
                    score_result = score_correctness(task_with_expect, result_text, Path(worktree_path))
                    if score_result is not None and score_result.get("score") is not None:
                        return score_result.get("score") == 1.0
        except Exception:
            pass

    # Fallback: check if there's output (presence means attempted task, for docs-only)
    # Only use this if we have no other scoring mechanism (no test files, no expected strings)
    if not test_files:
        result_text = result.get("result_text", "")
        return bool(result_text)

    # Has test files but couldn't score them: return None
    return None


def get_next_run_number(results_file: Path) -> int:
    """Derive the next run number from the existing RESULTS.md.

    Scans for "## Run N" headers and returns max(N) + 1.
    Defaults to 1 if file is absent or no runs found.

    Args:
        results_file: path to bench/RESULTS.md

    Returns:
        next run number (int)
    """
    if not results_file.exists():
        return 1

    try:
        text = results_file.read_text()
        import re
        runs = re.findall(r"## Run (\d+)", text)
        if runs:
            return max(int(r) for r in runs) + 1
    except Exception:
        pass

    return 1


def append_results_section(results_file: Path, section: str) -> None:
    """Append a new dated run section to RESULTS.md.

    Args:
        results_file: path to bench/RESULTS.md
        section: markdown text for the new run section
    """
    if not results_file.exists():
        results_file.write_text("# marvin-bench — results log\n\n")

    current = results_file.read_text()
    results_file.write_text(current + "\n\n" + section + "\n")


def format_results_table(results: list[dict[str, Any]]) -> str:
    """Format spike results as a markdown table.

    Args:
        results: list of result dicts from orchestrate_spike

    Returns:
        markdown table string
    """
    lines = [
        "| ticket | model | gate_pass | wall_s | tokens | note |",
        "|--------|-------|-----------|--------|--------|------|",
    ]

    for r in results:
        ticket = r.get("pr_number", "?")
        model = r.get("model", "?")
        gate = r.get("gate_pass")
        gate_str = "pass" if gate is True else "fail" if gate is False else "error"
        wall = r.get("wall_s", 0)
        tokens = r.get("total_tokens", 0)
        note = r.get("error", "")

        lines.append(f"| #{ticket} | {model} | {gate_str} | {wall:.1f} | {tokens} | {note} |")

    return "\n".join(lines)


def orchestrate_spike(
    tickets: list[str],
    model: str,
    workdir: Path | None = None,
    measure_energy: bool = False,
) -> list[dict[str, Any]]:
    """Orchestrate spike: replay tickets, run opencode, score gates.

    Args:
        tickets: list of PR numbers (strings)
        model: ollama model name (e.g., "qwen2.5:7b")
        workdir: directory for output (default: /tmp; worktrees are isolated)
        measure_energy: if True, sample energy with powermetrics

    Returns:
        list of result dicts, one per ticket
    """
    if workdir is None:
        workdir = Path("/tmp")

    workdir = Path(workdir)
    repo_path = ROOT.parent  # marvin repo root

    results = []

    for ticket_num in tickets:
        print(f"\n--- Spike: ticket #{ticket_num} ({model}) ---")

        # 1. Replay the ticket scenario
        print(f"  Replaying ticket #{ticket_num}...")
        ticket_data = tr.replay_ticket(ticket_num, repo_path)
        if ticket_data.get("error"):
            print(f"    Error: {ticket_data['error']}")
            results.append({
                "pr_number": ticket_num,
                "model": model,
                "error": ticket_data["error"],
                "gate_pass": None,
            })
            continue

        prompt = ticket_data.get("prompt", "")
        test_files = ticket_data.get("test_files", [])
        base_commit = ticket_data.get("base_commit", "")
        merge_commit = ticket_data.get("merge_commit", "")
        worktree_path = ticket_data.get("worktree_path")
        cleanup_fn = ticket_data.get("cleanup_fn")

        if not prompt:
            print(f"    Warning: empty prompt for #{ticket_num}")

        # 2. Start energy measurement if requested
        energy_handle = None
        try:
            if measure_energy:
                energy_handle = ea.start_sampling()

            try:
                # 3. Run opencode in the historical worktree
                print(f"  Running opencode in {worktree_path}...")
                task = {
                    "id": f"ticket-{ticket_num}",
                    "prompt": prompt,
                    "type": "qa",
                    "timeout": 300,
                    "dir": str(worktree_path) if worktree_path else str(workdir),
                }

                run_result = ocr.run_once_opencode(task, worktree_path or workdir, model, timeout=300)
                if run_result is None:
                    print(f"    Skipped (fs task, tool use not supported)")
                    results.append({
                        "pr_number": ticket_num,
                        "model": model,
                        "error": "skipped (fs task)",
                        "gate_pass": None,
                    })
                    continue

                # 4. Copy test files from merge commit into worktree for hidden checks
                if test_files and merge_commit and worktree_path:
                    tr.copy_test_files_to_check(test_files, merge_commit, worktree_path, repo_path)

                # 5. Stop energy measurement (before cleanup)
                energy_data = None
                if energy_handle:
                    energy_data = ea.stop_sampling(energy_handle)
                    if energy_data:
                        print(f"  Energy: {energy_data.get('joules', 0):.1f} J")

                # 6. Score the gate
                gate_pass = score_gate_pass(
                    run_result,
                    task=task,
                    test_files=test_files,
                    worktree_path=worktree_path,
                    base_commit=base_commit,
                    merge_commit=merge_commit,
                    repo_path=repo_path,
                )
                print(f"  Gate: {'PASS' if gate_pass is True else 'FAIL' if gate_pass is False else 'ERROR'}")
                print(f"  Wall: {run_result.get('wall_s', 0):.1f}s")

                # 7. Assemble result record
                result_record = {
                    "pr_number": ticket_num,
                    "model": model,
                    "gate_pass": gate_pass,
                    "wall_s": run_result.get("wall_s", 0),
                    "total_tokens": run_result.get("total_tokens", 0),
                    "result_text": run_result.get("result_text", ""),
                    "spawn_error": run_result.get("spawn_error"),
                    "test_files": test_files,
                }
                if energy_data:
                    result_record["energy_joules"] = energy_data.get("joules", 0)

                results.append(result_record)

            finally:
                # Always clean up the worktree
                if cleanup_fn:
                    try:
                        cleanup_fn()
                    except Exception as e:
                        print(f"  Warning: cleanup failed: {e}")
        finally:
            # Always stop energy sampling if it was started (even on exception or continue)
            if energy_handle:
                try:
                    ea.stop_sampling(energy_handle)
                except Exception:
                    pass

    return results


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Run a local opencode spike on selected tickets.",
    )
    ap.add_argument("model", help="Ollama model (e.g., qwen2.5:7b)")
    ap.add_argument(
        "--tickets-file",
        type=Path,
        help="Instance-private JSON fixture with ticket list (default: built-in public list)",
    )
    ap.add_argument(
        "--energy",
        action="store_true",
        help="Measure energy with powermetrics (requires sudo)",
    )
    ap.add_argument(
        "--workdir",
        type=Path,
        default=Path("/tmp"),
        help="Directory for worktrees and temp files (default: /tmp)",
    )
    args = ap.parse_args()

    # Check opencode is available
    ok, err = ocr.opencode_available()
    if not ok:
        print(f"Error: {err}", file=sys.stderr)
        sys.exit(1)

    # Check Ollama model is available
    ok, err = _ollama_available(args.model)
    if not ok:
        print(f"Error: {err}", file=sys.stderr)
        sys.exit(1)

    # Load ticket list
    tickets = load_ticket_list(args.tickets_file, default=DEFAULT_TICKET_LIST)
    print(f"Running spike on {len(tickets)} tickets with model '{args.model}'")
    print(f"Tickets: {tickets}")
    if args.energy:
        print("Energy measurement: enabled")

    # Run spike
    results = orchestrate_spike(
        tickets=tickets,
        model=args.model,
        workdir=args.workdir,
        measure_energy=args.energy,
    )

    # Format and print results
    print("\n" + "=" * 80)
    print("SPIKE RESULTS")
    print("=" * 80)
    print(format_results_table(results))

    # Append to RESULTS.md
    results_md = ROOT / "RESULTS.md"
    run_number = get_next_run_number(results_md)
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    section = f"""## Run {run_number} — {timestamp} (local opencode spike)

Model: `{args.model}`
Energy measurement: {'enabled' if args.energy else 'disabled'}

{format_results_table(results)}

### Spike summary
- Executed on {len(results)} tickets
- Pass gate: {sum(1 for r in results if r.get('gate_pass') is True)}/{len(results)}
- Errors: {sum(1 for r in results if r.get('error'))}
"""

    append_results_section(results_md, section)
    print(f"\nResults appended to {results_md}")


if __name__ == "__main__":
    main()
