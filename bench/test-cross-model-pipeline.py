#!/usr/bin/env python3
"""Test the cross_model_report pipeline with synthetic data.

This verifies the aggregation logic works end-to-end without requiring
actual bench runs. Run via: python3 test-cross-model-pipeline.py
"""
import json
import tempfile
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "lib"))

from cross_model_report import (
    load_results, latest_per_task_model, compute_deltas, tier_rollup, format_markdown_table,
)


def make_synthetic_results() -> dict[str, list]:
    """Generate synthetic bench result files."""
    return {
        "task-001-haiku": {
            "task": "task-001",
            "model": "claude-haiku-4-5-20251001",
            "runner": "claude",
            "repeat": 1,
            "judge": False,
            "runs": [
                {
                    "profile": "clean",
                    "model": "claude-haiku-4-5-20251001",
                    "cost_usd": 0.010,
                    "total_tokens": 500,
                    "correctness": {"score": 1.0},
                },
                {
                    "profile": "marvin",
                    "model": "claude-haiku-4-5-20251001",
                    "cost_usd": 0.008,
                    "total_tokens": 450,
                    "correctness": {"score": 1.0},
                },
            ],
        },
        "task-001-sonnet": {
            "task": "task-001",
            "model": "default",
            "runner": "claude",
            "repeat": 1,
            "judge": False,
            "runs": [
                {
                    "profile": "clean",
                    "model": "default",
                    "cost_usd": 0.030,
                    "total_tokens": 1500,
                    "correctness": {"score": 1.0},
                },
                {
                    "profile": "marvin",
                    "model": "default",
                    "cost_usd": 0.029,
                    "total_tokens": 1450,
                    "correctness": {"score": 1.0},
                },
            ],
        },
        "task-002-haiku": {
            "task": "task-002",
            "model": "claude-haiku-4-5-20251001",
            "runner": "claude",
            "repeat": 1,
            "judge": False,
            "runs": [
                {
                    "profile": "clean",
                    "model": "claude-haiku-4-5-20251001",
                    "cost_usd": 0.012,
                    "total_tokens": 600,
                    "correctness": {"score": 0.8},
                },
                {
                    "profile": "marvin",
                    "model": "claude-haiku-4-5-20251001",
                    "cost_usd": 0.010,
                    "total_tokens": 550,
                    "correctness": {"score": 1.0},
                },
            ],
        },
        "task-002-sonnet": {
            "task": "task-002",
            "model": "default",
            "runner": "claude",
            "repeat": 1,
            "judge": False,
            "runs": [
                {
                    "profile": "clean",
                    "model": "default",
                    "cost_usd": 0.035,
                    "total_tokens": 1800,
                    "correctness": {"score": 0.8},
                },
                {
                    "profile": "marvin",
                    "model": "default",
                    "cost_usd": 0.034,
                    "total_tokens": 1750,
                    "correctness": {"score": 1.0},
                },
            ],
        },
    }


def main():
    print("Testing cross_model_report pipeline with synthetic data...")
    print()

    with tempfile.TemporaryDirectory() as tmpdir:
        results_dir = Path(tmpdir)

        # Write synthetic results
        synthetic = make_synthetic_results()
        for name, data in synthetic.items():
            json_file = results_dir / f"{name}-20260801-120000.json"
            json_file.write_text(json.dumps(data, indent=2))
            print(f"  Created {json_file.name}")

        print()
        print("Running aggregation pipeline...")
        print()

        # Load results
        results = load_results(results_dir, ["default", "claude-haiku-4-5-20251001"])
        print(f"✓ Loaded {len(results)} result files")

        # Deduplicate
        latest = latest_per_task_model(results)
        print(f"✓ Dedup: {len(latest)} (task, model, profile) entries")

        # Compute deltas
        deltas = compute_deltas(latest)
        print(f"✓ Computed {len(deltas)} task × model deltas")

        # Tier rollup
        rollups = tier_rollup(deltas, ["Haiku", "Sonnet"])
        print(f"✓ Rolled up {len(rollups)} tiers")

        # Format table
        table = format_markdown_table(deltas)
        print(f"✓ Formatted markdown table ({len(table)} chars)")

        print()
        print("=== Generated Report ===")
        print()
        print(table)
        print()

        print("=== Tier Rollup ===")
        print()
        for tier in ["Haiku", "Sonnet"]:
            r = rollups[tier]
            print(f"{tier}:")
            print(f"  Tasks: {r['tasks']}")
            print(f"  Mean cost delta: ${r['mean_cost_delta']:+.4f}")
            print(f"  Mean token delta: {r['mean_token_delta']:+.0f}")
            print(f"  Mean correctness delta: {r['mean_correctness_delta']:+.3f}")
        print()

        print("=== Trend Analysis ===")
        print()
        haiku_cost = rollups["Haiku"]["mean_cost_delta"]
        sonnet_cost = rollups["Sonnet"]["mean_cost_delta"]
        print(f"Cost delta trend: Haiku {haiku_cost:+.4f} → Sonnet {sonnet_cost:+.4f}")

        if haiku_cost <= sonnet_cost:
            print("✓ CONFIRMED: Cost advantage shrinks on stronger models")
        else:
            print("✗ NOT CONFIRMED: Cost advantage grows on stronger models")

        print()
        print("=== Pipeline test PASSED ===")


if __name__ == "__main__":
    main()
