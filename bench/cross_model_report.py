#!/usr/bin/env python3
"""cross_model_report.py — aggregate cross-model bench results (Haiku/Sonnet/Opus).

Compare MARVIN vs clean across three model tiers to validate the hypothesis that
MARVIN's advantage grows on weaker models, and to quantify per-task/per-tier costs.

Usage:
    python3 cross_model_report.py --results-dir bench/results --models default,claude-haiku-4-5-20251001,claude-opus-5
    python3 cross_model_report.py --results-dir bench/results --models "default,claude-haiku-4-5-20251001"
"""
from __future__ import annotations
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "lib"))
from cross_model_report import (  # noqa: E402
    load_results, latest_per_task_model, compute_deltas, tier_rollup, format_markdown_table,
)


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Aggregate cross-model bench results into per-tier/per-task deltas."
    )
    ap.add_argument("--results-dir", type=Path, default=ROOT / "results",
                    help="directory containing bench results/ .json files (default: bench/results)")
    ap.add_argument("--models", required=True, metavar="MODELS",
                    help="comma-separated model ids to include (e.g. default,claude-haiku-4-5-20251001,claude-opus-5)")
    ap.add_argument("--tier-order", default="Haiku,Sonnet,Opus", metavar="TIERS",
                    help="comma-separated tier names in order (default: Haiku,Sonnet,Opus)")
    args = ap.parse_args()

    models = [m.strip() for m in args.models.split(",")]
    tier_order = [t.strip() for t in args.tier_order.split(",")]

    # Load and aggregate
    if not args.results_dir.exists():
        print(f"Results directory not found: {args.results_dir}", file=sys.stderr)
        sys.exit(1)

    results = load_results(args.results_dir, models)
    if not results:
        print(f"No results found matching models {models} in {args.results_dir}", file=sys.stderr)
        sys.exit(1)

    latest = latest_per_task_model(results)
    deltas = compute_deltas(latest)
    rollups = tier_rollup(deltas, tier_order)

    # Print the table
    table = format_markdown_table(deltas)
    print(table)
    print()

    # Print tier rollup summary
    print("## Tier Rollup Summary\n")
    for tier in tier_order:
        if tier in rollups:
            r = rollups[tier]
            print(f"**{tier}** ({r['tasks']} tasks):")
            print(f"  Mean cost delta: ${r['mean_cost_delta']:+.4f}")
            print(f"  Mean token delta: {r['mean_token_delta']:+.0f} tokens")
            print(f"  Mean correctness delta: {r['mean_correctness_delta']:+.3f}")
            print()

    # Trend analysis
    print("## Trend Analysis (monotonic shrinking hypothesis)\n")
    print("If MARVIN's advantage shrinks on stronger models, cost_delta should approach zero.")
    print()

    cost_deltas_by_tier = {tier: rollups[tier]["mean_cost_delta"] for tier in tier_order if tier in rollups}
    if len(cost_deltas_by_tier) >= 2:
        deltas_list = [cost_deltas_by_tier.get(t, 0.0) for t in tier_order if t in cost_deltas_by_tier]
        is_shrinking = all(
            deltas_list[i] >= deltas_list[i + 1]  # cost_delta should decrease (become less negative)
            for i in range(len(deltas_list) - 1)
        )
        verdict = "✓ CONFIRMED" if is_shrinking else "✗ NOT CONFIRMED"
        print(f"{verdict}: Cost delta shrinking across tiers (lower cost advantage on stronger models)")
        print(f"  Haiku: {deltas_list[0]:+.4f} → Sonnet: {deltas_list[1]:+.4f}" +
              (f" → Opus: {deltas_list[2]:+.4f}" if len(deltas_list) > 2 else ""))
    print()


if __name__ == "__main__":
    main()
