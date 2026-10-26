#!/usr/bin/env python3
"""Write spike run results to bench/RESULTS.md.

Appends a new "Run N — opencode+Ollama spike" section in the same format
as existing Runs 1-2, with a table and summary paragraph.
"""
from __future__ import annotations
import json
import re
from datetime import datetime
from pathlib import Path


def _count_existing_runs(results_md: Path) -> int:
    """Count how many "Run N —" sections already exist in RESULTS.md."""
    if not results_md.exists():
        return 0
    text = results_md.read_text()
    matches = re.findall(r"## Run (\d+) —", text)
    return int(matches[-1]) if matches else 0


def _format_results_table(results: list[dict]) -> str:
    """Format spike results as a markdown table."""
    lines = [
        "| Task | PR | Size | Kind | Tokens | Energy (J) | Gate | Wall (s) |",
        "|------|----|----|------|--------|-----------|------|----------|",
    ]

    for r in results:
        task_id = r.get("task_id", "?")
        pr_num = task_id.replace("spike-", "")
        size = r.get("diff_size", "?")
        kind = r.get("kind", "?")

        # Tokens: sum of prompt + gen
        prompt_tok = r.get("usage", {}).get("prompt_tokens", 0)
        gen_tok = r.get("usage", {}).get("gen_tokens", 0)
        tokens = prompt_tok + gen_tok

        # Energy: check availability
        energy_data = r.get("energy")
        if energy_data and energy_data.get("available"):
            energy_str = f"{energy_data.get('joules', 0):.1f}"
        else:
            energy_str = "N/A"

        # Gate: ok/kind
        gate = r.get("gate", {})
        gate_str = "✓" if gate.get("ok") else f"✗ ({gate.get('kind', 'error')})"

        wall = r.get("wall_s", "?")

        lines.append(
            f"| {task_id} | #{pr_num} | {size} | {kind} | {tokens} | {energy_str} | {gate_str} | {wall} |"
        )

    return "\n".join(lines)


def _format_summary_paragraph(results: list[dict]) -> str:
    """Write a summary paragraph with key findings."""
    total = len(results)
    passed = sum(1 for r in results if r.get("gate", {}).get("ok"))
    total_tokens = sum(r.get("usage", {}).get("prompt_tokens", 0) + r.get("usage", {}).get("gen_tokens", 0) for r in results)
    avg_tokens = total_tokens // total if total > 0 else 0

    energy_available = [r for r in results if r.get("energy", {}).get("available")]
    if energy_available:
        total_joules = sum(r.get("energy", {}).get("joules", 0) for r in energy_available)
        energy_str = f"\nEnergy: {total_joules:.1f} Joules total ({len(energy_available)} samples available)."
    else:
        energy_str = ""

    paragraph = (
        f"### Findings\n\n"
        f"Ran {total} tasks via `opencode` with local Ollama (`{total}` gate passes out of {total}). "
        f"Average tokens per task: {avg_tokens}. "
        f"Total tokens: {total_tokens}.{energy_str}\n\n"
        f"**Recommendation:** {'Small-ticket lane is viable with local models.' if passed == total else 'Local models need improvement or task selection bias.'}"
    )
    return paragraph


def append_run_to_results(
    results_md: Path,
    run_results: list[dict],
    task_metadata: dict | None = None,
) -> None:
    """Append a new "Run N" section to RESULTS.md.

    Args:
        results_md: Path to bench/RESULTS.md
        run_results: List of per-task result dicts from spike_opencode_ollama.py
        task_metadata: Optional dict with run_date, model, notes, etc.
    """
    # Ensure directory exists
    results_md.parent.mkdir(parents=True, exist_ok=True)

    # Count existing runs
    run_number = _count_existing_runs(results_md) + 1

    # Format new run section
    date_str = datetime.now().strftime("%Y-%m-%d")
    model_info = (task_metadata or {}).get("model", "qwen2.5:7b")

    new_section = (
        f"\n## Run {run_number} — {date_str} (opencode+Ollama spike)\n\n"
        f"Spike testing whether local models (Ollama) can handle small tickets via `opencode`, "
        f"with usage and energy telemetry. Model: `{model_info}`.\n\n"
        f"{_format_results_table(run_results)}\n\n"
        f"{_format_summary_paragraph(run_results)}\n\n"
    )

    # Append to RESULTS.md
    if results_md.exists():
        existing = results_md.read_text()
        results_md.write_text(existing + "\n---\n" + new_section)
    else:
        header = "# marvin-bench — results log\n"
        results_md.write_text(header + new_section)


def write_raw_results(
    results_dir: Path,
    run_results: list[dict],
) -> Path:
    """Write raw per-run JSON to bench/results/.

    Returns the path to the written file.
    """
    results_dir.mkdir(parents=True, exist_ok=True)

    timestamp = int(__import__("time").time())
    results_file = results_dir / f"spike-run-{timestamp}.json"
    results_file.write_text(json.dumps(run_results, indent=2) + "\n")

    return results_file
