#!/usr/bin/env python3
"""run_judgment_spec_search.py — CLI driver for judgment spec optimization.

Builds benchmark, runs spec search, writes results to outbox.

Usage:
    python3 run_judgment_spec_search.py --build-benchmark --sample-size 10
    python3 run_judgment_spec_search.py --search --benchmark benchmark.json \\
        --max-iterations 5 --accuracy-threshold 0.90
    python3 run_judgment_spec_search.py --build-benchmark --search --sample-size 10
"""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lib"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "bench"))

import judgment_benchmark  # noqa: E402
import judgment_spec  # noqa: E402
import metrics_registry  # noqa: E402

# Lazy-import spec_search since it's in a sibling directory
_spec_search = None


def get_spec_search():
    """Lazy-load spec_search module."""
    global _spec_search
    if _spec_search is None:
        import spec_search  # noqa: E402
        _spec_search = sys.modules['spec_search']
    return _spec_search


def find_outbox() -> Path:
    """Locate the MARVIN outbox for writing results."""
    outbox_candidates = [
        Path.home() / ".claude" / "outbox",
        Path.home() / "Documents" / "MARVIN" / "outbox",
        Path.home() / "Documents" / "outbox",
    ]
    for candidate in outbox_candidates:
        if candidate.exists() and candidate.is_dir():
            return candidate
    # Create in home if none exist
    outbox = Path.home() / ".claude" / "outbox"
    outbox.mkdir(parents=True, exist_ok=True)
    return outbox


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Build benchmark and/or run judgment spec search."
    )
    ap.add_argument(
        "--build-benchmark",
        action="store_true",
        help="Build gold-label benchmark from paper-knowledge collection"
    )
    ap.add_argument(
        "--sample-size",
        type=int,
        default=10,
        help="Number of papers to sample for benchmark (default 10)"
    )
    ap.add_argument(
        "--search",
        action="store_true",
        help="Run spec search after building benchmark (or against existing one)"
    )
    ap.add_argument(
        "--benchmark",
        help="Path to existing benchmark JSON (if not building new one)"
    )
    ap.add_argument(
        "--max-iterations",
        type=int,
        default=10,
        help="Max iterations for spec search (default 10)"
    )
    ap.add_argument(
        "--accuracy-threshold",
        type=float,
        default=0.95,
        help="Stop search when accuracy >= this value (default 0.95)"
    )
    ap.add_argument(
        "--out",
        help="Output file for search results (default: outbox/judgment_spec_search_<timestamp>.json)"
    )
    args = ap.parse_args()

    if not args.build_benchmark and not args.search:
        ap.print_help()
        sys.exit(1)

    # Step 1: Build benchmark if requested
    benchmark_path = None
    benchmark = None

    if args.build_benchmark:
        benchmark_path = Path("/tmp") / f"judgment_benchmark_{datetime.now().isoformat()}.json"
        print(f"Building benchmark ({args.sample_size} papers)...", flush=True)
        try:
            benchmark = judgment_benchmark.build_benchmark(args.sample_size)
            judgment_benchmark.save_benchmark(benchmark, benchmark_path)
            print(f"Benchmark saved to {benchmark_path}", flush=True)
        except Exception as e:
            print(f"Error building benchmark: {e}", file=sys.stderr, flush=True)
            sys.exit(1)
    elif args.benchmark:
        benchmark_path = Path(args.benchmark)
        if not benchmark_path.exists():
            print(f"Benchmark file not found: {args.benchmark}", file=sys.stderr)
            sys.exit(1)
        print(f"Loading benchmark from {benchmark_path}...", flush=True)
        benchmark = json.loads(benchmark_path.read_text())
        print(f"Loaded {len(benchmark)} benchmarks.", flush=True)

    # Step 2: Run search if requested
    search_result = None
    if args.search:
        if benchmark is None:
            print("Error: search requires a benchmark (--build-benchmark or --benchmark)", file=sys.stderr)
            sys.exit(1)

        print(f"\nStarting spec search ({args.max_iterations} iterations, {args.accuracy_threshold:.2%} threshold)...", flush=True)

        try:
            spec_search_module = get_spec_search()
            search_result = spec_search_module.run_search(
                baseline_spec=judgment_spec.DEFAULT_SPEC,
                score_fn=judgment_spec.score_spec,
                benchmark=benchmark,
                max_iterations=args.max_iterations,
                accuracy_threshold=args.accuracy_threshold,
            )
            print(f"Search complete: best accuracy = {search_result['best']['accuracy']:.2%}", flush=True)
        except Exception as e:
            print(f"Error running search: {e}", file=sys.stderr, flush=True)
            sys.exit(1)

    # Step 3: Record metrics and write results
    if search_result:
        outbox = find_outbox()
        out_file = args.out or (
            outbox / f"judgment_spec_search_{datetime.now().isoformat().replace(':', '-')}.json"
        )

        # Record metrics
        metrics_to_record = {
            "accuracy": {
                "value": search_result["best"]["accuracy"],
                "higher_is_better": True,
            },
            "iterations": {
                "value": search_result["total_iterations"],
                "higher_is_better": False,
            },
        }

        try:
            metrics_registry.record("judgment-spec-search", metrics_to_record)
            print(f"Metrics recorded to metrics registry.", flush=True)
        except Exception as e:
            print(f"Warning: could not record metrics: {e}", flush=True)

        # Write full result
        result_data = {
            "timestamp": datetime.now().isoformat(),
            "benchmark_size": len(benchmark) if benchmark else 0,
            "search_result": search_result,
        }

        try:
            Path(out_file).write_text(json.dumps(result_data, indent=2))
            print(f"Results written to {out_file}", flush=True)
        except Exception as e:
            print(f"Error writing results: {e}", file=sys.stderr, flush=True)
            sys.exit(1)

        # Print summary
        print(f"\n=== JUDGMENT SPEC SEARCH RESULTS ===")
        print(f"Baseline accuracy: {search_result['baseline']['accuracy']:.2%}")
        print(f"Best accuracy: {search_result['best']['accuracy']:.2%}")
        print(f"Iterations: {search_result['total_iterations']}")
        print(f"Stopped: {search_result['stopped_reason']}")
        print(f"\nNext jobs to search:")
        print(f"  - Triage classification accuracy")
        print(f"  - Daily digest relevance")
        print(f"  - Cross-paper consistency judgment")


if __name__ == "__main__":
    main()
