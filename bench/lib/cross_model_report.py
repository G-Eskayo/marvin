"""Cross-model aggregation — load and compare bench results across Haiku/Sonnet/Opus."""
from __future__ import annotations
import json
from pathlib import Path
from typing import TypedDict


class ResultFile(TypedDict):
    task: str
    model: str
    runner: str
    repeat: int
    judge: bool
    runs: list[dict]


class TaskModelResult(TypedDict):
    task: str
    model: str
    profile: str
    timestamp: str
    cost_usd: float
    total_tokens: int
    correctness_score: float


class DeltaRow(TypedDict):
    task: str
    tier: str
    model: str
    clean_cost: float
    marvin_cost: float
    cost_delta: float
    clean_tokens: int
    marvin_tokens: int
    token_delta: int
    clean_correctness: float
    marvin_correctness: float


def load_results(results_dir: Path, models: list[str]) -> list[ResultFile]:
    """Load all .json result files from results_dir, filter to specified models.

    models: list of model ids to include, e.g. ["default", "claude-haiku-4-5-20251001"]
    """
    results = []
    if not results_dir.exists():
        return results

    for json_file in sorted(results_dir.glob("*.json")):
        # Skip model-select files (they're metadata, not bench results)
        if "model-select" in json_file.name:
            continue

        try:
            data = json.loads(json_file.read_text())
            if data.get("model") in models:
                results.append(data)
        except Exception:
            pass

    return results


def latest_per_task_model(results: list[ResultFile]) -> dict[tuple[str, str], dict]:
    """Deduplicate to newest run per (task, model).

    Returns: dict mapping (task_id, model) to the newest result entry.
    """
    latest = {}

    for result_file in results:
        task = result_file["task"]
        model = result_file["model"]
        key = (task, model)

        # Extract the newest run from this file
        runs = result_file.get("runs", [])
        if not runs:
            continue

        # All runs in a file are from the same invocation, but if there are
        # multiple files for the same (task, model), keep only the latest one
        # (determined by which file we process last, since results are sorted)
        for run in runs:
            # Aggregate per-profile stats from the run
            row: TaskModelResult = {
                "task": task,
                "model": model,
                "profile": run.get("profile", ""),
                "timestamp": "",
                "cost_usd": run.get("cost_usd", 0.0),
                "total_tokens": run.get("total_tokens", 0),
                "correctness_score": (run.get("correctness", {}) or {}).get("score") or 0.0,
            }

            # Keep newest by overwriting (files are sorted, so last = newest)
            profile_key = (task, model, run.get("profile", ""))
            latest[profile_key] = row

    return latest


def compute_deltas(
    latest: dict[tuple[str, str, str], dict]
) -> list[DeltaRow]:
    """Compute deltas (marvin - clean) per task and model tier.

    Expects latest to be keyed by (task_id, model, profile).
    Returns list of DeltaRow dicts, one per (task, tier, model).
    """
    deltas: list[DeltaRow] = []

    # Group by (task, model) to pair up clean vs marvin runs
    by_task_model: dict[tuple[str, str], dict[str, dict]] = {}
    for (task, model, profile), row in latest.items():
        key = (task, model)
        if key not in by_task_model:
            by_task_model[key] = {}
        by_task_model[key][profile] = row

    # Compute deltas for each (task, model) pair
    for (task, model), profiles in by_task_model.items():
        clean = profiles.get("clean")
        marvin = profiles.get("marvin")

        if not clean or not marvin:
            continue  # Skip if we don't have both profiles

        delta_row: DeltaRow = {
            "task": task,
            "tier": _model_to_tier(model),
            "model": model,
            "clean_cost": clean.get("cost_usd", 0.0),
            "marvin_cost": marvin.get("cost_usd", 0.0),
            "cost_delta": marvin.get("cost_usd", 0.0) - clean.get("cost_usd", 0.0),
            "clean_tokens": clean.get("total_tokens", 0),
            "marvin_tokens": marvin.get("total_tokens", 0),
            "token_delta": marvin.get("total_tokens", 0) - clean.get("total_tokens", 0),
            "clean_correctness": clean.get("correctness_score", 0.0),
            "marvin_correctness": marvin.get("correctness_score", 0.0),
        }
        deltas.append(delta_row)

    return deltas


def _model_to_tier(model: str) -> str:
    """Map model id to tier name."""
    if "haiku" in model.lower():
        return "Haiku"
    if "opus" in model.lower():
        return "Opus"
    # Default and sonnet both map to sonnet
    return "Sonnet"


def tier_rollup(
    deltas: list[DeltaRow],
    tier_order: list[str] = ["Haiku", "Sonnet", "Opus"]
) -> dict[str, dict]:
    """Aggregate deltas by tier; compute monotonic-trend check.

    Returns dict mapping tier name to rollup stats:
    - mean_cost_delta
    - mean_token_delta
    - mean_correctness_delta
    - tasks_in_tier
    """
    by_tier: dict[str, list[DeltaRow]] = {}

    for delta in deltas:
        tier = delta["tier"]
        if tier not in by_tier:
            by_tier[tier] = []
        by_tier[tier].append(delta)

    rollups = {}
    for tier in tier_order:
        if tier not in by_tier:
            rollups[tier] = {
                "mean_cost_delta": 0.0,
                "mean_token_delta": 0.0,
                "mean_correctness_delta": 0.0,
                "tasks": 0,
            }
            continue

        rows = by_tier[tier]
        cost_deltas = [r["cost_delta"] for r in rows]
        token_deltas = [r["token_delta"] for r in rows]
        correct_deltas = [r["marvin_correctness"] - r["clean_correctness"] for r in rows]

        rollups[tier] = {
            "mean_cost_delta": sum(cost_deltas) / len(cost_deltas) if cost_deltas else 0.0,
            "mean_token_delta": sum(token_deltas) / len(token_deltas) if token_deltas else 0.0,
            "mean_correctness_delta": sum(correct_deltas) / len(correct_deltas) if correct_deltas else 0.0,
            "tasks": len(rows),
        }

    return rollups


def format_markdown_table(deltas: list[DeltaRow]) -> str:
    """Format deltas as a markdown table, grouped by task then tier.

    Returns markdown-formatted table string.
    """
    if not deltas:
        return ""

    # Sort by task, then by tier order
    tier_order = {"Haiku": 0, "Sonnet": 1, "Opus": 2}
    deltas_sorted = sorted(deltas, key=lambda d: (d["task"], tier_order.get(d["tier"], 999)))

    lines = [
        "| Task | Tier | Model | Clean Cost | MARVIN Cost | Cost Δ | Clean Tok | MARVIN Tok | Tok Δ | Clean | MARVIN |",
        "|------|------|-------|------------|-------------|--------|-----------|-----------|-------|-------|--------|",
    ]

    for row in deltas_sorted:
        lines.append(
            f"| {row['task']} | {row['tier']} | {row['model']:40s} | "
            f"${row['clean_cost']:.4f} | ${row['marvin_cost']:.4f} | "
            f"${row['cost_delta']:+.4f} | {row['clean_tokens']:,} | {row['marvin_tokens']:,} | "
            f"{row['token_delta']:+,} | {row['clean_correctness']:.2f} | {row['marvin_correctness']:.2f} |"
        )

    return "\n".join(lines)
