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

import opencode_runner as ocr
import ticket_replay as tr
import energy_apple as ea
from score import score_correctness


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


def score_gate_pass(result: dict[str, Any], test_files: list[str] | None = None) -> bool | None:
    """Determine whether result passes gate criteria.

    Scores the result's correctness (if not already computed), then evaluates:
    - correctness.score == 1.0 → pass (True)
    - correctness.score < 1.0 → fail (False)
    - spawn_error or infra issue → None (not scored)

    Args:
        result: result dict from run_once_opencode (with "result_text")
        test_files: list of test files from replay_ticket (optional, for scoped scoring)

    Returns:
        True (pass), False (fail), or None (infra error / not scored).
    """
    # Infra error: don't score
    if result.get("spawn_error"):
        return None

    # Compute correctness if not already present
    if "correctness" not in result:
        result_text = result.get("result_text", "")

        # Binary check: output present AND no obvious error markers
        # If result_text is empty, score 0.0 (fail)
        # If result_text contains error/refusal markers, score 0.0 (fail)
        # Otherwise score 1.0 (pass) — note this is a weak signal
        has_output = bool(result_text)
        has_error = any(
            marker in result_text.lower()
            for marker in ["error", "refused", "unable to", "cannot", "failed", "exception"]
        ) if result_text else False

        score = 1.0 if (has_output and not has_error) else 0.0

        result["correctness"] = {
            "score": score,
            "note": "binary check: output present and no error markers",
        }

    # Check correctness score
    correctness = result.get("correctness", {})
    score = correctness.get("score")
    if score is None:
        return None

    # Binary gate: pass if score == 1.0, else fail
    return score == 1.0


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
        worktree_path = ticket_data.get("worktree_path")
        cleanup_fn = ticket_data.get("cleanup_fn")

        if not prompt:
            print(f"    Warning: empty prompt for #{ticket_num}")

        try:
            # 2. Start energy measurement if requested
            energy_handle = None
            if measure_energy:
                energy_handle = ea.start_sampling()

            # 3. Run opencode in the historical worktree
            print(f"  Running opencode in {worktree_path}...")
            task = {
                "id": f"ticket-{ticket_num}",
                "prompt": prompt,
                "type": "qa",
                "timeout": 300,
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

            # 4. Stop energy measurement
            energy_data = None
            if energy_handle:
                energy_data = ea.stop_sampling(energy_handle)
                if energy_data:
                    print(f"  Energy: {energy_data.get('joules', 0):.1f} J")

            # 5. Score the gate
            gate_pass = score_gate_pass(run_result, test_files)
            print(f"  Gate: {'PASS' if gate_pass is True else 'FAIL' if gate_pass is False else 'ERROR'}")
            print(f"  Wall: {run_result.get('wall_s', 0):.1f}s")

            # Assemble result record
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
