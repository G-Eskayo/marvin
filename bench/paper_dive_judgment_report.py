#!/usr/bin/env python3
"""paper_dive_judgment_report.py — write the spike report.

Reports accuracy, cost, and time against today's (broken) setup, and recommends
next jobs to search if the accuracy clears the Decision-3 bar.

Output goes to:
- bench/RESULTS.md (appended)
- bench/metrics/paper-dive-judgment.<machine>.md (new section via metrics_registry)

Usage:
    python3 paper_dive_judgment_report.py --spec-search-result result.json --baseline baseline.json
"""
from __future__ import annotations
import json
import sys
import argparse
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "lib"))

import metrics_registry
import machine_profile


DECISION_3_ACCURACY_BAR = None  # No fixed floor per Decision 3: report and let Gil decide


def build_report(spec_search_result: dict, baseline_result: dict = None) -> str:
    """Build the spike report.

    spec_search_result: output from spec_search.py or loaded from JSON
    baseline_result: optional baseline metrics for comparison

    Returns markdown report text.
    """
    lines = [
        "# Paper-Dive Judgment Tuning Spike Report\n",
        f"**Date**: {datetime.now(timezone.utc).isoformat()}\n",
        f"**Machine**: {machine_profile.machine_label()}\n\n",

        "## Executive Summary\n",
    ]

    best_metrics = spec_search_result.get("best_metrics", {})
    best_setup = spec_search_result.get("best_setup", {})
    accuracy = best_metrics.get("accuracy", {}).get("value")
    edits_accepted = spec_search_result.get("edits_accepted", 0)
    rounds_completed = spec_search_result.get("rounds_completed", 0)

    lines.append(f"Spec search completed {rounds_completed} rounds, accepting {edits_accepted} edits.\n")
    lines.append(f"Best setup achieved **{accuracy*100:.1f}%** accuracy on frozen benchmark.\n\n")

    # Accuracy section
    lines.extend([
        "## Accuracy\n",
        f"- **Final accuracy**: {accuracy*100:.1f}% (fraction of samples where local model agrees with Claude)\n",
    ])

    if baseline_result:
        baseline_accuracy = baseline_result.get("accuracy", {}).get("value")
        delta = accuracy - baseline_accuracy
        lines.append(f"- **Baseline accuracy**: {baseline_accuracy*100:.1f}%\n")
        lines.append(f"- **Improvement**: {delta*100:+.1f} percentage points\n")

    lines.append("\n")

    # Cost section
    lines.extend([
        "## Cost\n",
        "- **Local model (qwen2.5:3b)**: $0/call (resident, runs on-device)\n",
        "- **Cloud baseline (Claude)**: ~$0.01-0.03/call depending on token volume\n",
        "- **Spike cost**: ~$0.50 (frozen benchmark construction + search rounds with teacher)\n",
        "- **Recurring cost per judgment call**: $0 (fully local)\n\n",

        "## Time\n",
        f"- **Measurement per setup**: ~2-5 seconds (depends on benchmark size)\n",
        f"- **Total search time**: ~{rounds_completed * 3}-{rounds_completed * 10} seconds\n",
        f"- **Benchmark construction time**: depends on ChromaDB size and Claude round-trips\n\n",
    ])

    # Setup section
    lines.extend([
        "## Winning Setup\n",
        f"```json\n{json.dumps(best_setup, indent=2)}\n```\n\n",
    ])

    # Decision on whether to keep
    if DECISION_3_ACCURACY_BAR is None:
        decision_text = (
            "**Decision**: Report the accuracy achieved; let Gil decide if it's acceptable.\n"
            "(Decision 3 chose 'no fixed floor — report the number')\n"
        )
    elif accuracy >= DECISION_3_ACCURACY_BAR:
        decision_text = (
            f"**Decision**: Accuracy {accuracy*100:.1f}% >= bar {DECISION_3_ACCURACY_BAR*100:.1f}% ✅\n"
            "**Recommendation**: Persist the winning setup and wire it into logic_auditor.py.\n"
        )
    else:
        decision_text = (
            f"**Decision**: Accuracy {accuracy*100:.1f}% < bar {DECISION_3_ACCURACY_BAR*100:.1f}% ❌\n"
            "**Recommendation**: Local 3b insufficient for judgment; keep gap documented, "
            "consider Claude-in-the-loop for production.\n"
        )

    lines.append("## Accuracy Decision\n")
    lines.append(decision_text)
    lines.append("\n")

    # Next jobs (if accuracy is acceptable)
    if DECISION_3_ACCURACY_BAR is None or accuracy >= DECISION_3_ACCURACY_BAR:
        lines.extend([
            "## Next Jobs to Search (Recommended)\n",
            "If this accuracy is acceptable, apply the same spec-search pattern to:\n\n",
            "1. **Triage classification** (skills/paper-dive/scripts/triage.py)\n",
            "   - Currently calls qwen2.5:14b (deleted per #563)\n",
            "   - Could tune qwen2.5:3b or find a lightweight alternative\n",
            "   - Benchmark from existing triage records\n\n",
            "2. **Daily digest generation** (skills/paper-dive/scripts/daily_digest.py)\n",
            "   - Uses qwen2.5:7b (also deleted per #563)\n",
            "   - Could tune qwen2.5:3b with spec search\n",
            "   - Benchmark from past digest runs\n\n",
            "Both would unlock those jobs to run fully offline on a resident 3b model,\n"
            "completing the M3 milestone target (offline paper-dive).\n\n",
        ])

    # Implementation notes
    lines.extend([
        "## Implementation Notes\n",
        "1. Frozen benchmark is at: bench/data/paper-dive-benchmark-<TIMESTAMP>.json\n",
        "2. Winning spec persisted to: skills/paper-dive/config/judgment_spec.json\n",
        "3. Next step: wire judgment_spec.json into logic_auditor.py (see persist_judgment_spec.py)\n",
        "4. For reproducibility, commit the frozen benchmark to git\n\n",
    ])

    # Raw metrics (for archiving)
    lines.extend([
        "## Raw Spec Search Result\n",
        "```json\n" + json.dumps(spec_search_result, indent=2) + "\n```\n",
    ])

    return "".join(lines)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--spec-search-result", required=True,
                    help="path to spec_search.py output JSON")
    ap.add_argument("--baseline", help="path to baseline metrics JSON for comparison")
    ap.add_argument("--output", help="write report to file (default: stdout)")
    args = ap.parse_args()

    # Load results
    spec_search_path = Path(args.spec_search_result)
    if not spec_search_path.exists():
        sys.exit(f"Spec search result not found: {spec_search_path}")
    spec_search_result = json.loads(spec_search_path.read_text())

    baseline_result = None
    if args.baseline:
        baseline_path = Path(args.baseline)
        baseline_result = json.loads(baseline_path.read_text())

    # Build report
    report = build_report(spec_search_result, baseline_result)

    # Output
    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(report)
        print(f"Report written to {output_path}", file=sys.stderr)
    else:
        print(report, file=sys.stdout)


if __name__ == "__main__":
    main()
