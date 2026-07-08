#!/usr/bin/env python3
"""
run_mlx_model_comparison.py — real MMLU-Pro comparison for Qwen2.5-3B vs Llama-3.2-3B,
via the in-process MLX loglikelihood adapter (lib/mlx_lm_eval_adapter.py).

Usage: ~/.agents/venv/bin/python run_mlx_model_comparison.py [--limit N]
"""
from __future__ import annotations
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))
import mlx_lm_eval_adapter  # noqa: F401 — import triggers @register_model("mlx-inprocess")

from lm_eval import simple_evaluate

MODELS = {
    "qwen2.5-3b": "mlx-community/Qwen2.5-3B-Instruct-4bit",
    "llama-3.2-3b": "mlx-community/Llama-3.2-3B-Instruct-4bit",
}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=200)
    ap.add_argument("--task", default="leaderboard_mmlu_pro")
    args = ap.parse_args()

    results = {}
    for label, repo in MODELS.items():
        print(f"\n=== {label} ({repo}) ===")
        eval_results = simple_evaluate(
            model="mlx-inprocess",
            model_args={"pretrained": repo},
            tasks=[args.task],
            limit=args.limit,
            apply_chat_template=True,
            fewshot_as_multiturn=True,
        )
        results[label] = eval_results["results"][args.task]
        print(results[label])

    print("\n=== Comparison ===")
    for label, metrics in results.items():
        print(f"{label}: {metrics}")


if __name__ == "__main__":
    main()
